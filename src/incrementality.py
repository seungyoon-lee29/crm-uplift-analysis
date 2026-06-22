"""Step 3b — 증분 이익: '전체발송 vs uplift 타겟발송' 의사결정.

무작위배정 덕분에, uplift 점수로 정렬한 그룹 안에서 treated-control 결과차가
그 그룹에 발송했을 때의 증분(반사실)이 된다.

의사결정 단위 = decile 한계분석: 고객을 uplift 점수 10분위로 나누고,
각 분위의 '한계 순이익/명'이 양(+)인 분위에만 발송하는 것이 최적 정책.

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


def _inc(g: pd.DataFrame, outcome: str) -> float:
    t = g.loc[g.treatment == 1, outcome]
    c = g.loc[g.treatment == 0, outcome]
    if len(t) == 0 or len(c) == 0:
        return np.nan
    return t.mean() - c.mean()


def decile_table(test: pd.DataFrame, cfg: dict, aov: float, n_bins: int = 10) -> pd.DataFrame:
    """uplift 점수 분위별 한계 증분·순이익."""
    b = cfg["business"]
    fatigue = b["optout_rate_per_send"] * b["customer_ltv"]
    ranked = test.sort_values("uplift_score", ascending=False).reset_index(drop=True)
    ranked["decile"] = (np.arange(len(ranked)) // (len(ranked) / n_bins)).astype(int) + 1
    rows = []
    for d, g in ranked.groupby("decile"):
        inc_conv = _inc(g, "conversion")
        inc_spend = _inc(g, "spend")
        gross = inc_conv * aov * b["margin_rate"]
        net_pc = gross - b["send_cost"] - fatigue
        rows.append({"decile": int(d), "n": len(g), "inc_conv_pc": inc_conv,
                     "inc_spend_pc": inc_spend, "gross_pc": gross,
                     "net_pc": net_pc, "net_total": net_pc * len(g)})
    return pd.DataFrame(rows)


def sensitivity(test: pd.DataFrame, cfg: dict, aov: float,
                fatigue_grid: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """수신거부 비용(채널 피로비)을 바꿔가며 최적 정책과 손익분기 탐색."""
    b = cfg["business"]
    ranked = test.sort_values("uplift_score", ascending=False).reset_index(drop=True)
    ranked["decile"] = (np.arange(len(ranked)) // (len(ranked) / n_bins)).astype(int) + 1
    dec = ranked.groupby("decile").apply(
        lambda g: pd.Series({"n": len(g), "inc_conv": _inc(g, "conversion")}))
    rows = []
    for fat in fatigue_grid:
        net_pc = dec["inc_conv"] * aov * b["margin_rate"] - b["send_cost"] - fat
        send = net_pc > 0                       # 한계 순이익>0 분위만 발송
        targeted_total = float((net_pc[send] * dec["n"][send]).sum())
        blanket_total = float((net_pc * dec["n"]).sum())
        rows.append({"fatigue_cost": round(float(fat), 3),
                     "deciles_sent": int(send.sum()),
                     "blanket_net": blanket_total,
                     "targeted_net": targeted_total,
                     "targeting_gain": targeted_total - blanket_total})
    return pd.DataFrame(rows)


def main() -> None:
    cfg = load_config()
    b = cfg["business"]
    test = pd.read_parquet(ROOT / "data" / "test_with_uplift.parquet")
    aov = float(test.loc[test.conversion == 1, "spend"].mean())

    dec = decile_table(test, cfg, aov)
    blanket_net = float(dec["net_total"].sum())
    pos = dec[dec["net_pc"] > 0]
    targeted_net = float(pos["net_total"].sum())

    base_fatigue = b["optout_rate_per_send"] * b["customer_ltv"]
    grid = np.round(np.arange(0.0, 1.0001, 0.05), 3)
    sens = sensitivity(test, cfg, aov, grid)
    base_gain = float(targeted_net - blanket_net)
    # 전체발송이 순손실로 돌아서는 채널피로비 (blanket_net = N*(ATE_conv*AOV*margin - send) - N*fatigue = 0)
    ate_conv = float(_inc(test, "conversion"))
    blanket_breakeven = ate_conv * aov * b["margin_rate"] - b["send_cost"]

    L = ["# 증분 이익 리포트 — 전체발송 vs uplift 타겟발송\n"]
    L.append(f"AOV(구매자 평균 spend) = ${aov:.2f} · 가정: 마진 {b['margin_rate']}, "
             f"발송비 ${b['send_cost']}, 채널피로비(수신거부×LTV) = ${base_fatigue:.3f}/통\n")

    L.append("## 1. 한계 순이익 by uplift 분위 (의사결정 단위)\n")
    L.append("| 분위 | n | 증분구매/명 | 증분총이익/명 | 한계순이익/명 |")
    L.append("|---|---|---|---|---|")
    for _, r in dec.iterrows():
        L.append(f"| {int(r['decile'])} | {int(r['n'])} | {r['inc_conv_pc']:+.4f} | "
                 f"${r['gross_pc']:.3f} | ${r['net_pc']:+.3f} |")

    L.append(f"\n- 전체 평균은 증분구매 +{ate_conv:.4f}/명 = 이메일은 평균적으로 먹힌다(\"다 보내\"가 틀린 건 아님).")
    L.append(f"- 그러나 분위별 한계순이익이 양(+)인 분위 = {len(pos)}/10 "
             f"→ 음(-)인 분위를 빼면 순이익이 ${base_gain:.0f} 늘어난다(타겟발송 ${targeted_net:.0f} vs 전체발송 ${blanket_net:.0f}).")
    L.append("- ⚠️ 단 분위별 증분구매는 노이즈가 크다(분위당 표준오차 ≈ ±0.004 vs 추정치 ±0.002). "
             "즉 '특정 분위 = 확정 sleeping-dog'은 과대주장 — 의사결정 프레임은 타당하나 점추정은 홀드아웃 재검증이 필요.\n")

    L.append("## 2. 채널 피로비 민감도 (← 진짜 '팀장 설득' 포인트)\n")
    L.append("수신거부 1건의 비용(채널피로비)을 얼마로 보느냐에 따라 답이 갈린다.\n")
    L.append("| 채널피로비/통 | 발송 분위수 | 전체발송 순이익 | 타겟발송 순이익 | 타겟팅 이득 |")
    L.append("|---|---|---|---|---|")
    for _, r in sens[sens.fatigue_cost.isin([0.0,0.05,0.1,0.2,0.3,0.5,0.7,1.0])].iterrows():
        L.append(f"| ${r['fatigue_cost']:.2f} | {int(r['deciles_sent'])} | "
                 f"${r['blanket_net']:.0f} | ${r['targeted_net']:.0f} | ${r['targeting_gain']:.0f} |")
    L.append(f"\n**핵심1 (타겟팅은 약하게 항상 우위)**: 타겟발송은 음의 분위를 제외할 수 있어 "
             f"정의상 전체발송 ≤ 타겟발송. 기본 가정($0.05)에서도 +${base_gain:.0f}({base_gain/blanket_net*100:+.0f}%).")
    L.append(f"**핵심2 (전체발송이 손실로 도는 임계)**: 채널피로비가 **${blanket_breakeven:.2f}/통**을 넘으면 "
             f"전체발송은 순손실. 이메일($0.05)은 안전권이지만, 푸시·SMS처럼 피로비 큰 채널이면 위험.\n")
    L.append("→ 팀장 설득: \"다 보내라\"는 *이메일처럼 싼 채널 + 무한 발송예산* 가정에서만 옳다. "
             "채널피로비가 크거나(푸시/SMS) 발송 capacity가 유한하면, uplift 정렬이 발송당 이익을 높이고 "
             "음의 증분 꼬리를 잘라낸다 — 그 경제성을 이 표가 수치로 보여준다.\n")

    L.append("## 부록: robustness — raw spend 기준 분위 증분\n")
    L.append(dec[["decile", "n", "inc_conv_pc", "inc_spend_pc", "net_pc"]].round(4).to_string(index=False))

    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "incrementality_report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\n[saved] {docs/'incrementality_report.md'}")


if __name__ == "__main__":
    main()
