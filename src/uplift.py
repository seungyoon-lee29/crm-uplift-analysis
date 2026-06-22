"""Step 3a — uplift 모델 학습 + 평가(Qini/AUUC).

설계 노트:
- treatment 무작위배정이므로, 피처 X만으로 학습한 모델 점수로 고객을 정렬한 뒤
  같은 점수대의 treated vs control 을 비교하면 증분이 편향 없이 추정된다.
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


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    """범주형 원-핫 → 모델 입력용 수치 프레임."""
    ohe = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    ct = ColumnTransformer(
        [("num", "passthrough", NUM), ("cat", ohe, CAT)], remainder="drop"
    )
    arr = ct.fit_transform(df)
    names = NUM + list(ct.named_transformers_["cat"].get_feature_names_out(CAT))
    return pd.DataFrame(arr, columns=names, index=df.index)


def fit_predict(df: pd.DataFrame, cfg: dict):
    """학습/평가 분할 후 테스트셋에 예측 uplift 점수를 붙여 반환."""
    target = cfg["data"]["uplift_target"]
    X = prepare_features(df)
    y = df[target].values
    t = df["treatment"].values

    Xtr, Xte, ytr, yte, ttr, tte, idx_tr, idx_te = train_test_split(
        X, y, t, df.index,
        test_size=cfg["split"]["test_size"],
        random_state=cfg["split"]["random_state"],
        stratify=t,
    )

    base = dict(n_estimators=100, max_depth=3, learning_rate=0.1,
                random_state=cfg["split"]["random_state"])
    model = TwoModels(
        estimator_trmnt=GradientBoostingClassifier(**base),
        estimator_ctrl=GradientBoostingClassifier(**base),
        method="vanilla",
    )
    model.fit(Xtr, ytr, ttr)
    uplift_score = model.predict(Xte)

    qini = qini_auc_score(yte, uplift_score, tte)
    auuc = uplift_auc_score(yte, uplift_score, tte)

    test = df.loc[idx_te].copy()
    test["uplift_score"] = uplift_score
    return test, {"qini_auc": float(qini), "auuc": float(auuc),
                  "n_test": int(len(test)), "target": target}


def main() -> None:
    cfg = load_config()
    df = load_hillstrom(cfg)
    test, metrics = fit_predict(df, cfg)
    print("모델 평가:", metrics)
    out = ROOT / "data" / "test_with_uplift.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    test.to_parquet(out)
    print(f"[saved] {out}  (rows={len(test)})")


if __name__ == "__main__":
    main()
