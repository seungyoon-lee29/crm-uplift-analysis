"""Hillstrom 데이터 로드·이진화·검증.

Hillstrom MineThatData Email Analytics Challenge:
  64,000 고객을 3군(Mens E-Mail / Womens E-Mail / No E-Mail)으로 무작위배정한
  실제 이메일 캠페인 A/B 데이터. 결과: visit, conversion, spend (발송 후 2주).
  무작위배정이라 control(No E-Mail)이 깨끗한 반사실(counterfactual)을 제공 → 증분 측정 가능.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import yaml
from sklift.datasets import fetch_hillstrom

ROOT = Path(__file__).resolve().parents[1]


def load_config(path: str | None = None) -> dict:
    path = path or (ROOT / "config" / "config.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_hillstrom(cfg: dict, target: str | None = None) -> pd.DataFrame:
    """원천 + 결과 3종 + 이진 treatment 를 한 프레임으로 합쳐 반환.

    반환 컬럼: 8개 피처 + visit, conversion, spend, segment(원본), treatment(0/1)
    treatment=1 = 이메일 발송(Mens 또는 Womens), 0 = No E-Mail.
    """
    target = target or cfg["data"]["uplift_target"]
    bunch = fetch_hillstrom(target_col=target)
    X = bunch["data"].copy()
    seg = bunch["treatment"].copy()  # 'Mens E-Mail' / 'Womens E-Mail' / 'No E-Mail'

    # 결과 3종 모두 확보 (target_col 마다 따로 받아 합침)
    for col in ("visit", "conversion", "spend"):
        if col == target:
            X[col] = bunch["target"].values
        else:
            X[col] = fetch_hillstrom(target_col=col)["target"].values

    X["segment"] = seg.values
    pos = set(cfg["data"]["treatment_positive"])
    X["treatment"] = X["segment"].isin(pos).astype(int)
    return X


def validate(df: pd.DataFrame) -> dict:
    """무작위배정·결측·퍼널 단조성 등 기본 sanity 체크."""
    checks = {}
    checks["n_rows"] = len(df)
    checks["n_missing"] = int(df.isna().sum().sum())
    checks["treatment_balance"] = df["treatment"].value_counts(normalize=True).round(3).to_dict()
    # 퍼널 단조성: conversion 한 사람은 visit 했어야 한다
    bad = df[(df["conversion"] == 1) & (df["visit"] == 0)]
    checks["conversion_without_visit"] = int(len(bad))
    # spend>0 이면 conversion=1 이어야
    bad2 = df[(df["spend"] > 0) & (df["conversion"] == 0)]
    checks["spend_without_conversion"] = int(len(bad2))
    return checks


if __name__ == "__main__":
    cfg = load_config()
    df = load_hillstrom(cfg)
    print(df.head())
    print("\n검증:", validate(df))
