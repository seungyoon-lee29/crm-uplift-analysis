# EDA Findings — Hillstrom CRM Uplift

검증: {'n_rows': 64000, 'n_missing': 0, 'treatment_balance': {1: 0.667, 0: 0.333}, 'conversion_without_visit': 0, 'spend_without_conversion': 0}

## 1. 전체 ATE (이메일 발송 vs 무발송)

| 결과 | treated | control | ATE | 상대 |
|---|---|---|---|---|
| visit | 0.1670 | 0.1062 | +0.0609 | +57.3% |
| conversion | 0.0107 | 0.0057 | +0.0050 | +86.5% |
| spend | $1.2496 | $0.6528 | +0.5968 | +91.4% |

AOV(구매자 평균 spend) = $116.36 · 전체 구매율 = 0.0090

## 2. H1 — 세그먼트별 spend ATE (sleeping-dog 탐색)

ATE<0 이면 '이메일이 오히려 매출을 깎는' sleeping-dog 후보.

### recency  ⚠️ 음의 ATE 그룹 1개
 recency    n  treated  control    ate
       8 3495    1.112    1.299 -0.187
      11 3504    0.499    0.300  0.199
       6 4605    0.973    0.753  0.220
       2 7537    1.604    1.101  0.502
       5 4510    0.903    0.383  0.519
       7 4078    1.002    0.382  0.620
       3 5904    1.520    0.888  0.631
       9 6441    1.001    0.309  0.693
      10 7565    1.100    0.377  0.723
      12 2332    1.304    0.557  0.747
       1 8952    1.766    0.845  0.921
       4 5077    1.383    0.431  0.952

### history_segment
 history_segment     n  treated  control   ate
  3) $200 - $350 12289    1.036    0.933 0.103
  2) $100 - $200 14254    1.004    0.423 0.581
    1) $0 - $100 22970    1.099    0.517 0.582
  4) $350 - $500  6409    1.727    1.010 0.716
6) $750 - $1,000  1859    1.459    0.350 1.109
  5) $500 - $750  4911    1.735    0.539 1.196
     7) $1,000 +  1308    4.060    2.170 1.891

### channel
     channel     n  treated  control   ate
       Phone 28021    1.041    0.644 0.396
         Web 28217    1.306    0.671 0.635
Multichannel  7762    1.799    0.616 1.183

### newbie
 newbie     n  treated  control   ate
      0 31856    1.281    0.935 0.346
      1 32144    1.218    0.372 0.846

### zip_code
 zip_code     n  treated  control   ate
Surburban 28776    1.158    0.669 0.488
    Rural  9563    1.403    0.767 0.636
    Urban 25661    1.295    0.592 0.703

### mens
 mens     n  treated  control   ate
    1 35266    1.360    0.784 0.577
    0 28734    1.114    0.491 0.624

### womens
 womens     n  treated  control   ate
      0 28818    1.175    0.695 0.480
      1 35182    1.310    0.618 0.693
