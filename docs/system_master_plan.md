# 🌌 [퀀트 유니버스] Richman 프로젝트 마스터 가이드 (v8.x 통합본)

> **본 문서는 Richman 프로젝트의 헌법이며, 모든 개발 작업은 이 문서의 지침 아래 수행됩니다.**
>
> **v8.x 변경 요약**
> - GMM 국면 분기 전략 제거 → 통합 단일 전략으로 단순화
> - AI 타겟 정의 변경: High any → Close max (실현 가능한 종가 기준)
> - AI 피처 경량화: 8개 → 4개 (RSI, Disparity, BandWidth, Volume_Ratio)
> - Walk-Forward 정밀도 holdout 분리 측정 (정밀도 부풀림 방지)
> - v9.1 Sensitivity 재실행 반영 (AI_FILTER 0.55, RSI_BUY 35, TRAILING_ATR_MULT 5.0)
> - 진단 도구 추가: test_predict.py, test_sensitivity.py, feature_experiment.py

---

## 📌 Part 1. 핵심 투자 철학 및 자산 배분 전략

본 시스템은 단일 매매 로직에 의존하지 않고, **거시경제 기반 자산배분**과 **룰베이스 단기 트레이딩**을 융합한 다중(Multi) 전략을 구사합니다.

### 1. 🌐 전체 자본 배분 (Level 1: Core / Satellite)
*   **배분 방식:** 전체 자본을 **Core 70%** 와 **Satellite 30%** 로 분리하여 운용.
*   분기 1회 리밸런싱으로 비중 유지.

### 2. 📈 세부 포트폴리오 구성 (Level 2)

*   **🛡️ Core (70%) — 한국형 올웨더 자산배분**
    *   **구성:** 국내 주식(Korea Quant 시스템 별도 운용) · 해외 주식(나스닥/S&P) · 한국 국채 · 미국 국채 · 금
    *   배분 비중은 백테스트 검증으로 확정된 **R-3 고정 비중** 적용 (Markowitz 동적 최적화 대비 OOS 성능 우위 확인)
    *   국내 주식 부분은 워크스페이스의 **Korea Quant** 시스템이 담당하며, 본 Richman 프로젝트와는 독립적으로 운용됨.

*   **⚔️ Satellite (30%) — AI 기반 단기 스윙 매매 (본 시스템의 핵심)**
    *   `screener.py` (나스닥 중소형주 전수조사, Light 모드) → `predict.py` (XGBoost 5-Fold 정밀 검증, Deep 모드) 2단계 파이프라인으로 매매 대상 확정.
    *   **타겟 유니버스:** 나스닥 중소형주 (시가총액 $3B~$50B / 20일 평균 거래량 ≥ 2M / ATR 변동성 3~10% / 최소 250일 데이터)
    *   **AI 엔진:** XGBoost (n_estimators=100, max_depth=2, lr=0.01) — 피처 6종(RSI · Disparity · BandWidth · Volume_Ratio · Slow_K · Slow_D)의 최근 3일 윈도우로 **7일 후 종가 +10% 상승 확률** 예측. CV Gap을 적용한 5-Fold 교차검증으로 정밀도 검증.
    *   **진입 조건 (가중 투표, 합계 ≥ +0.7 시 매수):**
        *   **주 신호 (+1.0):** BB 상단 돌파 + BB 스퀴즈 탈출(BandWidth > 20일 평균 × 1.76)
        *   **보조 신호 (+0.7):** RSI < 35 (과매도 반등)
        *   **확신도 가산:** MACD 골든크로스 (+0.3) / MACD 0선 상향 돌파 (+0.2)
        *   **AI 게이트:** AI 확신도 < 0.55 → 매수 신호 전부 차단
    *   **청산 조건 (셋 중 하나라도 충족 시):**
        *   **모멘텀 소진 매도:** 전일 RSI > 85에서 당일 RSI < 85로 이탈
        *   **하락 전환 매도:** 종가 < BB 하단 × 1.05 **AND** MACD 데드크로스
        *   **최초 손절:** 진입가 − ATR × 2.0
        *   **트레일링 스탑 (Chandelier Exit):** 보유 중 최고가 − ATR × 5.0
    *   **포지션 사이징:** Half-Kelly (KELLY_FRACTION=0.5, 손익비 2.0 고정) · 단일 종목 최대 20% 한도 · 수수료 편도 0.4% 반영
    *   🔄 **모든 매매 내역은 `trade_journal.py` (3시트 Excel: 매매일지/AI추천로그/월간통계)에 기록되며, `alert.py`가 보유 종목을 5분 주기로 모니터링 → 손절/익절 구간 진입 시 텔레그램 알림 발송.**
---

## 🏭 Part 2. 소프트웨어 파이프라인 (9단계 아키텍처)

### ⚙️ [1단계] 중앙 통제실 — `config.py` ✅
- 전체 시스템의 환경 변수를 통제하는 유일한 원천(Single Source of Truth)
- 종목 리스트, 수수료(0.4% 편도), AI 확신도, 트레일링 스탑 배수, Satellite 할당 비율(30%) 등
- 알림 설정(섹션 11), Detect_Regime 보존 상수(섹션 12) 포함

### 🦅 [2단계] 시장 전수조사 — `screener.py` ✅
- 나스닥 시가총액 $3B~$50B 중소형주 유니버스 추출
- **1차 필터:** 가격 ≥ $5, 거래량 ≥ 2M, ATR 변동성 3~10%
- **2차 Light AI:** Make_Indicators 26개 지표 + XGBoost 70/30 split + Laplace 정밀도 게이트
- 정밀도 < `SCREENER_MIN_PRECISION`(0.55)이면 후속 단계 진입 차단

### 📊 [3단계] 데이터 전처리 — `ta.py` ✅
- HTS 표준 수식(Wilder's RMA) 기반 지표 26개 산출
- `Detect_Regime()`은 **파이프라인 미사용 — 수동 분석 전용 보존 함수**
- v8.x: 통합 전략으로 일원화하면서 GMM 국면 분기 로직 제거

### 🧠 [4단계] AI 정밀 분석 — `predict.py` ✅
- XGBoost로 "이 종목이 N일 내에 급등할까?"를 확률(`AI_Prob`)로 산출
- **타겟 정의(v8.x):** entry 이후 `FORECAST_PERIOD`일 중 **최대 종가**가 `TARGET_PCT%` 이상 상승
    - 이전 High 기준 any 조건은 실현 불가능 수익을 학습해 양성비를 부풀리는 문제가 있어 폐기
- **5-Fold TimeSeriesSplit + Gap(`FORECAST_PERIOD`)** 으로 데이터 누수 차단
- **Laplace 스무딩 정밀도** `(hits + 1) / (total + 2)` 로 보수적 측정
- **Walk-Forward AI 부착(`Add_AI_Signals`):**
    - holdout 분리 측정 (학습 마지막 20%를 정밀도 측정 전용으로 떼어내 자기 점수 부풀림 방지)
    - `train_window=500`, `update_step=20`

### 💸 [5단계] 자금 관리 및 시뮬레이션 — `kelly.py` + `backtest.py` ✅
- **`kelly.py`:** AI 확신도 + 모델 정밀도 + 동적 손익비를 융합한 Half-Kelly 비중
    - 정밀도 ≤ 0.5 또는 AI_Prob < AI_FILTER 시 비중 0
    - `MAX_WEIGHT_PER_TRADE`(20%) 단일 종목 캡
- **`backtest.py`:** 매매 일지(Trade Log) 기반 시뮬레이터
    - 통합 전략(국면 분기 없음): BB 돌파+스퀴즈 / RSI 과매도/과매수 / MACD 보조
    - Chandelier Exit (트레일링 스탑) + ATR 기반 최초 손절
    - 가중 투표: 매수 ≥ +0.7 / 매도 ≤ -0.7

### 🚀 [6단계] 최적화 및 시각화 — `optimize.py` + `portfolio.py` + `visualize.py` ✅
- **`optimize.py`:** Optuna 2-Layer (지표 산출 / 매매 판단 분리), Expectancy Score 채점
    - 독소조항: 매매 < 10 or > 80, 승률 < 35%, 평균수익 ≤ 0
    - **주의:** Expectancy Score는 매매횟수에 가중치를 줘서 sensitivity 결과와 다를 수 있음 → sensitivity 우선
- **`portfolio.py`:** Macro(샤프 최대화) / Micro(역변동성 배분) 두 모드
- **`visualize.py`:** 5단 지표 패널 + 매매 타점 시각화

### 📓 [7단계] 매매 일지 및 사후 검증 — `trade_journal.py` ✅
- CLI 매매 기록, AI 추천 로그 사후 검증, 월간 통계
- `show_holdings()` → alert.py 연동

### 🚨 [8단계] 실시간 알림 — `alert.py` ✅
- 보유 종목 익절/손절 모니터링, 텔레그램/콘솔 알림
- 데이터 소스: trade_journal 보유 종목 + `alert_watchlist.json`

| 조건 | 레벨 | 알림 내용 |
|---|---|---|
| 현재가 ≤ 손절가 | 🚨 CRITICAL | 즉시 확인 + 비프 + 텔레그램 |
| 손절가까지 3% 이내 | ⚠️ WARNING | 손절가 접근 중 |
| 현재가 ≥ 익절가 (+7%) | 🎯 INFO | 익절 구간 진입 |
| +15% 이상 돌파 | 🔥 INFO | 분할 익절 고려 |

- 중복 방지: CRITICAL 5분, 기타 10분 쿨다운

```bash
python alert.py                    # 무한 모니터링 (5분 간격)
python alert.py --once             # 1회 체크 후 종료
python alert.py --add IONQ 30.00   # 수동 감시 추가
```

### 🤖 [9단계] 자동매매 — `trader.py` (미구현)
- Phase A: 잔고 조회 + 현재가 읽기 전용
- Phase B: 모의매매(PAPER)
- Phase C: 실전매매 — 3개월 수동 수익 검증 후 착수

---

## 🎯 Part 3. 매매 전략 (통합 단일 전략 — v8.x)

**핵심 변화:** GMM 국면 분기 전략(Bull/Sideways/Bear별 다른 로직)을 제거하고 단일 통합 전략으로 일원화했습니다.

이유: 국면 판별이 noisy하고, 국면별 분기가 종목 특이성을 반영하지 못해 백테스트 결과가 불안정했음. 통합 전략 + AI 확신도 필터가 더 안정적.

### 3-1. 매매 신호 (가중 투표)

**[매수 트리거]**

| 조건 | 가중치 | 비고 |
|---|---|---|
| BB 상단 돌파 + BB_Squeeze | +1.0 | 주 신호 (모멘텀 돌파) |
| RSI < `RSI_BUY` (35) | +0.7 | 보조 신호 (과매도 반등) |
| MACD 골든크로스 | +0.3 | 확신도 보강 |
| MACD 0선 상향 돌파 | +0.2 | 추세 확인 |
| Divergence = -1 (약세) | -0.3 | 매수 점수 차감 |

**[매도 트리거]**

| 조건 | 가중치 | 비고 |
|---|---|---|
| RSI 전일 > `RSI_SELL`(85), 당일 < `RSI_SELL` | -1.0 | 모멘텀 소진 |
| BB 하단 1.05배 접근 + MACD 데드크로스 | -1.0 | 하락 전환 확정 |
| MACD 데드크로스 | -0.3 | 매도 보강 |
| MACD 0선 하향 돌파 | -0.2 | 추세 약화 |

**[게이트]**
- AI_Prob < `AI_FILTER`(0.65) → 매수 가중치 강제 0 (AI 확신도 미달 시 매수 차단)
- 가중치 합계 ≥ +0.7 → 매수
- 가중치 합계 ≤ -0.7 → 매도

### 3-2. 청산 룰 (항상 적용)

| 조건 | 행동 |
|---|---|
| 고점 대비 ATR × `TRAILING_ATR_MULT`(5.0) 하락 | 트레일링 스탑 (Chandelier Exit) |
| 진입가 대비 ATR × `ATR_STOP_MULTIPLIER`(2.0) 하락 | 최초 손절가 터치 |
| 매도 신호 발동 | 청산 |

---

## 🔧 Part 4. 현재 운용 파라미터 (v8.x)

### 지표 산출 (Layer 1 — 튜닝 가능)

| 파라미터 | 현재 값 | 탐색 범위 | 설명 |
|---|---|---|---|
| `RSI_PERIOD` | 14 | 7, 9, 14 | RSI 산출 기간 |
| `MACD_VERSION` | 1 (12,26,9) | 1, 2, 3 | MACD 3버전 자동 선택 |
| `STOCH_PERIOD` | 14 | 14, 20 | 스토캐스틱 기간 |
| `STOCH_SLOW_K` | 3 | 3, 5 | |
| `STOCH_SLOW_D` | 3 | 3, 5 | |

### 매매 판단 (Layer 2 — 튜닝 가능)

| 파라미터 | 현재 값 | 탐색 범위 | 설명 |
|---|---|---|---|
| `RSI_BUY` | **35** | 30~55 | 과매도 반등 진입 (v9.1 sensitivity: 35가 매매수·승률·수익 모두 최고) |
| `RSI_SELL` | 85 | 65~85 | 과매수 이탈 매도 |
| `BB_SQUEEZE_RATIO` | 1.76 | 1.2~3.0 | BB 폭 확대 배율 |
| `AI_FILTER` | **0.65** | 0.50~0.70 | AI 확신도 임계값 (sensitivity 결과 0.65가 첫 양호값) |
| `TRAILING_ATR_MULT` | **5.0** | 1.5~5.0 | Chandelier Exit 배수 (v9.1 sensitivity: 승률 66.7%, 수익 +53%) |

### 리스크 / 자금 관리 (고정)

| 파라미터 | 현재 값 | 설명 |
|---|---|---|
| `KELLY_FRACTION` | 0.5 | Half-Kelly |
| `WIN_LOSS_RATIO` | **2.0** | 켈리 공식 손익비 고정 (v10: 동적→고정, ATR 큰 종목 비중 0 문제 해결) |
| `MAX_WEIGHT_PER_TRADE` | 0.20 | 단일 종목 최대 비중 (Satellite 자금 대비) |
| `SATELLITE_ALLOCATION` | 0.30 | 스윙 자금 비율 (전체 자본 대비) |
| `ATR_STOP_MULTIPLIER` | 2.0 | 진입가 기준 ATR 배수 손절 |
| `FEE_RATE` | 0.004 | 편도 수수료 |

### AI 학습 (고정)

| 파라미터 | 현재 값 | 설명 |
|---|---|---|
| `AI_FEATURES` | RSI, Disparity, BandWidth, Volume_Ratio, Slow_K, Slow_D | **6개 (현재)** |
| `AI_WINDOW_SIZE` | 3 | 패턴 인식 윈도우 (일, v9.1: 5→3 과적합 완화) |
| `AI_TARGET_PCT` | 10 | 목표 수익률 (%) |
| `AI_FORECAST_PERIOD` | 7 | 예측 기간 (일, Close 기준) |
| XGBoost 파라미터 | depth=2, reg_alpha=0.5, reg_lambda=2 | **v9.1 정규화 강화** |

### 스크리너 (고정)

| 파라미터 | 현재 값 | 설명 |
|---|---|---|
| `SCREENER_EXCHANGES` | ['NASDAQ', 'NYSE'] | 유니버스 거래소 |
| `SCREENER_MIN_MARKET_CAP` | **$1B** | 시총 하한 (v10: $3B→$1B) |
| `SCREENER_MAX_MARKET_CAP` | **$20B** | 시총 상한 (v10: $50B→$20B) |
| `SCREENER_MIN_PRICE` | $5 | 동전주 제외 |
| `SCREENER_MIN_TURNOVER` | **$20M** | 20일 평균 거래대금 ($) — v10에서 거래량→거래대금 |
| `SCREENER_MIN_VOLATILITY` | 3.0% | ATR 변동성 하한 |
| `SCREENER_MAX_VOLATILITY` | **12.0%** | ATR 변동성 상한 (v10: 10%→12%) |
| `SCREENER_MIN_PRECISION` | 0.55 | Light AI 정밀도 게이트 |
| `SCREENER_EXCLUDE_INDUSTRIES` | 8개 키워드 | 은행/보험/REIT/펀드/지주 제외 |
| `MARKET_CAP_CACHE_PATH` | market_cap_cache.json | yfinance 시총 캐시 |
| `MARKET_CAP_CACHE_DAYS` | 7 | 캐시 유효기간 (일) |

---

## 📊 Part 5. ta.py 파생 지표 (총 12개)

| # | 컬럼명 | 계산 방법 | 용도 |
|---|---|---|---|
| 1 | RSI_Slope | RSI 5일 기울기 | 다이버전스 감지 |
| 2 | Price_Slope | 종가 5일 기울기 | 다이버전스 감지 |
| 3 | Divergence | Price↑+RSI↓=-1, Price↓+RSI↑=+1 | 매도/매수 보조 |
| 4 | BB_Squeeze | BandWidth > (20일 평균 × ratio) | 횡보→강세 전환 |
| 5 | BB_Width_Pct | BandWidth 전일 대비 변화율 | 폭 변화 추적 |
| 6 | Stoch_Cross | Slow_K ↔ Slow_D 교차 | 골든/데드크로스 |
| 7 | MACD_Cross | MACD ↔ Signal 교차 | 모멘텀 전환 |
| 8 | MACD_Zero_Cross | MACD ↔ 0선 교차 | 추세 확인 |
| 9 | Price_Above_MA20 | Close > MA20 | 강세 확인 |
| 10 | ADX | Average Directional Index | 추세 강도 |
| 11 | ATR | Average True Range (Wilder's RMA) | 손절폭/트레일링 |
| 12 | Volume_Ratio | 당일 거래량 / 20일 평균 | 거래량 폭발 감지 |

---

## 🔬 Part 6. 진단 및 실험 도구 (v8.x 신규)

| 파일 | 역할 |
|---|---|
| `test_predict.py` | AI 비랜덤성 / 클래스 균형 / 피처 중요도 / 폭락 방어 4종 검증 |
| `test_sensitivity.py` | 파라미터 단일 스윕 (AI_FILTER, RSI_BUY/SELL, BB_SQUEEZE, TRAILING) |
| `feature_experiment.py` | 피처 세트 비교 (4개 / 5개 / 6개 / 8개) — 과적합 갭 측정 |

### 진단 → 튜닝 → 운용 워크플로우

```
1. test_predict.py        # AI 모델 건강성 점검 (정밀도, 클래스 균형, 피처 분산)
2. test_sensitivity.py    # 각 파라미터의 최적 구간 탐색 (사람이 눈으로 판단)
3. config.py 조정         # sensitivity 결과를 우선시하여 반영
4. feature_experiment.py  # (선택) 피처 세트 변경 효과 검증
5. optimize.py            # Optuna 자동 탐색 — 단, sensitivity와 충돌하면 sensitivity 우선
6. screener.py            # 나스닥 전수조사 → 후보 추출
7. predict.py TICKER ...  # 후보 정밀 분석 → 매수 판단
```

**중요:** `optimize.py`의 Expectancy Score는 매매횟수 가중치(`√매매횟수`)가 강해서 "신호가 많고 부진한 조합"을 우대합니다. `sensitivity` 결과와 충돌하면 **sensitivity 우선**.

---

## 🛠️ Part 7. AI 에이전트 개발 지침 (Rules)

1. **No Hardcoding:** 모든 상수는 `config.py`에서만 관리.
2. **Backup Policy:** 주요 로직 수정 시 `파일명_backup.py` 생성.
3. **Look-ahead Bias 차단:** 미래 데이터 참조 금지. GMM은 Rolling Window로만 학습 (보존 함수).
4. **CV Gap:** 교차검증 시 train 마지막 `FORECAST_PERIOD`일 제거 (타겟 누수 방지).
5. **스케일 독립성:** AI 피처는 비율/지수 형태(RSI, ADX, 이격도, Volume_Ratio)만. 절대 주가 사용 금지.
6. **시각화 품질:** 직관적 시각화 요소 필수.
7. **자동매매 안전 원칙:** 3개월 수동매매 수익 검증 전까지 실전 자동매매 착수 금지.
8. **measurement vs production 모델 인지:** 정밀도 측정용 모델과 실제 예측용 모델이 다름을 인지. Hist_Precision은 절대적 성능 보장이 아닌 "과거 패턴이 잘 작동한 약한 증거".

---

## 🗺️ Part 8. 향후 로드맵

| 우선순위 | 과제 | 상태 | 설명 |
|---|---|---|---|
| 1 | Sensitivity 기반 파라미터 튜닝 | ✅ v9.1 | AI_FILTER 0.55, RSI_BUY 35, TRAILING 5.0 반영 |
| 2 | 통합 전략 일원화 (GMM 제거) | ✅ v8.x | 국면 분기 제거, 단일 전략 |
| 3 | Walk-Forward holdout 정밀도 측정 | ✅ v8.x | 자기 채점 부풀림 차단 |
| 4 | 진단 도구 (test_predict / sensitivity) | ✅ v8.x | 4종 검증 + 5종 스윕 |
| 5 | screener 실전 검증 | 🔜 진행 중 | 실제 종목 추출 후 매매 결과 추적 |
| 6 | 스케줄러 자동화 | 🔜 다음 | screener + alert를 cron/작업스케줄러로 |
| 7 | 자동매매 Phase A | 📋 계획 | 잔고 조회 + 현재가 (읽기 전용) |
| 8 | 자동매매 Phase B | 📋 계획 | 모의매매(PAPER) |
| 9 | 자동매매 Phase C | 📋 계획 | 실전매매 (3개월 검증 후) |

---

## 📁 파일 구조 요약

```
richman/
├── config.py                # [1단계] 중앙 통제실
├── screener.py              # [2단계] 시장 전수조사 (Light AI)
├── ta.py                    # [3단계] 지표 + GMM 보존 함수
├── predict.py               # [4단계] AI 정밀 분석 (Deep Scan)
├── kelly.py                 # [5단계] Half-Kelly 자금 관리
├── backtest.py              # [5단계] 매매 일지 백테스트
├── optimize.py              # [6단계] Optuna 2-Layer 최적화
├── portfolio.py             # [6단계] 비중 배분 (Macro/Micro)
├── visualize.py             # [6단계] 시각화
├── trade_journal.py         # [7단계] 매매 일지 + AI 사후 검증
├── alert.py                 # [8단계] 실시간 알림
├── trader.py                # [9단계] 자동매매 (미구현)
│
├── test_predict.py          # 🔬 AI 모델 건강성 진단
├── test_sensitivity.py      # 🔬 파라미터 민감도 분석
├── feature_experiment.py    # 🔬 피처 세트 비교
│
├── trade_journal.xlsx       # 📊 매매 데이터 (3시트)
├── alert_watchlist.json     # 👁️ 수동 감시 종목
├── alert_history.json       # 📜 알림 발송 이력
│
└── docs/
    ├── system_master_plan.md  # 본 문서 (헌법)
    ├── archive_audit.md       # archive 코드 감사
    └── logic_audit.md         # 논리 감사
```
