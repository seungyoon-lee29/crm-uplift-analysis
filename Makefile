.PHONY: setup eda model incrementality figures all clean

PY = .venv/bin/python
PIP = .venv/bin/pip

setup:            ## 전용 venv 생성 + 의존성 설치 (numpy<2 핀이 핵심)
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.txt
	@echo "✅ setup 완료 — 'make all' 로 전체 파이프라인 실행"

eda:              ## Step2: 전체 ATE + H1 세그먼트 탐색 → docs/eda_findings.md
	$(PY) -m src.eda

model:            ## Step3a: uplift 모델 학습 + validation/test Qini/AUUC → data/*_with_uplift.parquet
	$(PY) -m src.uplift

incrementality:   ## Step3b: 전체발송 vs 타겟발송 증분 이익 → docs/incrementality_report.md
	$(PY) -m src.incrementality

figures:          ## 의사결정 차트 → docs/figures/*.png
	$(PY) -m src.figures

all: eda model incrementality figures  ## 전체 파이프라인 (재현 가능)
	@echo "✅ 전체 파이프라인 완료"

clean:
	rm -rf data/validation_with_uplift.parquet data/test_with_uplift.parquet docs/figures/*.png
