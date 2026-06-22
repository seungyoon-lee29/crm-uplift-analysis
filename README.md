# CRM Uplift Analysis

이커머스/핀테크 고객 세그먼트별 업리프트 모델링 프로젝트.

## 개요

처치 효과(Treatment Effect) 추정을 통해 CRM 캠페인의 실질적 효과를 측정하고, 처치 반응성이 높은 고객군(persuadables)을 식별하는 업리프트 모델을 구축합니다.

## 분석 목표

- 캠페인 대상자 전체에 대한 ATE(Average Treatment Effect) 추정
- 고객 세그먼트별 CATE(Conditional Average Treatment Effect) 분해
- Uplift 모델 기반 타겟팅 우선순위 산출 (Qini / AUUC 평가)
- 비용 대비 효과(ROI) 시뮬레이션

## 프로젝트 구조

```
crm-uplift-analysis/
├── README.md
├── .gitignore
├── notebooks/          # EDA, 모델링, 평가
├── src/
│   ├── features/       # 피처 엔지니어링
│   ├── models/         # 업리프트 모델 (S/T/X-learner, CausalML)
│   └── evaluation/     # Qini curve, AUUC
├── data/               # (gitignore — 로컬 전용)
└── reports/            # 최종 리포트
```

## 주요 방법론

| 방법 | 설명 |
|------|------|
| S-Learner | 단일 모델로 처치 변수를 피처로 포함 |
| T-Learner | 처치/대조 집단 별 개별 모델 |
| X-Learner | 소규모 처치 집단에 강건한 메타러너 |
| DR-Learner | 이중 견고 추정 (doubly robust) |

## 데이터

- 내부 CRM 캠페인 로그 (고객 ID, 처치 여부, 전환 결과)
- 고객 행동 피처 (RFM, 채널 활동도, 세그먼트 등)
- 데이터 파일은 `.gitignore`에 의해 추적 제외

## 평가 지표

- **AUUC** (Area Under the Uplift Curve)
- **Qini coefficient**
- **누적 업리프트 곡선** @ top 10/20/30%
