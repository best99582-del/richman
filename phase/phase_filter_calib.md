# Phase: AI_FILTER 재캘리브레이션 + AI_Prob 디폴트 버그 수정

## Context

이전 phase(`phase_signal_grid.md`)에서 (FP=10일, TP=7%)가 추천됐고, 이 위에서 AI_FILTER도 재캘리브레이션하기로 함.

진행 중 **두 평가 도구가 정반대 결과를 줘 코드 합리성 자체를 의심하게 됨**:
- test_filter_calib (분류 정밀도): 낮은 AI_FILTER(0.45~0.55) 추천
- test_sensitivity (매매 백테스트): 높은 AI_FILTER(0.60~0.65) 추천

코드 검수 끝에 진짜 원인 발견.

## 🔴 발견된 버그: `Add_AI_Signals` 디폴트 0.5

[predict.py:408-409](../predict.py) (수정 전):
```python
df['AI_Prob'] = 0.5
df['Model_Precision'] = 0.5
```

학습 전 구간(첫 500일, train_window)이 `AI_Prob=0.5`로 채워짐. 그런데 [backtest.py:52](../backtest.py#L52)의 게이트:
```python
ai_pass = ai_prob >= params['ai_filter']
```

**AI_FILTER=0.50일 때 `0.5 >= 0.50` = True** → 학습 안 된 디폴트 구간이 통째로 매수 후보로 들어감.
**AI_FILTER=0.52일 때 `0.5 >= 0.52` = False** → 차단.

이게 두 도구의 모순을 만든 원인:
- test_filter_calib은 5-Fold CV로 매번 모델 새로 학습 → 디폴트 0.5 구간 없음
- test_sensitivity는 Add_AI_Signals 결과를 사용 → 0.50 vs 0.52 경계에서 학습 안 된 노이즈 구간이 통째로 들어가/빠지는 비대칭 발생

### 버그 수정 효과 (검증)

(FP=7, TP=10%, AI_FILTER=0.50, 동일 데이터):
| | 매매수 | 승률 | 평균수익 |
|---|---|---|---|
| 수정 전 | 162 | **40.7%** ❌ | +8.99% |
| 수정 후 | **78** | **51.3%** ✅ | **+18.15%** |

매매수 절반(162→78), 승률 +10.6%p — 학습 안 된 구간 노이즈가 제거됨.

## 수정 내용

### predict.py — `Add_AI_Signals` 디폴트 변경

```python
def Add_AI_Signals(df, train_window=500):
    """학습 전 구간(첫 train_window일)은 AI_Prob=0.0으로 — 어떤 AI_FILTER에서도
    매수 통과되지 않도록. (과거 0.5 디폴트의 0.50 경계 버그 수정.)"""
    df['AI_Prob'] = 0.0
    df['Model_Precision'] = 0.0
```

## AI_FILTER 재교차 (버그 수정 후, FP=10, TP=7%)

| AI_FILTER | 분류 정밀도 | 매매수 | 승률 | 평균수익 | 판정 |
|---|---|---|---|---|---|
| 0.50 | 0.548 / S481 | 86 | 52.3% | +18.47% | ✅양호 |
| 0.52 | 0.537 / S391 | 80 | 53.8% | +20.86% | ✅양호 |
| **0.55** | **0.527 / S238** | **63** | **49.2%** | **+19.56%** | ⚠️보통 ◀ |
| 0.58 | 0.499 / S114 | 39 | 51.3% | +15.89% | ✅양호 |
| 0.60 | 0.497 / S81 | 26 | 61.5% | +33.49% | ✅양호 |
| 0.63 | 0.495 / S32 | 13 | 61.5% | +31.41% | ✅양호 |

두 도구가 같은 방향을 가리킴 — 모순 해소.

## 결정 (2026-05-14): **AI_FILTER = 0.55**

근거:
1. **system_master_plan.md 헌법 명시값 회복** — 이전 v10.1에서 0.50으로 내렸던 것을 헌법대로 복원
2. **단기 스윙 정체성 유지** — 종목당 연 2~3회 매매 (0.60은 연 1회로 너무 보수적)
3. **과조정 회피** — FP/TP가 이미 보수 방향(7일/10% → 10일/7%)으로 움직였으므로 AI_FILTER까지 크게 올리면 시스템 성격이 너무 변함
4. **백테스트 양호** — 평균수익 +19.56%, 승률 49.2%, 매매 63회 (5종목 합산 5년)

## config.py 일괄 반영

| 파라미터 | 이전 | 변경 후 | 근거 |
|---|---|---|---|
| AI_FORECAST_PERIOD | 7 | **10** | phase_signal_grid |
| AI_TARGET_PCT | 10 | **7** | phase_signal_grid |
| AI_FILTER | 0.50 | **0.55** | 이 phase (헌법 회복) |
| `Add_AI_Signals` 디폴트 | 0.5 | **0.0** | 이 phase (버그 수정) |

## 검증 결과 (최종)

- (FP=10, TP=7%, AI_FILTER=0.55) 적용 상태에서 test_sensitivity 재실행 → ◀현재 마커가 0.55 줄에 정확히 표시, 매매 63회 / 승률 49.2% / 평균 +19.56% ✅양호 확인

## 산출물

- [test_filter_calib.py](../test_filter_calib.py) — 신규 (분류 정밀도 기반 AI_FILTER 스윕)
- [phase/_run_sensitivity_filter.py](../phase/_run_sensitivity_filter.py) — test_sensitivity의 test_ai_filter만 단독 실행
- [results/filter_calib_results.txt](../results/filter_calib_results.txt) / .json
- [predict.py:405-413](../predict.py) — Add_AI_Signals 디폴트 0.0 수정
- [config.py](../config.py) — FP/TP/AI_FILTER 일괄 반영

## test_sensitivity 보완 (추가 작업)

사용자 지적: "test_sensitivity의 주 목적은 적정 기대수익률·보유기간 최적화 아니었나"
→ 코드 점검 결과 **AI_FORECAST_PERIOD sweep이 아예 없고**, AI_TARGET_PCT는 양성비만 측정(정밀도/수익률 안 봄)으로 사용자 의도와 코드 사이에 간극 있었음.

### 보완 내용

- `predict.Add_AI_Signals` 시그니처 확장: `target_pct`/`forecast_period`/`ai_filter` 인자 추가 (None이면 모듈 상수 사용 — 기존 호출 호환)
- `test_sensitivity`에 신규 검증 두 개 추가:
  - **검증 6: `test_forecast_period`** — FP=[3,5,7,10,14] sweep, 분류 정밀도 + 매매 메트릭 동시 측정
  - **검증 7: `test_target_pct`** — TP=[5,7,10,15,20] sweep, 동일 방식
- 새 함수는 매 sweep마다 `Add_AI_Signals`를 다시 호출 (신호 정의 자체가 바뀌므로)

### FP/TP 재검증 결과 (v10.2 적용 후)

**FP sweep (TP=7% 고정):**

| FP | CV정밀도 | 매매수 | 승률 | 평균수익 |
|---|---|---|---|---|
| 3일 | 0.334 | 27 | 74.1% | +16.22% |
| 5일 | 0.433 | 38 | 55.3% | +22.42% |
| 7일 | 0.514 | 45 | 51.1% | +6.41% |
| **10일** | **0.527** | **45** | **48.9%** | **+19.22%** ◀ |
| 14일 | 0.600 | 59 | 49.2% | +24.16% |

**TP sweep (FP=10일 고정):**

| TP | CV정밀도 | 매매수 | 승률 | 평균수익 |
|---|---|---|---|---|
| 5% | 0.629 | 56 | 44.6% | +17.28% |
| **7%** | **0.527** | **45** | **48.9%** | **+19.22%** ◀ |
| 10% | 0.452 | 40 | 57.5% | +18.59% |
| 15% | 0.317 | 35 | 60.0% | +20.65% |
| 20% | 0.267 | 28 | 60.7% | +8.36% |

### 재검증 해석

- 분류 정밀도와 매매 평균수익이 **이번엔 다른 답**: 정밀도는 (14일, 5%) 쪽, 수익은 (14일, 15%) 쪽.
- 단 (FP=14, TP=15%)는 매매수 35회로 표본 작음, (FP=14, TP=7%)는 평균수익 +24%로 약간 더 높음.
- **(FP=10, TP=7%) 유지 결정 — 안정성 우선**: 분류 정밀도 + 매매 평균수익 둘 다 양호한 균형점. 14일은 단기 스윙 시스템 정체성에 약간 부담.

## 다음 phase 후보

1. **screener 통과율 재측정** — 새 (FP, TP, AI_FILTER) + SCREENER_MIN_PRECISION=0.50 게이트 통과 종목 분포 확인
2. **stub backtest 전체 재실행** — 새 운용값으로 5종목 누적수익률/Sharpe 재산출하여 성능 회귀 없는지 확인
3. **system_master_plan.md 일괄 갱신** — v10.2로 헌법 동기화
4. **BB_SQUEEZE_RATIO 재캘리브레이션** — 새 라벨 정의 위에서 스퀴즈 신호 정확도
5. **스케줄러 자동화** — 신호 정의가 안정되었으니 매일 자동 실행 가능
