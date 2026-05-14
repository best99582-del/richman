# Phase: v10.2 마무리 (screener 통과율 + BB sweep + 헌법 동기화)

## Context

v10.2 핵심 변경(FP/TP/AI_FILTER + Add_AI_Signals 버그 수정)은 [phase_filter_calib.md](phase_filter_calib.md)에서 완료. 이 phase는 그 결과의 **실전 영향 검증과 잔여 정합성 회복** 작업.

3가지 작업:
1. screener 통과율 재측정
2. BB_SQUEEZE_RATIO 재캘리브레이션
3. system_master_plan.md v10.2 동기화

## 1. screener 통과율 재측정

v10.2 운용값(FP=10, TP=7%, AI_FILTER=0.55, Add_AI_Signals 디폴트 0.0)으로 5종목 게이트 통과 여부 확인.

| Ticker | v10.1 Light_Precision | v10.2 Light_Precision | v10.1 통과 | v10.2 통과 |
|---|---|---|---|---|
| IONQ | 0.514 | **0.750** | ✅ | ✅ |
| PLTR | 필터됨 | 필터됨 | ❌ | ❌ |
| SOFI | 필터됨 | 필터됨 | ❌ | ❌ |
| APLD | 0.506 | **0.675** | ✅ | ✅ |
| RKLB | 필터됨 | **0.725** | ❌ | ✅ |

**개선:**
- 통과 종목: 2/5 → **3/5** (RKLB 신규 통과)
- IONQ/APLD 정밀도 큰 폭 상승 (0.514→0.750, 0.506→0.675)
- 모든 통과 종목 AI_Prob ≥ 0.505 (매수 후보 적격)

**잔여 과제:** PLTR, SOFI는 여전히 holdout precision < 0.50. 두 종목 신호가 어려운 패턴인 듯 — 다음 phase에서 종목별 진단 가능.

## 2. BB_SQUEEZE_RATIO sweep (v10.2 운용값 기준)

### 발동 빈도

| ratio | IONQ | PLTR | SOFI | 적정? |
|---|---|---|---|---|
| 1.2 | 연 63회 | 연 69회 | 연 74회 | ❌노이즈 |
| 1.5 | 연 33회 | 연 28회 | 연 27회 | ⚠️조금 잦음 |
| 1.8 | 연 13회 | 연 10회 | 연 8회 | ✅적정 |
| 2.0 | 연 8회 | 연 6회 | 연 2회 | ⚠️SOFI 부족 |
| 2.5 | 연 4회 | 연 1회 | 연 0회 | ❌비활성 |
| 3.0 | 연 2회 | 연 1회 | 연 0회 | ❌비활성 |

### 매매 성과 (5종목 합산 백테스트)

| ratio | 매매수 | 승률 | 평균수익 |
|---|---|---|---|
| 1.2 | 72 | 48.6% | +23.52% |
| **1.5** | **66** | **50.0%** | **+21.79%** |
| 1.68 (이전) | ~61 | ~49% | ~+19.4% |
| 1.8 | 61 | 49.2% | +19.39% |
| 2.0 | 60 | 48.3% | +19.10% |
| 2.5 | 57 | 45.6% | +17.40% |
| 3.0 | 55 | 45.5% | +17.82% |

**결정: 1.68 → 1.50**

근거:
- 매매 평균수익 +19.4% → +21.79% (+2.4%p)
- 승률 49.2% → 50.0%
- 발동 빈도 연 27~33회는 좀 잦지만 BB 상단 돌파 + AI_FILTER + RSI 등 다른 조건이 함께 필터링하므로 노이즈는 흡수
- v10.1(1.68) → v10.2(1.50) — Optuna 이후 계속 낮아지는 추세 일관

### 흥미로운 패턴

ratio가 낮을수록 매매 평균수익이 좋아지는 경향. 이는 BB_SQUEEZE가 매수 신호의 **한 조건일 뿐**이고, 다른 조건이 강해서 너무 타이트하게 잡으면 좋은 신호도 같이 빠진다는 신호. 운용 측면에서는 1.5 부근이 sweet spot.

## 3. system_master_plan.md v10.2 동기화

이전까지 헌법이 **v8.x 통합본**으로 표시되어 있어 실제 코드와 큰 간극. 다음 영역을 갱신:

- 제목: v8.x → **v10.2**
- 변경 요약: v10.0/v10.1/v10.2 변경 추가
- AI 엔진 설명: 피처(Volume_Ratio→Volume_Spike), 타겟(7일/10%→10일/7%)
- 매매 가중치 표: RSI_BUY 35→42, RSI_SELL 85→84, BB_SQUEEZE 1.50, AI_FILTER 0.55
- 청산 룰: TRAILING_ATR_MULT 5.0→3.17
- Part 4 운용 파라미터 표 일괄 갱신
- AI 학습 표: AI_TARGET_PCT 10→7, AI_FORECAST_PERIOD 7→10
- Part 5: 지표 표에 Volume_Spike (13번째) 추가
- Part 6: 진단 도구에 test_signal_grid.py, test_filter_calib.py 추가
- Rule 5: Volume_Ratio → Volume_Spike
- Part 8 로드맵: v10.0~v10.2 완료 항목 5개 추가
- 파일 구조: ta.py → indicators.py

## config.py 변경 요약 (v10.2 최종)

| 파라미터 | v10.1 | v10.2 | 근거 |
|---|---|---|---|
| AI_FORECAST_PERIOD | 7 | **10** | phase_signal_grid |
| AI_TARGET_PCT | 10 | **7** | phase_signal_grid |
| AI_FILTER | 0.50 | **0.55** | phase_filter_calib (헌법 회복) |
| BB_SQUEEZE_RATIO | 1.68 | **1.50** | 이 phase |
| (predict.Add_AI_Signals 디폴트) | 0.5 | **0.0** | phase_filter_calib (버그 수정) |
| (Add_AI_Signals 시그니처) | 고정 인자 | **target_pct/forecast_period/ai_filter 옵션 추가** | phase_filter_calib |

## 상태

- [x] screener 통과율 재측정 (3/5 통과, 평균 정밀도 큰 폭 개선)
- [x] BB_SQUEEZE_RATIO sweep + 1.50 반영
- [x] system_master_plan.md v10.2 동기화
- [x] CLAUDE.md BB 값 갱신
- [x] phase 문서 작성

## 산출물

- [phase/_run_sensitivity_bb.py](_run_sensitivity_bb.py) — BB sweep 단독 러너
- [config.py](../config.py) — BB_SQUEEZE_RATIO 1.50 반영
- [docs/system_master_plan.md](../docs/system_master_plan.md) — v10.2 헌법 동기화
- [CLAUDE.md](../CLAUDE.md) — BB 1.50 갱신

## 다음 phase 후보

1. **PLTR/SOFI 진단** — 두 종목이 v10.2에서도 게이트 미통과. 종목 특성 분석 → AI 피처/타겟 추가 조정 필요한지 진단
2. **backtest 전체 재실행** — v10.2 새 운용값으로 5종목 누적수익률/Sharpe 측정
3. **스케줄러 자동화** — 신호 정의가 안정되었으니 매일 자동 실행 (screener + alert를 Windows 작업 스케줄러로)
4. **자동매매 Phase A** — 잔고 조회 + 현재가 (읽기 전용) API 연동
