"""Step 3a — uplift 모델 학습 + validation/test 평가(Qini/AUUC).

설계 노트:
- treatment 무작위배정이므로, 피처 X만으로 학습한 모델 점수로 고객을 정렬한 뒤
  같은 점수대의 treated vs control 을 비교하면 증분이 편향 없이 추정된다.
- train으로 모델을 학습하고, validation은 정책 선택, test는 최종 성과 평가에만 쓴다.
- 모델 타깃은 visit(신호 가장 강함). 금액(spend) 환산은 incrementality.py 에서.
- 모델: T-learner(TwoModels). base = GradientBoosting.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder
from sklift.metrics import qini_auc_score, uplift_auc_score
from sklift.models import TwoModels

from src.data import load_config, load_hillstrom

ROOT = Path(__file__).resolve().parents[1]

NUM = ["recency", "history", "mens", "womens", "newbie"]
CAT = ["history_segment", "zip_code", "channel"]


def fit_feature_transformer(df: pd.DataFrame) -> ColumnTransformer:
    """train 데이터로만 범주형 인코더를 학습."""
    ohe = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    ct = ColumnTransformer(
        [("num", "passthrough", NUM), ("cat", ohe, CAT)], remainder="drop"
    )
    ct.fit(df)
    return ct


def transform_features(df: pd.DataFrame, ct: ColumnTransformer) -> pd.DataFrame:
    """학습된 transformer로 모델 입력용 수치 프레임 생성."""
    arr = ct.transform(df)
    names = NUM + list(ct.named_transformers_["cat"].get_feature_names_out(CAT))
    return pd.DataFrame(arr, columns=names, index=df.index)


def split_indices(df: pd.DataFrame, cfg: dict):
    """60/20/20 train/validation/test split. treatment 비율은 각 split에서 유지."""
    split = cfg["split"]
    train_size = split["train_size"]
    validation_size = split["validation_size"]
    test_size = split["test_size"]
    if not np.isclose(train_size + validation_size + test_size, 1.0):
        raise ValueError("train_size + validation_size + test_size must equal 1.0")

    idx_train_val, idx_test = train_test_split(
        df.index,
        test_size=test_size,
        random_state=split["random_state"],
        stratify=df["treatment"],
    )
    val_fraction = validation_size / (train_size + validation_size)
    idx_train, idx_val = train_test_split(
        idx_train_val,
        test_size=val_fraction,
        random_state=split["random_state"],
        stratify=df.loc[idx_train_val, "treatment"],
    )
    return idx_train, idx_val, idx_test


def _metrics(y: np.ndarray, uplift_score: np.ndarray, t: np.ndarray) -> dict:
    return {
        "qini_auc": float(qini_auc_score(y, uplift_score, t)),
        "auuc": float(uplift_auc_score(y, uplift_score, t)),
        "n": int(len(y)),
    }


def fit_predict(df: pd.DataFrame, cfg: dict):
    """train으로 학습 후 validation/test에 예측 uplift 점수를 붙여 반환."""
    target = cfg["data"]["uplift_target"]
    idx_train, idx_val, idx_test = split_indices(df, cfg)
    transformer = fit_feature_transformer(df.loc[idx_train])

    Xtr = transform_features(df.loc[idx_train], transformer)
    Xval = transform_features(df.loc[idx_val], transformer)
    Xte = transform_features(df.loc[idx_test], transformer)
    ytr = df.loc[idx_train, target].values
    ttr = df.loc[idx_train, "treatment"].values

    base = dict(n_estimators=100, max_depth=3, learning_rate=0.1,
                random_state=cfg["split"]["random_state"])
    model = TwoModels(
        estimator_trmnt=GradientBoostingClassifier(**base),
        estimator_ctrl=GradientBoostingClassifier(**base),
        method="vanilla",
    )
    model.fit(Xtr, ytr, ttr)

    validation = df.loc[idx_val].copy()
    test = df.loc[idx_test].copy()
    validation["uplift_score"] = model.predict(Xval)
    test["uplift_score"] = model.predict(Xte)

    metrics = {
        "target": target,
        "n_train": int(len(idx_train)),
        "validation": _metrics(
            validation[target].values,
            validation["uplift_score"].values,
            validation["treatment"].values,
        ),
        "test": _metrics(
            test[target].values,
            test["uplift_score"].values,
            test["treatment"].values,
        ),
    }
    return validation, test, metrics


def main() -> None:
    cfg = load_config()
    df = load_hillstrom(cfg)
    validation, test, metrics = fit_predict(df, cfg)
    print("모델 평가:", metrics)
    out_val = ROOT / "data" / "validation_with_uplift.parquet"
    out_test = ROOT / "data" / "test_with_uplift.parquet"
    out_val.parent.mkdir(parents=True, exist_ok=True)
    validation.to_parquet(out_val)
    test.to_parquet(out_test)
    print(f"[saved] {out_val}  (rows={len(validation)})")
    print(f"[saved] {out_test}  (rows={len(test)})")


if __name__ == "__main__":
    main()
