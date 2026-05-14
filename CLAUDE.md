# CLAUDE.md — Richman 퀀트 유니버스 프로젝트

> 이 파일은 Claude Code가 프로젝트 전반을 이해하고 일관된 방식으로 기여하기 위한 가이드입니다.
> 모든 답변과 코드 작업은 **한글**로 수행합니다.

---

## 프로젝트 개요

**목표:** 거시경제 기반 자산배분 + AI 기반 단기 스윙 트레이딩을 융합한 다중 전략 퀀트 시스템.

**핵심 전략:**
- Core (70%): 미국 지수 40% + 소형 가치주 30% (장기 보유)
- Satellite (30%): 나스닥 급등주 AI 스윙 매매 (본 시스템의 핵심)

**현재 타겟 마켓:** NASDAQ 중소형주 (시가총액 $3B~$50B, 거래량 2M+, ATR 3~10%)
- TICKERS(고정 분석용): IONQ, PLTR, SOFI (MARA/RIOT는 비트코인 연동으로 v8.3 제거)
- screener.py가 나스닥 전수조사 → predict.py로 AI 정밀 검증 → 최종 매매 대상 확정

---

## 파일 구조 및 역할

```
richman/
├── config.py            # [1단계] 모든 상수의 유일한 원천 (Single Source of Truth)
├── screener.py          # [2단계] 나스닥 전수조사 → 급등주 후보 자동 발굴 (Light 모드)
├── ta.py                # [3단계] 기술적 지표 + GMM 롤링 국면 판별
├── predict.py           # [4단계] XGBoost 급등 확률 예측 (5-Fold, Deep 모드)
├── kelly.py             # [5단계] Half-Kelly 최적 투입 비중 산출
├── backtest.py          # [5단계] 매매 일지 기반 스윙 전략 시뮬레이션
├── optimize.py          # [6단계] Optuna 2-Layer 최적화 (Expectancy Score 기반)
├── portfolio.py         # [6단계] Risk Parity 비중 배분 + 샤프 최적화
├── visualize.py         # [6단계] 5단 지표 패널 + 국면 배경색 시각화
├── trade_journal.py     # [7단계] CLI 매매 기록 + AI 추천 사후 검증
├── alert.py             # [8단계] 실시간 익절/손절 모니터링 + 텔레그램 알림
├── trader.py            # [9단계] 자동매매 (미구현 — Phase A/B/C)
│
├── trade_journal.xlsx   # 3시트: 매매일지 / AI추천로그 / 월간통계
├── alert_watchlist.json # 수동 감시 종목 목록
├── alert_history.json   # 알림 발송 이력 (최근 500건)
└── system_master_plan.md # 프로젝트 헌법 — 전략 철학 및 아키텍처 전체 문서
```

---

## 핵심 설계 원칙 (반드시 준수)

1. **No Hardcoding**: 모든 상수는 반드시 `config.py`에서 관리. 코드에 숫자 직접 삽입 금지.
2. **Backup Policy**: 주요 로직 수정 시 `파일명_backup.py` 생성 후 작업.
3. **Look-ahead Bias 차단**: 미래 데이터 참조 절대 금지. GMM은 Rolling Window로만 학습.
4. **CV Gap 적용**: 교차검증 시 train 마지막 `FORECAST_PERIOD`일 제거하여 타겟 누수 방지.
5. **스케일 독립성**: AI 피처는 반드시 비율/지수 형태(RSI, ADX, 이격도 등)만 사용. 절대 주가 사용 금지.
6. **시각화 품질**: 국면별 배경색, 매매 타점 등 직관적 시각화 요소 필수 포함.
7. **자동매매 안전 원칙**: 3개월 수동매매 수익 검증 전까지 실전 자동매매 착수 금지.

---

## 현재 핵심 파라미터 (v8.x 기준)

| 파라미터 | 현재 값 | 설명 |
|---|---|---|
| `RSI_BUY` / `RSI_SELL` | 42 / 84 | RSI 매수/매도 기준 (v10.1 Optuna) |
| `BB_SQUEEZE_RATIO` | 1.68 | 스퀴즈 탈출 판단 배율 (v10.1 Optuna) |
| `ADX_THRESHOLD` | 0 (비활성) | ADX 횡보 보조 기준 (v8.1에서 제거됨) |
| `AI_FILTER` | 0.55 | AI 확신도 매수 필터 (v10.2 헌법 회복) |
| `TRAILING_ATR_MULT` | 3.17 | Chandelier Exit ATR 배수 (v10.1 Optuna) |
| `AI_FORECAST_PERIOD` | 10일 | XGBoost 예측 기간 (v10.2 그리드 재캘리브레이션) |
| `AI_TARGET_PCT` | 7% | 급등 판단 기준 수익률 (v10.2 그리드 재캘리브레이션) |
| `TRAILING_STOP_PCT` | 5.5% | 퍼센트 기반 손절 대안 |
| `KELLY_FRACTION` | 0.5 | Half-Kelly 비율 |
| `FEE_RATE` | 0.4% | 편도 수수료 |
| `SATELLITE_ALLOCATION` | 30% | 스윙 자금 비율 |

**현재 AI 피처 (config.AI_FEATURES):**
```python
# v10 (현재): Volume_Ratio → Volume_Spike(>2 이진)로 교체 후
['RSI', 'Disparity', 'BandWidth', 'Volume_Spike', 'Slow_K', 'Slow_D']
```

---

## ta.py — 지표 및 국면 판별

### make_indicators() 출력 컬럼 (26개)

**기본 지표:** MACD, MACD_Signal, MACD_Hist, RSI, MA5/10/20/60/120, Upper/Lower/BandWidth (BB), ATR, Disparity, K/Slow_K/Slow_D (Stochastic), ADX

**파생 신호 (12개):**
| 컬럼 | 설명 |
|---|---|
| RSI_Slope | RSI 5일 기울기 (다이버전스 감지) |
| Price_Slope | 종가 5일 기울기 |
| Divergence | -1(약세)/0/+1(강세) 다이버전스 |
| BB_Squeeze | BandWidth > 20일평균 × BB_SQUEEZE_RATIO |
| BB_Width_Pct | BandWidth 전일 대비 변화율 |
| Stoch_Cross | +1(골든크로스)/-1(데드크로스) |
| MACD_Cross | +1/-1 교차 |
| MACD_Zero_Cross | MACD 0선 교차 |
| Price_Above_MA20 | Close > MA20 여부 |
| Volume_Ratio | 당일 거래량 / 20일 평균 거래량 |

### detect_regime() — GMM 롤링 국면 판별
- **피처:** Trend = (Close - MA60) / MA60, Vol = ATR / Close
- **방법:** 252일 롤링 윈도우 → 3-컴포넌트 GMM → Trend 평균으로 Bull/Sideways/Bear 매핑
- **ADX Override:** v8.1에서 제거됨 (ADX_THRESHOLD=0으로 비활성화)

---

## backtest.py — 매매 로직

### 국면별 전략
| 국면 | 전략 | 핵심 조건 |
|---|---|---|
| Bull | 추세 추종 | BB 상단 돌파 + BB_Squeeze → 매수 / RSI 고점 이탈 → 매도 |
| Sideways | 평균 회귀 | BB 밴드 돌파 + Stoch 교차 + RSI 박스권 |
| Bear | 방어적 단기 | 이격도 극단 침체 → 소량 매수, 과열 → 매도 |

### 가중 투표 (신호 충돌 해결)
- 매수 가중치 합계 ≥ +0.7 → 매수 승인
- 매도 가중치 합계 ≤ -0.7 → 매도 승인
- AI_Prob < AI_FILTER → 매수 강제 취소 (관망)

### Chandelier Exit
```python
trailing_stop = highest_price_since_entry - (current_atr × TRAILING_ATR_MULT)
```

---

## optimize.py — 2-Layer Optuna 최적화

| 레이어 | 속도 | 튜닝 대상 |
|---|---|---|
| Layer 2 | 빠름 | 매매 판단 파라미터 12개 (지표 재계산 없음) |
| Layer 1 | 느림 | 지표 산출 파라미터 8개 + Layer2 파라미터 동시 |

**Expectancy Score (최적화 목표값):**
```python
score = (avg_return_pct × 100) × win_rate × √trade_count
```
실격 조건: 매매횟수 < 10 or > 80, 승률 < 35%, 평균수익 ≤ 0

---

## predict.py — AI 예측 모드

| 함수 | 모드 | 설명 |
|---|---|---|
| `Analyze_Full(ticker)` | Deep | 단일 종목 정밀 분석 (5-Fold CV + GMM) |
| `Deep_Scan(tickers)` | Deep | 복수 종목 병렬 분석 |
| `Add_AI_Signals(df)` | Backtest | Walk-Forward 신호 부착 |

---

## trade_journal.py — Excel 3시트 구조

1. **매매일지**: Trade_ID, Ticker, Entry/Exit 정보, Return_Pct, AI_Prob, Regime, Stop_Price
2. **AI추천로그**: Rec_ID, AI_Prob, Hist_Precision, 10일 후 실제 수익, AI_Correct
3. **월간통계**: 월별 승률, 손익, AI 적중률, 놓친 수익

`show_holdings()` → 보유중(Result='⏳ 보유중') DataFrame 반환 → `alert.py`가 이를 읽어 모니터링

---

## alert.py — 실시간 알림

| 조건 | 레벨 | 알림 |
|---|---|---|
| 현재가 ≤ 손절가 | CRITICAL | 텔레그램 + 비프 |
| 손절가까지 3% 이내 | WARNING | 경고 |
| 현재가 ≥ 익절가 (+10%) | INFO | 익절 구간 진입 |
| +15% 이상 | INFO | 분할 익절 고려 |

쿨다운: CRITICAL 5분, 기타 10분

---

## 로드맵 (다음 단계)

| 우선순위 | 과제 | 상태 |
|---|---|---|
| 1 | 스케줄러 자동화 (screener + alert cron) | 🔜 다음 |
| 2 | Volume_Ratio AI 피처 점검 → Volume_Spike로 교체 | ✅ 완료 (2026-05-14) |
| 3 | 자동매매 Phase A (잔고/현재가 읽기 전용) | 📋 계획 |
| 4 | 자동매매 Phase B (모의매매) | 📋 계획 |
| 5 | 자동매매 Phase C (실전 — 3개월 검증 후) | 📋 계획 |

---

## 개발 시 주의사항

- **수정 전 반드시 백업** (`파일명_backup.py`)
- config.py 수정 시 관련 파일 전체 영향 파악 후 진행
- GMM 국면 판별은 롤링 방식 — 전체 데이터 한 번에 fit 하면 Look-ahead Bias 발생
- screener.py는 Light 모드 (1-Fold, GMM 생략)로 속도 최우선
- predict.py는 Deep 모드 (5-Fold + GMM)로 정확도 최우선
