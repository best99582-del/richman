# Phase B: ta 라이브러리 부분 교체 + ta.py → indicators.py 리네임

## 목적

Phase A 검증에서 우리 구현이 ta 라이브러리와 사실상 동일함을 확인 후,
**RSI/MACD/BB/ATR/ADX 5개 표준 지표를 ta 라이브러리 호출로 교체**하여
코드 간소화.

## 핵심 변경

### 1. 이름 충돌 해결: `ta.py` → `indicators.py`

로컬 `ta.py`가 외부 `ta` 라이브러리를 가려서 `import ta`로 외부를 못 씀.
git mv로 깔끔하게 리네임:

```
ta.py → indicators.py
```

12개 파일의 import 일괄 교체:
- alert.py, backtest.py, feature_experiment.py, optimize.py, visualize.py
- screener.py, predict.py, test_*.py 등

### 2. 외부 ta 라이브러리로 5개 지표 교체

| 지표 | 변경 |
|---|---|
| RSI | `ta.momentum.RSIIndicator(close, window).rsi()` |
| MACD | `ta.trend.MACD(close, slow, fast, signal)` |
| BB | `ta.volatility.BollingerBands(close, window, dev)` |
| ATR | `ta.volatility.AverageTrueRange(high, low, close, window)` |
| ADX | `ta.trend.ADXIndicator(high, low, close, window)` |

### 3. 유지된 코드

- **Stochastic (Slow_K/Slow_D)**: 우리 정의 유지 (라이브러리와 평활 깊이 다름)
- **이동평균 (MA5/10/20/60/120)**: pandas rolling 그대로
- **Disparity**: EMA20 대비 비율 (자체 정의)
- **파생 신호 12개**: RSI_Slope, Divergence, BB_Squeeze, MACD_Cross 등 모두 유지
- **GMM 국면 판별** (`Detect_Regime`): 그대로
- **BandWidth 계산**: `(Upper-Lower)/MA20*100` 우리 정의 유지

### 4. 제거된 코드

- `get_rma()` Wilder's RMA 헬퍼 함수 — 더 이상 호출처 없음
- 약 40줄 감소 (RSI/ATR/ADX 직접 구현)

## 검증 결과 — 새 indicators.py vs 옛 ta_backup.py

3종목(APLD/SOFI/AAPL) × 17지표 비교:

### ✅ 사실상 동일 (rel_diff < 1%)

- MACD/MACD_Signal/MACD_Hist: 0.001~0.08%
- RSI: 0.04~0.25%
- BB Upper/Lower: 0.14~0.83%
- ATR: 0.001~0.14%
- ADX: 0.005~0.11%
- **Slow_K/Slow_D**: **0.000%** (정확히 동일 — 우리 구현 유지)
- **Disparity**: **0.000%**
- RSI_Slope: 0.2~0.6%
- Divergence: 0.09~0.26%
- BB_Squeeze: 100% bool 일치
- Stoch_Cross: 0.000%

### 🟡 일부 미세 차이

- **BandWidth**: rel_diff 2.5% — Upper/Lower의 0.5~0.8% 차이가 비율 계산에서 증폭
- **MACD_Cross**: rel_diff 2.5~4% — MACD_Signal 0.001~0.08% 차이로 인한 ±1봉 교차 시점 변동

## 백테스트 영향 평가

| 지표 | 영향 | 대응 |
|---|---|---|
| MACD_Cross 시점 ±1봉 | 매매 진입/청산 일이 미세하게 바뀔 수 있음 | 백테스트 재실행하면 확인 가능 |
| BandWidth 2.5% | BB_Squeeze 판정에 영향 가능 | 검증 결과 BB_Squeeze는 100% 일치 |
| 기타 모든 지표 | 사실상 동일 | 영향 없음 |

→ **AI 모델 재학습 / Optuna 재최적화 필요성: 매우 낮음**.
   MACD_Cross가 가끔 ±1봉 차이날 수 있지만 백테스트의 표본수가 충분히 많아
   기댓값 변화는 거의 없을 것으로 예상.

## 파일

- 백업: [ta_backup.py](../ta_backup.py) (git ignore됨, 디스크에만)
- 신규: [indicators.py](../indicators.py)
- 검증 스크립트: [verify_ta_library.py](../verify_ta_library.py)
- Phase A 문서: [phase_ta_verify.md](phase_ta_verify.md)

## 상태

- [x] ta.py → indicators.py 리네임 (git mv)
- [x] 12개 파일 import 일괄 교체
- [x] 외부 ta 라이브러리로 5개 지표 교체
- [x] get_rma() 헬퍼 제거 (40줄 감소)
- [x] 백업 vs 신규 지표 비교 검증 (Phase A)
- [x] 5종목 백테스트 결과 비교 검증
- [x] phase 문서 작성
- [x] 커밋 + GitHub push (커밋 d7bf392)

## 백테스트 영향 (5종목 실측)

| 종목 | 매매수 | 평균 수익률 | 누적 수익 |
|---|---|---|---|
| APLD | 동일(2) | **완전 일치** (164.71%) | 493.47% (동일) |
| **SOFI** | 동일(10) | 22.99% → **23.13%** (+0.14%p) | 316.78% → **322.63%** (+5.85%p) |
| IONQ | 동일(3) | 완전 일치 (107.15%) | 591.67% (동일) |
| PLTR | 동일(2) | 완전 일치 (-2.06%) | -5.35% (동일) |
| RKLB | 동일(4) | 완전 일치 (29.39%) | 79.58% (동일) |

**결론:**
- 4/5 종목 완전 일치
- SOFI 1건의 매매가 손실→이익으로 전환 (MACD_Cross ±1봉 차이가 유리하게 작용)
- **악화 아닌 미세 개선** → 백테스트 재학습 불필요 확정
