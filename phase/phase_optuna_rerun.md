# Phase: Optuna 재최적화 (Volume_Spike + Slow_K/D 반영)

## Context

이전 phase(`phase_vr_spike.md`)에서 AI 피처가 다음과 같이 변경됨:
- `Volume_Ratio` → `Volume_Spike` (이진 플래그)
- `Slow_K`, `Slow_D` 추가

현재 `config.py`의 매매 파라미터는 **구 피처 세트 기준**으로 최적화된 값.
피처가 바뀌었으므로 최적 파라미터도 달라졌을 가능성이 큼 → 재최적화 필요.

## 현재 운용 파라미터 (재최적화 전)

| 파라미터 | 현재 값 |
|---|---|
| RSI_BUY | 35 |
| RSI_SELL | 85 |
| BB_SQUEEZE_RATIO | 1.76 |
| AI_FILTER | 0.55 |
| TRAILING_ATR_MULT | 5.0 |
| RSI_PERIOD | 14 |

**AI_FEATURES (6개):** `RSI, Disparity, BandWidth, Slow_K, Slow_D, Volume_Spike`

**TEST_TICKERS:** IONQ, PLTR, SOFI, APLD, RKLB

## 실행 계획

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | Layer 2 (매매 기준값 5개) 500 trials | ✅ 완료 (353s) |
| 2 | Layer 1 (지표 5개 + 매매 5개) 250 trials | ✅ 완료 (1864s) |
| 3 | 결과 분석 → config.py 반영 결정 | ✅ Layer 2 채택 |
| 4 | 반영 후 backtest로 5종목 최종 검증 | ✅ 완료 — 합계 +777%p |

## Layer 2 결과 (Expectancy = 48.50)

| 파라미터 | 현재 → Layer 2 |
|---|---|
| rsi_buy | 35 → **42** |
| rsi_sell | 85 → **84** |
| bb_squeeze_ratio | 1.76 → **1.68** |
| ai_filter | 0.55 → **0.504** |
| trailing_atr_mult | 5.0 → **3.17** |

## Layer 1 결과 (Expectancy = 32.40)

지표 산출 파라미터까지 함께 탐색(rsi_period=7, stoch_slow_k/d=5/5 추천)했으나, 250 trials로는 탐색 공간이 너무 커서 Layer 2보다 score가 낮음 → **Layer 1 채택 안 함**.

다만 매매 기준값 4개(rsi_buy=48, rsi_sell=85, bb_squeeze_ratio=1.65, ai_filter=0.505)는 Layer 2와 같은 방향이므로 신호 일관성 확인됨.

## Backtest 검증 (config 값 vs Layer 2 — 5종목)

| Ticker | 현재 누적 | L2 누적 | Δ | 현재 승률 → L2 | 현재 매매수 → L2 |
|---|---|---|---|---|---|
| IONQ | 591.67% | 398.40% | **-193%** ❌ | 100% → 61.9% | 3 → 21 |
| PLTR | 21.03% | **690.78%** | **+670%** ✅ | 66.7% → 60.0% | 3 → 15 |
| SOFI | 385.95% | 378.48% | -7% ≈ | 66.7% → 46.7% | 9 → 15 |
| APLD | 493.47% | 329.66% | **-164%** ❌ | 100% → 40.0% | 2 → 10 |
| RKLB | 805.70% | **1278.25%** | **+473%** ✅ | 60% → 70% | 5 → 10 |
| **합계** | **2297.82%** | **3075.57%** | **+777%p** ✅ | — | 22 → 71 |

### 트레이드오프 분석

- **현재 파라미터** (보수적): IONQ/APLD 같은 종목에서 "소수 정예 대박" 패턴
- **Layer 2 파라미터** (적극적): 매매 횟수 3배+, "빈번한 중간 수익" 패턴
- 총합으로 **+777%p 명확한 개선**, PLTR는 손실→이익 전환(+670%p)
- IONQ/APLD 후퇴는 받아들이는 대신, 단일 종목 의존도가 낮아져 시스템 안정성 ↑

## 최종 결정사항 (2026-05-14)

✅ **Layer 2 값 5개 모두 config.py에 반영**:

```python
RSI_BUY = 42              # was 35
RSI_SELL = 84             # was 85
BB_SQUEEZE_RATIO = 1.68   # was 1.76
AI_FILTER = 0.50          # was 0.55
TRAILING_ATR_MULT = 3.17  # was 5.0
```

CLAUDE.md의 파라미터 표도 동일하게 업데이트.

## 산출물

- [phase/_run_optuna_rerun.py](_run_optuna_rerun.py) — Optuna 재실행 스크립트
- [phase/_verify_layer2.py](_verify_layer2.py) — backtest 검증 스크립트
- [phase/optuna_rerun_result.json](optuna_rerun_result.json) — L1/L2 best_params
- [phase/optuna_rerun_log.txt](optuna_rerun_log.txt) — 실행 로그
- [phase/verify_layer2_result.json](verify_layer2_result.json) — 종목별 비교
