# Phase: 정밀도 평가 메트릭 일원화 (Screener ↔ Predict)

## Context

이전 phase까지 신호 파라미터(`AI_FILTER`, `BB_SQUEEZE_RATIO`, `TRAILING_ATR_MULT` 등)를 백테스트/Optuna 기반으로 최적화해 왔으나, 사용자가 방향을 전환:

> "backtest나 optuna의 중요성은 상대적으로 낮아. 그것보다는 predict와 screener의 품질에 직접적인 영향을 미치는, 기대수익률·보유기간·BB-squeeze·정밀도 등을 최적화하고 개선하는 작업을 더 해야 한다."

이 작업의 출발점인 **test_predict / test_sensitivity / predict / screener의 정밀도 평가 기준이 통일되어 있지 않다**는 문제를 먼저 해결해야 함.

## 발견된 불일치

| 측면 | `predict.Analyze_Full` | `screener._quick_analyze` |
|---|---|---|
| 분할 | TimeSeriesSplit 5-Fold | 70/30 단일 holdout |
| Laplace | `_laplace_precision()` 헬퍼 | 인라인 `(tp+1)/(tp+fp+2)` |
| 반환 키 | `Hist_Precision` | **같은 이름** `Hist_Precision` |

같은 종목에 대해 두 함수가 다른 분포의 정밀도를 같은 이름으로 반환 → `SCREENER_MIN_PRECISION=0.50`이 어느 메트릭 기준인지 코드만 봐선 불명확.

## 변경 내용

### predict.py — 공용 헬퍼 추출 및 키 명명

- 신규 함수 `cv_precision(df, ...)` — TimeSeriesSplit n-Fold 평균 정밀도 + 누적 신호 수
- 신규 함수 `holdout_precision(df, ..., split_ratio=0.7)` — 단일 holdout 정밀도 + 신호 수
- `Analyze_Full` 내부 5-Fold 인라인 루프 → `cv_precision(df)` 한 줄로 교체
- 반환 dict에 `CV_Precision`(정식), `Eval_Method='cv_5fold'` 추가; `Hist_Precision`은 호환 별칭으로 유지
- Deep dashboard 라벨: "모델정밀도" → "CV정밀도(5-Fold)"

### screener.py — holdout_precision import 후 호출

- `from predict import Create_Windowed_Data, holdout_precision`
- `_quick_analyze`의 인라인 정밀도 블록(35줄) → `holdout_precision(df)` 한 줄로 교체
- 반환 dict에 `Light_Precision`(정식), `Eval_Method='holdout_70_30'`, `Light_Signals` 추가; `Hist_Precision`은 호환 별칭으로 유지
- Light dashboard 라벨: "정밀도" → "Light정밀도(70/30)"

### test_predict.py — CV vs Holdout 차이 보고

- `test_ai_not_random(stock_data)`가 `Analyze_Full` 호출 후 같은 데이터로 `holdout_precision`도 함께 측정
- 두 정밀도 차이(Δ)가 0.10 이상이면 "분기 의존" 경고 출력
- 신호가 평가 분기에 얼마나 민감한지 한눈에 확인 가능

### test_sensitivity.py — 평가 방식 헤더 명시

- 실행 시작 시 헤더에 사용 평가 체계 명시(Walk-Forward AI 신호 + Backtest_Strategy)
- 분류 메트릭 비교는 test_predict.py로 분기 안내

### config.py — 임계값 의미 명확화

```python
# v10.2: 평가 메트릭 일원화 — 이 임계값은 Light(70/30 holdout) 기준.
#        predict.Analyze_Full의 CV(5-Fold) 정밀도와는 다른 분포 — 직접 비교 금지.
SCREENER_MIN_PRECISION = 0.50    # Light(holdout 70/30) 정밀도 하한
```

## 호환성

`trade_journal.py`가 `Hist_Precision`을 **Excel 컬럼명**으로 사용 중 (기존 매매 기록 파일 호환). predict/screener 모두 `Hist_Precision` 별칭을 유지하므로 **기존 엑셀/이력은 그대로 동작**.

새 코드를 작성할 때는 `CV_Precision`, `Light_Precision`을 사용해 의미를 명확히 하는 것이 권장.

## 검증 (2026-05-14)

| 항목 | 결과 |
|---|---|
| 전체 모듈 import 정상 | ✅ predict/screener/test_predict/test_sensitivity/trade_journal/alert/backtest/optimize |
| `predict.cv_precision` / `predict.holdout_precision` 노출 | ✅ |
| `Analyze_Full('SOFI')` 반환 → `CV_Precision=0.298, Hist_Precision=0.298(별칭), Eval_Method='cv_5fold'` | ✅ |
| 같은 데이터 `holdout_precision('SOFI')` = 0.309 (Δ +0.011) | ✅ 두 메트릭 독립 측정 정상 |
| `screener._quick_analyze('IONQ')` 반환 → `Light_Precision=0.514, Hist_Precision=0.514(별칭), Eval_Method='holdout_70_30', Light_Signals=208` | ✅ |
| `SCREENER_MIN_PRECISION=0.50` 게이트가 PLTR/RKLB/SOFI 필터링 (정밀도 0.5 미만) | ✅ 게이트 동작 |

### 부수 발견 — 다음 phase에서 다룰 주제

v10.1 파라미터(`AI_TARGET_PCT=10%`, `AI_FORECAST_PERIOD=7일`, `AI_FILTER=0.50`)에서 SOFI/PLTR/RKLB의 holdout 정밀도가 0.50 미만. AI 신호 자체의 품질이 낮음 → "보유기간 × 목표수익률" 그리드 실험으로 신호 품질 개선이 다음 작업의 핵심.

## 비범위 (이번 phase에서 안 함)

- `AI_TARGET_PCT`, `AI_FORECAST_PERIOD`, `AI_FILTER` 최적화 — 메트릭 일원화 후 다음 phase

## 다음 phase 후보

1. **AI_FORECAST_PERIOD × AI_TARGET_PCT 그리드 실험** — (5/7/10/14일) × (5/10/15%) → CV 정밀도/양성비/신호수 표
2. **AI_FILTER vs Light_Precision/CV_Precision 곡선 비교** — 운용용 임계값 vs 검증용 임계값 분리 검토
3. **BB_SQUEEZE_RATIO 별 신호 발생률 vs 후속 수익률 분포** — 신호 빈도와 질의 tradeoff
