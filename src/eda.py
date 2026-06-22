"""Step 2 — EDA: 전체 ATE 방향 확인 + H1(sleeping-dog) 세그먼트 탐색.

산출: 콘솔 출력 + docs/eda_findings.md (수치는 모두 데이터에서 직접 계산).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.data import load_config, load_hillstrom, validate

ROOT = Path(__file__).resolve().parents[1]


def ate(df: pd.DataFrame, col: str) -> tuple[float, float, float]:
    t = df.loc[df.treatment == 1, col].mean()
    c = df.loc[df.treatment == 0, col].mean()
    return t, c, t - c


def segment_ate(df: pd.DataFrame, axis: str, outcome: str = "spend") -> pd.DataFrame:
    rows = []
    for key, g in df.groupby(axis):
        t = g.loc[g.treatment == 1, outcome].mean()
        c = g.loc[g.treatment == 0, outcome].mean()
        rows.append({axis: key, "n": len(g), "treated": t, "control": c, "ate": t - c})
    return pd.DataFrame(rows).sort_values("ate")


def main() -> None:
    cfg = load_config()
    df = load_hillstrom(cfg)
    lines: list[str] = []

    def out(s: str = "") -> None:
        print(s)
        lines.append(s)

    out("# EDA Findings — Hillstrom CRM Uplift\n")
    out(f"검증: {validate(df)}\n")

    out("## 1. 전체 ATE (이메일 발송 vs 무발송)\n")
    out("| 결과 | treated | control | ATE | 상대 |")
    out("|---|---|---|---|---|")
    for col in ["visit", "conversion", "spend"]:
        t, c, d = ate(df, col)
        rel = (d / c * 100) if c else 0.0
        unit = "$" if col == "spend" else ""
        out(f"| {col} | {unit}{t:.4f} | {unit}{c:.4f} | {d:+.4f} | {rel:+.1f}% |")
    conv = df[df.conversion == 1]
    out(f"\nAOV(구매자 평균 spend) = ${conv.spend.mean():.2f} · 전체 구매율 = {df.conversion.mean():.4f}\n")

    out("## 2. H1 — 세그먼트별 spend ATE (sleeping-dog 탐색)\n")
    out("ATE<0 이면 '이메일이 오히려 매출을 깎는' sleeping-dog 후보.\n")
    for axis in ["recency", "history_segment", "channel", "newbie", "zip_code", "mens", "womens"]:
        tbl = segment_ate(df, axis, "spend")
        neg = tbl[tbl.ate < 0]
        flag = f"  ⚠️ 음의 ATE 그룹 {len(neg)}개" if len(neg) else ""
        out(f"### {axis}{flag}")
        out(tbl.round(3).to_string(index=False))
        out("")

    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "eda_findings.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[saved] {docs/'eda_findings.md'}")


if __name__ == "__main__":
    main()
