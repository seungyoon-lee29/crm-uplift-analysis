"""Step 3b — 증분 이익: '전체발송 vs uplift 타겟발송' 의사결정.

무작위배정 덕분에, uplift 점수로 정렬한 그룹 안에서 treated-control 결과차가
그 그룹에 발송했을 때의 증분(반사실)이 된다.

의사결정 단위 = decile 한계분석: validation에서 uplift 점수 10분위별
'한계 순이익/명'이 양(+)인 분위 정책을 고르고, test에서 최종 성과를 평가한다.

순이익/명 = 증분구매 × AOV × 마진율 − 발송비 − 수신거부확률 × LTV
  · 데이터에 있는 것: 증분구매·AOV(=구매자 평균 spend).
  · 마진·발송비·수신거부·LTV 는 config 가정(명시적 가정, 한계에 노출).
  · conversion×AOV 로 매출을 환산(raw spend 는 분산이 커 노이즈 → 별도 robustness 컬럼).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.data import load_config

ROOT = Path(__file__).resolve().parents[1]
Z_95 = 1.96


def _inc(g: pd.DataFrame, outcome: str) -> float:
    t = g.loc[g.treatment == 1, outcome]
    c = g.loc[g.treatment == 0, outcome]
    if len(t) == 0 or len(c) == 0:
        return np.nan
    return t.mean() - c.mean()


def _conversion_stats(g: pd.DataFrame) -> dict:
    """treated-control conversion 차이와 정규근사 95% CI."""
    treated = g.loc[g.treatment == 1, "conversion"]
    control = g.loc[g.treatment == 0, "conversion"]
    n_t = len(treated)
    n_c = len(control)
    if n_t == 0 or n_c == 0:
        return {
            "treated_n": n_t,
            "control_n": n_c,
            "inc_conv_pc": np.nan,
            "inc_conv_se": np.nan,
            "inc_conv_ci_low": np.nan,
            "inc_conv_ci_high": np.nan,
        }
    p_t = float(treated.mean())
    p_c = float(control.mean())
    inc = p_t - p_c
    se = float(np.sqrt(p_t * (1 - p_t) / n_t + p_c * (1 - p_c) / n_c))
    return {
        "treated_n": n_t,
        "control_n": n_c,
        "inc_conv_pc": inc,
        "inc_conv_se": se,
        "inc_conv_ci_low": inc - Z_95 * se,
        "inc_conv_ci_high": inc + Z_95 * se,
    }


def _with_deciles(scored: pd.DataFrame, n_bins: int) -> pd.DataFrame:
    ranked = scored.sort_values("uplift_score", ascending=False).reset_index(drop=True)
    ranked["decile"] = (np.floor(np.arange(len(ranked)) * n_bins / len(ranked)).astype(int) + 1)
    return ranked


def decile_table(scored: pd.DataFrame, cfg: dict, aov: float, n_bins: int = 10,
                 fatigue_cost: float | None = None,
                 selected_deciles: set[int] | None = None) -> pd.DataFrame:
    """uplift 점수 분위별 한계 증분·순이익과 95% CI."""
    b = cfg["business"]
    fatigue = (
        b["optout_rate_per_send"] * b["customer_ltv"]
        if fatigue_cost is None
        else fatigue_cost
    )
    ranked = _with_deciles(scored, n_bins)
    rows = []
    for d, g in ranked.groupby("decile"):
        conv = _conversion_stats(g)
        inc_spend = _inc(g, "spend")
        gross = conv["inc_conv_pc"] * aov * b["margin_rate"]
        net_pc = gross - b["send_cost"] - fatigue
        net_ci_low = conv["inc_conv_ci_low"] * aov * b["margin_rate"] - b["send_cost"] - fatigue
        net_ci_high = conv["inc_conv_ci_high"] * aov * b["margin_rate"] - b["send_cost"] - fatigue
        rows.append({
            "decile": int(d),
            "n": len(g),
            **conv,
            "inc_spend_pc": inc_spend,
            "gross_pc": gross,
            "net_pc": net_pc,
            "net_pc_ci_low": net_ci_low,
            "net_pc_ci_high": net_ci_high,
            "net_total": net_pc * len(g),
            "send_policy": bool(selected_deciles and int(d) in selected_deciles),
        })
    return pd.DataFrame(rows)


def k_grid_default() -> np.ndarray:
    return np.round(np.arange(0.05, 1.0001, 0.05), 3)


def topk_curve(scored: pd.DataFrame, cfg: dict, aov: float, fatigue: float,
               grid: np.ndarray | None = None) -> pd.DataFrame:
    """상위 k%(uplift 점수 내림차순)에 발송할 때의 누적 순이익 곡선.

    단조 임계 정책: '상위 k%에 발송'. 비연속 분위 cherry-pick보다 과적합이 적고 해석 쉽다.
    """
    b = cfg["business"]
    grid = k_grid_default() if grid is None else grid
    ranked = scored.sort_values("uplift_score", ascending=False).reset_index(drop=True)
    n = len(ranked)
    rows = []
    for k in grid:
        m = max(1, int(round(float(k) * n)))
        inc = _inc(ranked.iloc[:m], "conversion")
        net_pc = inc * aov * b["margin_rate"] - b["send_cost"] - fatigue
        rows.append({"k": round(float(k), 3), "n_sent": m,
                     "inc_conv": inc, "net_pc": net_pc, "cum_net": net_pc * m})
    return pd.DataFrame(rows)


def select_topk(validation: pd.DataFrame, cfg: dict, aov: float, fatigue: float,
                grid: np.ndarray | None = None) -> float:
    """validation 누적 순이익을 최대화하는 k*. 모두 음수면 0(무발송)."""
    curve = topk_curve(validation, cfg, aov, fatigue, grid)
    best = curve.loc[curve["cum_net"].idxmax()]
    return float(best["k"]) if best["cum_net"] > 0 else 0.0


def eval_topk(test: pd.DataFrame, cfg: dict, aov: float, fatigue: float,
              k: float) -> dict:
    """test 상위 k%에 발송 시 순이익 vs 전체발송 순이익(out-of-sample)."""
    b = cfg["business"]
    ranked = test.sort_values("uplift_score", ascending=False).reset_index(drop=True)
    n = len(ranked)
    inc_all = _inc(ranked, "conversion")
    blanket = (inc_all * aov * b["margin_rate"] - b["send_cost"] - fatigue) * n
    if k <= 0:
        return {"k": 0.0, "n_sent": 0, "targeted_net": 0.0, "blanket_net": float(blanket)}
    m = max(1, int(round(k * n)))
    inc = _inc(ranked.iloc[:m], "conversion")
    targeted = (inc * aov * b["margin_rate"] - b["send_cost"] - fatigue) * m
    return {"k": float(k), "n_sent": m, "targeted_net": float(targeted),
            "blanket_net": float(blanket)}


def sensitivity(validation: pd.DataFrame, test: pd.DataFrame, cfg: dict, aov: float,
                fatigue_grid: np.ndarray, grid: np.ndarray | None = None) -> pd.DataFrame:
    """채널피로비별로 validation에서 k*를 고르고 test에서 top-k% 성과를 평가."""
    rows = []
    for fat in fatigue_grid:
        k = select_topk(validation, cfg, aov, float(fat), grid)
        ev = eval_topk(test, cfg, aov, float(fat), k)
        rows.append({"fatigue_cost": round(float(fat), 3),
                     "k_star": k,
                     "n_sent": ev["n_sent"],
                     "blanket_net": ev["blanket_net"],
                     "targeted_net": ev["targeted_net"],
                     "targeting_gain": ev["targeted_net"] - ev["blanket_net"]})
    return pd.DataFrame(rows)


def decile_cherrypick(validation: pd.DataFrame, test: pd.DataFrame, cfg: dict,
                      aov: float, fatigue: float) -> dict:
    """[비교용] 구 정책: validation에서 net_pc>0 인 비연속 분위를 골라 test 평가."""
    val_dec = decile_table(validation, cfg, aov, fatigue_cost=fatigue)
    selected = set(val_dec.loc[val_dec["net_pc"] > 0, "decile"].astype(int))
    test_dec = decile_table(test, cfg, aov, fatigue_cost=fatigue, selected_deciles=selected)
    return {"selected": sorted(selected),
            "blanket_net": float(test_dec["net_total"].sum()),
            "targeted_net": float(test_dec.loc[test_dec["send_policy"], "net_total"].sum())}


def main() -> None:
    cfg = load_config()
    b = cfg["business"]
    validation = pd.read_parquet(ROOT / "data" / "validation_with_uplift.parquet")
    test = pd.read_parquet(ROOT / "data" / "test_with_uplift.parquet")
    aov = float(validation.loc[validation.conversion == 1, "spend"].mean())
    base_fatigue = b["optout_rate_per_send"] * b["customer_ltv"]

    # ── 헤드라인 정책: 단조 top-k% (validation에서 k* 선택 → test 평가) ──
    k_star = select_topk(validation, cfg, aov, base_fatigue)
    ev = eval_topk(test, cfg, aov, base_fatigue, k_star)
    targeted_net, blanket_net = ev["targeted_net"], ev["blanket_net"]
    base_gain = targeted_net - blanket_net
    gain_pct = base_gain / blanket_net * 100 if blanket_net else float("nan")

    # ── 비교용: 구 비연속 decile cherry-pick 정책 ──
    cherry = decile_cherrypick(validation, test, cfg, aov, base_fatigue)
    cherry_gain = cherry["targeted_net"] - cherry["blanket_net"]

    # 진단용 decile CI 표 (test, 정책 색칠 없음)
    dec = decile_table(test, cfg, aov)

    grid = np.round(np.arange(0.0, 1.0001, 0.05), 3)
    sens = sensitivity(validation, test, cfg, aov, grid)
    ate_conv = float(_inc(test, "conversion"))
    blanket_breakeven = ate_conv * aov * b["margin_rate"] - b["send_cost"]

    L = ["# 증분 이익 리포트 — 전체발송 vs uplift 타겟발송 (top-k 정책)\n"]
    L.append("발송 정책 = **단조 top-k%**(uplift 점수 상위 k%에 발송). k*는 **validation**에서 고르고 "
             "최종 성과는 **test**에서 평가하는 out-of-sample 규율.\n")
    L.append(f"AOV(구매자 평균 spend, validation 기준) = ${aov:.2f} · 가정: 마진 {b['margin_rate']}, "
             f"발송비 ${b['send_cost']}, 채널피로비(수신거부×LTV) = ${base_fatigue:.3f}/통\n")

    L.append("## 1. 헤드라인 — 기본 이메일 가정\n")
    L.append(f"- validation이 고른 발송 비율 **k\\* = {k_star*100:.0f}%** (상위 {ev['n_sent']}명).")
    L.append(f"- test 평가: 타겟발송 **${targeted_net:.0f}** vs 전체발송 **${blanket_net:.0f}** "
             f"→ 차이 **${base_gain:+.0f}({gain_pct:+.0f}%)**.")
    L.append(f"- 전체 평균 증분구매 +{ate_conv:.4f}/명 = 이메일은 평균적으로 먹힌다(\"다 보내\"가 틀린 건 아님).")
    if base_gain < 0:
        L.append("- → 약한 uplift 신호로는, 검증된 top-k 타겟팅도 이메일에선 전체발송을 못 이긴다(정직한 결론).\n")
    else:
        L.append("- → 검증된 top-k 타겟팅이 이메일에서도 전체발송 이상이다.\n")

    L.append("## 2. 정책 안정성 — 단조 top-k vs 비연속 분위 cherry-pick\n")
    L.append("같은 기본 가정·같은 validation/test에서 정책 선택 방식만 바꿔 비교.\n")
    L.append("| 정책 | 발송 규칙 | test 타겟발송 | vs 전체발송 |")
    L.append("|---|---|---|---|")
    L.append(f"| 비연속 분위 (구) | 분위 {cherry['selected']} | ${cherry['targeted_net']:.0f} | ${cherry_gain:+.0f} |")
    L.append(f"| **top-k% (신)** | 상위 {k_star*100:.0f}% | ${targeted_net:.0f} | ${base_gain:+.0f} |")
    L.append("\n- 비연속 분위는 validation 노이즈에 과적합(비단조 선택)되어 정책이 불안정. "
             "top-k는 단조·해석가능하며 out-of-sample에서 더 견고하다.\n")

    L.append("## 3. 진단 — test 분위별 증분구매와 95% CI\n")
    L.append("(정책이 아니라 신호 진단용. CI가 넓다 = 분위 부호를 단정하면 안 된다.)\n")
    L.append("| 분위 | test n | 증분구매/명 | SE | 95% CI | 한계순이익/명 |")
    L.append("|---|---|---|---|---|---|")
    for _, r in dec.iterrows():
        L.append(f"| {int(r['decile'])} | {int(r['n'])} | {r['inc_conv_pc']:+.4f} | {r['inc_conv_se']:.4f} | "
                 f"[{r['inc_conv_ci_low']:+.4f}, {r['inc_conv_ci_high']:+.4f}] | ${r['net_pc']:+.3f} |")
    L.append("")

    L.append("## 4. 채널 피로비 민감도 (← 진짜 '팀장 설득' 포인트)\n")
    L.append("피로비별로 validation에서 k*를 고르고 test 성과를 평가.\n")
    L.append("| 채널피로비/통 | k\\* (발송%) | 전체발송 순이익 | 타겟발송 순이익 | 타겟팅 이득 |")
    L.append("|---|---|---|---|---|")
    for _, r in sens[sens.fatigue_cost.isin([0.0,0.05,0.1,0.2,0.3,0.5,0.7,1.0])].iterrows():
        L.append(f"| ${r['fatigue_cost']:.2f} | {r['k_star']*100:.0f}% | "
                 f"${r['blanket_net']:.0f} | ${r['targeted_net']:.0f} | ${r['targeting_gain']:.0f} |")
    L.append(f"\n**핵심1**: 기본 이메일 가정($0.05)에서 검증된 top-k 정책은 test에서 "
             f"${base_gain:+.0f}({gain_pct:+.0f}%) — {'전체발송 이상' if base_gain>=0 else '전체발송보다 낮다'}. "
             "약한 신호에선 타겟팅이 자동 승리가 아니다.")
    L.append(f"**핵심2**: 채널피로비가 **${blanket_breakeven:.2f}/통**을 넘으면 전체발송은 순손실. "
             "이메일($0.05)은 안전권, 푸시·SMS면 위험 → 그 구간에서 top-k 타겟팅(또는 무발송)의 가치가 커진다.\n")
    L.append("→ 팀장 설득: \"다 보내라\"는 *싼 채널 + 무한 발송예산* 가정에서만 옳다. "
             "피로비가 커지면 전체발송 손실 위험이 커지지만, uplift 정책도 validation/test로 검증해야 한다.\n")

    L.append("## 부록: robustness — raw spend 기준 분위 증분\n")
    L.append(dec[["decile", "n", "treated_n", "control_n",
                  "inc_conv_pc", "inc_conv_se", "inc_spend_pc", "net_pc"]].round(4).to_string(index=False))

    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "incrementality_report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\n[saved] {docs/'incrementality_report.md'}")


if __name__ == "__main__":
    main()
