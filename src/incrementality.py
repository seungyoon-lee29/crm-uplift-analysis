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


def sensitivity(validation: pd.DataFrame, test: pd.DataFrame, cfg: dict, aov: float,
                fatigue_grid: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """채널피로비별로 validation 정책을 고르고 test 성과를 평가."""
    rows = []
    for fat in fatigue_grid:
        val_dec = decile_table(validation, cfg, aov, n_bins, fatigue_cost=float(fat))
        selected = set(val_dec.loc[val_dec["net_pc"] > 0, "decile"].astype(int))
        test_dec = decile_table(test, cfg, aov, n_bins, fatigue_cost=float(fat),
                                selected_deciles=selected)
        blanket_total = float(test_dec["net_total"].sum())
        targeted_total = float(test_dec.loc[test_dec["send_policy"], "net_total"].sum())
        rows.append({"fatigue_cost": round(float(fat), 3),
                     "deciles_sent": int(len(selected)),
                     "blanket_net": blanket_total,
                     "targeted_net": targeted_total,
                     "targeting_gain": targeted_total - blanket_total})
    return pd.DataFrame(rows)


def main() -> None:
    cfg = load_config()
    b = cfg["business"]
    validation = pd.read_parquet(ROOT / "data" / "validation_with_uplift.parquet")
    test = pd.read_parquet(ROOT / "data" / "test_with_uplift.parquet")
    aov = float(validation.loc[validation.conversion == 1, "spend"].mean())

    validation_dec = decile_table(validation, cfg, aov)
    selected_deciles = set(validation_dec.loc[validation_dec["net_pc"] > 0, "decile"].astype(int))
    dec = decile_table(test, cfg, aov, selected_deciles=selected_deciles)
    blanket_net = float(dec["net_total"].sum())
    targeted_net = float(dec.loc[dec["send_policy"], "net_total"].sum())

    base_fatigue = b["optout_rate_per_send"] * b["customer_ltv"]
    grid = np.round(np.arange(0.0, 1.0001, 0.05), 3)
    sens = sensitivity(validation, test, cfg, aov, grid)
    base_gain = float(targeted_net - blanket_net)
    # 전체발송이 순손실로 돌아서는 채널피로비 (blanket_net = N*(ATE_conv*AOV*margin - send) - N*fatigue = 0)
    ate_conv = float(_inc(test, "conversion"))
    blanket_breakeven = ate_conv * aov * b["margin_rate"] - b["send_cost"]

    L = ["# 증분 이익 리포트 — 전체발송 vs uplift 타겟발송\n"]
    L.append("정책 선택은 validation에서, 최종 성과 평가는 test에서 수행했다. "
             "따라서 아래 순이익은 validation에서 고른 발송 분위 정책을 test에 적용한 out-of-sample 평가다.\n")
    L.append(f"AOV(구매자 평균 spend, validation 기준) = ${aov:.2f} · 가정: 마진 {b['margin_rate']}, "
             f"발송비 ${b['send_cost']}, 채널피로비(수신거부×LTV) = ${base_fatigue:.3f}/통\n")

    L.append("## 1. validation 정책 → test 한계 순이익 by uplift 분위\n")
    L.append(f"validation에서 한계순이익이 양(+)인 발송 분위 = {sorted(selected_deciles)}\n")
    L.append("| 분위 | test n | 발송? | 증분구매/명 | SE | 95% CI | 한계순이익/명 | 순이익 95% CI |")
    L.append("|---|---|---|---|---|---|---|---|")
    for _, r in dec.iterrows():
        send = "Y" if r["send_policy"] else "N"
        L.append(f"| {int(r['decile'])} | {int(r['n'])} | {send} | "
                 f"{r['inc_conv_pc']:+.4f} | {r['inc_conv_se']:.4f} | "
                 f"[{r['inc_conv_ci_low']:+.4f}, {r['inc_conv_ci_high']:+.4f}] | "
                 f"${r['net_pc']:+.3f} | "
                 f"[${r['net_pc_ci_low']:+.3f}, ${r['net_pc_ci_high']:+.3f}] |")

    L.append(f"\n- 전체 평균은 증분구매 +{ate_conv:.4f}/명 = 이메일은 평균적으로 먹힌다(\"다 보내\"가 틀린 건 아님).")
    L.append(f"- validation에서 고른 {len(selected_deciles)}/10개 분위만 test에 발송하면 "
             f"순이익 변화는 ${base_gain:.0f}이다(타겟발송 ${targeted_net:.0f} vs 전체발송 ${blanket_net:.0f}).")
    L.append("- ⚠️ 분위별 증분구매의 95% CI가 넓다. 즉 '특정 분위 = 확정 sleeping-dog'은 과대주장 — "
             "의사결정 프레임은 타당하나 점추정은 추가 홀드아웃 재검증이 필요.\n")

    L.append("## 2. 채널 피로비 민감도 (← 진짜 '팀장 설득' 포인트)\n")
    L.append("수신거부 1건의 비용(채널피로비)을 얼마로 보느냐에 따라 답이 갈린다.\n")
    L.append("| 채널피로비/통 | 발송 분위수 | 전체발송 순이익 | 타겟발송 순이익 | 타겟팅 이득 |")
    L.append("|---|---|---|---|---|")
    for _, r in sens[sens.fatigue_cost.isin([0.0,0.05,0.1,0.2,0.3,0.5,0.7,1.0])].iterrows():
        L.append(f"| ${r['fatigue_cost']:.2f} | {int(r['deciles_sent'])} | "
                 f"${r['blanket_net']:.0f} | ${r['targeted_net']:.0f} | ${r['targeting_gain']:.0f} |")
    gain_pct = base_gain / blanket_net * 100 if blanket_net else np.nan
    if base_gain >= 0:
        L.append(f"\n**핵심1 (타겟팅은 test에서도 우위)**: validation에서 양(+)으로 보인 분위만 발송하는 정책은 "
                 f"기본 가정($0.05)의 test 평가에서 ${base_gain:+.0f}({gain_pct:+.0f}%)이다.")
    else:
        L.append(f"\n**핵심1 (기본 이메일 가정에서는 ML 정책 불안정)**: validation에서 양(+)으로 보인 분위만 발송하는 정책은 "
                 f"기본 가정($0.05)의 test 평가에서 ${base_gain:+.0f}({gain_pct:+.0f}%)로 전체발송보다 낮다.")
    L.append(f"**핵심2 (전체발송이 손실로 도는 임계)**: 채널피로비가 **${blanket_breakeven:.2f}/통**을 넘으면 "
             f"전체발송은 순손실. 이메일($0.05)은 안전권이지만, 푸시·SMS처럼 피로비 큰 채널이면 위험.\n")
    L.append("→ 팀장 설득: \"다 보내라\"는 *이메일처럼 싼 채널 + 무한 발송예산* 가정에서는 충분히 옳을 수 있다. "
             "채널피로비가 커질수록 전체발송의 손실 위험은 커지지만, uplift 정책도 validation/test로 검증해야 한다. "
             "이 표는 타겟팅을 자동 정답으로 만들지 않고, 언제 전체발송이 위험해지는지와 모델 정책이 얼마나 불안정한지를 함께 보여준다.\n")

    L.append("## 부록: robustness — raw spend 기준 분위 증분\n")
    L.append(dec[["decile", "n", "treated_n", "control_n", "send_policy",
                  "inc_conv_pc", "inc_conv_se", "inc_spend_pc", "net_pc"]].round(4).to_string(index=False))

    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "incrementality_report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\n[saved] {docs/'incrementality_report.md'}")


if __name__ == "__main__":
    main()
