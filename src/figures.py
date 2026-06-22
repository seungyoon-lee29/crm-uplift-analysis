"""의사결정 차트 생성 → docs/figures/*.png (수치는 모두 마트에서 직접 로드)."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 한글 라벨 렌더링 (macOS 기본 폰트)
for _f in ("AppleGothic", "Apple SD Gothic Neo", "NanumGothic", "Malgun Gothic"):
    try:
        plt.rcParams["font.family"] = _f
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False
import numpy as np
import pandas as pd
from sklift.metrics import perfect_qini_curve, qini_curve

from src.data import load_config
from src.incrementality import decile_table, select_topk, sensitivity, topk_curve

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs" / "figures"


def fig_qini(test: pd.DataFrame) -> None:
    y, uplift, t = test["visit"].values, test["uplift_score"].values, test["treatment"].values
    x_a, y_a = qini_curve(y, uplift, t)
    x_p, y_p = perfect_qini_curve(y, t)
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.plot(x_a, y_a, label="uplift 모델", lw=2, color="#4f46e5")
    ax.plot(x_p, y_p, label="완벽 모델(상한)", lw=1, ls="--", color="#94a3b8")
    ax.plot([0, x_a[-1]], [0, y_a[-1]], label="랜덤(무작위 발송)", lw=1, ls=":", color="#334155")
    ax.set_xlabel("발송 고객 수 (uplift 내림차순)")
    ax.set_ylabel("누적 증분 visit")
    ax.set_title("Qini 곡선 — 모델이 랜덤보다 위 = 증분 정렬력 있음")
    ax.legend()
    fig.tight_layout(); fig.savefig(FIG / "qini_curve.png", dpi=120); plt.close(fig)


def fig_decile(dec: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    colors = ["#4f46e5" if v else "#dc2626" for v in dec["send_policy"]]
    ax.bar(dec["decile"], dec["net_pc"], color=colors)
    ax.axhline(0, color="#334155", lw=0.8)
    ax.set_xlabel("uplift 분위 (1=최상위)")
    ax.set_ylabel("한계 순이익 / 명 ($)")
    ax.set_title("비연속 분위 cherry-pick의 불안정성 — 빨강(제외)이 test 최고 분위")
    fig.tight_layout(); fig.savefig(FIG / "decile_net_profit.png", dpi=120); plt.close(fig)


def fig_topk(validation: pd.DataFrame, test: pd.DataFrame, cfg: dict,
             aov: float, base_fatigue: float) -> None:
    vg = topk_curve(validation, cfg, aov, base_fatigue)
    tg = topk_curve(test, cfg, aov, base_fatigue)
    k_star = select_topk(validation, cfg, aov, base_fatigue)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(vg["k"] * 100, vg["cum_net"], label="validation (정책 선택)", color="#94a3b8", lw=2, marker="o", ms=3)
    ax.plot(tg["k"] * 100, tg["cum_net"], label="test (성과 평가)", color="#4f46e5", lw=2, marker="o", ms=3)
    ax.axvline(k_star * 100, color="#dc2626", ls="--", lw=1, label=f"validation k* = {k_star*100:.0f}%")
    ax.axhline(0, color="#334155", lw=0.8)
    ax.set_xlabel("발송 비율 k (uplift 상위 %)")
    ax.set_ylabel("누적 순이익 ($)")
    ax.set_title("top-k 정책 — validation에서 고른 k*의 test 누적 순이익")
    ax.legend()
    fig.tight_layout(); fig.savefig(FIG / "topk_policy.png", dpi=120); plt.close(fig)


def fig_sensitivity(sens: pd.DataFrame, base_fatigue: float) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(sens["fatigue_cost"], sens["blanket_net"], label="전체발송", lw=2, color="#dc2626", marker="o", ms=3)
    ax.plot(sens["fatigue_cost"], sens["targeted_net"], label="타겟발송", lw=2, color="#4f46e5", marker="o", ms=3)
    ax.axhline(0, color="#334155", lw=0.8)
    ax.axvline(base_fatigue, color="#94a3b8", ls="--", lw=1, label=f"기본 가정 (${base_fatigue:.2f})")
    ax.set_xlabel("채널 피로비 / 통 ($) = 수신거부율 × LTV")
    ax.set_ylabel("총 순이익 ($)")
    ax.set_title("채널 피로비가 오를수록 타겟발송의 우위 확대")
    ax.legend()
    fig.tight_layout(); fig.savefig(FIG / "fatigue_sensitivity.png", dpi=120); plt.close(fig)


def main() -> None:
    cfg = load_config()
    b = cfg["business"]
    FIG.mkdir(parents=True, exist_ok=True)
    validation = pd.read_parquet(ROOT / "data" / "validation_with_uplift.parquet")
    test = pd.read_parquet(ROOT / "data" / "test_with_uplift.parquet")
    aov = float(validation.loc[validation.conversion == 1, "spend"].mean())
    validation_dec = decile_table(validation, cfg, aov)
    selected_deciles = set(validation_dec.loc[validation_dec["net_pc"] > 0, "decile"].astype(int))
    dec = decile_table(test, cfg, aov, selected_deciles=selected_deciles)
    sens = sensitivity(validation, test, cfg, aov, np.round(np.arange(0.0, 1.0001, 0.05), 3))
    base_fatigue = b["optout_rate_per_send"] * b["customer_ltv"]

    fig_qini(test)
    fig_decile(dec)
    fig_topk(validation, test, cfg, aov, base_fatigue)
    fig_sensitivity(sens, base_fatigue)
    print(f"[saved] 4 figures → {FIG}")


if __name__ == "__main__":
    main()
