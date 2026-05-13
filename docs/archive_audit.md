# 🔍 Archive 코드베이스 종합 평가 (archive_audit.md)

> **평가일**: 2026-05-05  
> **평가자**: 독립 AI 에이전트 (v2 코드/결론 미참조)  
> **대상**: c:\Users\admin\Desktop\richman\ 전체 11개 모듈

---

## 📋 모듈별 평가

### 1. `config.py` (221줄)

**핵심 로직 요약:**
- 전체 시스템의 Single Source of Truth. 11개 섹션으로 구조화.
- API 키를 환경변수에서 로드하는 보안 패턴 적용.
- Optuna 탐색 범위, 스크리너 필터 기준, 알림 설정까지 포괄.

**강점:**
- 모든 매직넘버가 한 파일에 집중됨 → 유지보수 탁월.
- MACD 3버전 매핑 테이블(`MACD_VERSIONS`)은 optimize.py와 깔끔하게 연동.
- `ADX_THRESHOLD = 0`으로 비활성화 가능한 설계는 유연함.

**결함/리스크:**
- `AI_TARGET_PCT = 10`(10일 내 10% 상승)은 나스닥 중소형주 기준으로도 **극히 드문 이벤트**. 양성 비율(Positive Rate)이 5% 이하로 추정되어 모델이 거의 모든 것을 "안 오른다"로 예측할 유인이 큼.
- `FEE_RATE = 0.004`(편도 0.4%)는 미국 주식 실전 기준 **과대 추정**. 키움/미래 등 주요 증권사 미국주식 수수료는 편도 0.07~0.25% 수준.
- `SCREENER_MIN_MARKET_CAP = 3e9`은 "중소형주"라기보다 **중형주 하한**. 실제 소형주($500M~$3B)를 놓칠 수 있음.

**Lookahead Bias:** 없음 (설정 파일이므로 해당 없음)

---

### 2. `ta.py` (464줄)

**핵심 로직 요약:**
- Wilder's RMA 기반 RSI/ATR/ADX 산출 (HTS 일치 목표).
- 26개 기본+파생 지표 생성 (RSI_Slope, Divergence, BB_Squeeze 등).
- GMM 롤링 윈도우 국면 판별 (`Detect_Regime`) — QQQ 프록시 지원.

**강점:**
- `get_rma()` 함수는 Wilder 원문에 충실한 구현. 초기값 SMA 처리도 정확.
- `Detect_Regime()`의 QQQ 프록시 전략은 소형주에 직접 GMM을 적용할 때의 노이즈 문제를 우회하는 훌륭한 아이디어.
- `_load_params()` 헬퍼로 optimize.py 오버라이드를 깔끔하게 지원.
- `Volume_Ratio` 파생 지표 추가로 거래량 폭발 감지 가능.

**결함/리스크:**
- `Detect_Regime()`은 **매 행(i)마다 GMM을 fit**함 (L290~L330). 252일 윈도우 × 전체 데이터 = O(N × 252) 반복. 1,500행 데이터 기준 약 **2~5분 소요** → screener에서 수백 종목에 적용 불가 (실제로 screener에서는 제거됨).
- GMM `warm_start=False`로 매 윈도우마다 완전 재학습 → 국면 전환이 불연속적(chattering) 가능성.
- `BB_Squeeze` 판별에 사용되는 `bb_squeeze_ratio`가 `_load_params()`를 통해 전달되지만, `Detect_Regime()` 내부에서는 사용되지 않아 국면과 스퀴즈 사이에 불일치 가능.

**Lookahead Bias 검증:**
- ✅ `Detect_Regime()` L294: `mask = source_index < today` — 오늘 미만(strictly past) 사용. **정상.**
- ✅ `Make_Indicators()`: 모든 지표가 `.shift()`, `.rolling()`, `.ewm()` 등 과거 데이터만 사용. **정상.**
- ⚠️ L308: `gmm.predict(scaled_train)` 호출이 means 매핑과 오늘 예측 양쪽에서 2번 발생 — 비효율적이나 bias는 아님.

---

### 3. `screener.py` (392줄)

**핵심 로직 요약:**
- 나스닥 시총 $3B~$50B 중소형주를 유니버스로 추출.
- 가격/거래량/변동성 1차 필터 후 XGBoost "Light AI" 스캔.
- GMM 제거, 5-Fold 제거 → 70/30 단순 split으로 속도 확보.

**강점:**
- screener/predict 2단계 분리 아키텍처는 실전적. 빠른 필터(Light) → 정밀 분석(Deep) 파이프라인.
- `SCREENER_MAX_VOLATILITY = 10.0`으로 비트코인 연동 극단주 제거 — 실전 경험에서 나온 좋은 판단.
- CV Gap (`gap = FORECAST_PERIOD`, L188) 적용으로 타겟 누수 방지.

**결함/리스크:**
- **Light AI 정밀도의 신뢰성 문제**: 70/30 단순 split은 시계열에서 **단 하나의 시점**에서만 모델을 평가. 해당 시점이 강세장/약세장이냐에 따라 정밀도가 극단적으로 달라짐.
- `_quick_analyze()` L219~L228: 정밀도 측정 후 **전체 데이터(X_all, y_all)**로 재학습하여 현재 예측 → 이 재학습 모델은 **미래 정보(y_all의 뒷부분)를 학습**한 상태. 즉, 정밀도는 70/30으로 측정했지만 실제 예측에 사용되는 모델은 100%를 본 모델 → **과신 위험**.
- 간이 국면 판별(L168~L179)에서 `ADX_THRESHOLD = 0`이면 항상 `trend > 0`에 따라 Bull/Bear만 판정 → Sideways가 나올 수 없음.

**Lookahead Bias:**
- ⚠️ **L219~L228**: 전체 데이터 재학습 모델로 현재 예측 — 타겟(y_all) 마지막 부분은 미래의 High를 포함. 엄밀히는 bias이나, 가장 최근 `FORECAST_PERIOD`(10일)만 영향받고 그 나머지 데이터는 과거이므로 **실전 영향은 제한적**.

---

### 4. `predict.py` (431줄) ⭐ 가장 중요

**핵심 로직 요약:**
- `Analyze_Full()`: GMM 국면 + 5-Fold CV + XGBoost + Kelly + 거래량 분석 종합.
- `Add_AI_Signals()`: Walk-Forward 방식으로 backtest용 AI_Prob 부착.
- `Deep_Scan()`: 복수 종목 배치 분석 + 대시보드 출력.

**강점:**
- 5-Fold `TimeSeriesSplit`에 **CV Gap** (`safe_train_idx = train_idx[:-FORECAST_PERIOD]`, L139) 적용 — 타겟 누수를 의식적으로 차단한 훌륭한 설계.
- `_laplace_precision()`: 라플라스 스무딩으로 소표본 정밀도 과대평가 방지.
- `_create_model()` 팩토리 패턴으로 모델 설정 중복 제거.
- `Add_AI_Signals()` Walk-Forward: `train_end = i - FORECAST_PERIOD` (L378)로 미래 참조 차단.

**결함/리스크:**
- **AI_TARGET_PCT = 10% 문제 (가장 큰 리스크)**: 10일 내 10% 상승은 양성 비율이 극히 낮음. XGBoost가 "모든 것을 0으로 예측"해도 높은 정확도를 달성 → `AI_Prob`이 대부분 0.1~0.3 범위에 몰리면서 `AI_FILTER(0.52)` 통과가 사실상 불가능할 수 있음.
- **Analyze_Full() L163~L172 (screener와 동일 문제)**: 전체 데이터로 최종 모델 학습 후 현재 예측 → 5-Fold CV의 정밀도와 실제 예측 모델이 다름.
- **AI_FEATURES 구성**: `['RSI', 'Disparity', 'BandWidth', 'Volume_Ratio']` 4개만 사용. 추세 방향(MACD, Price_Slope)이나 모멘텀 전환(MACD_Cross, Stoch_Cross) 신호가 빠져 있어 급등 포착에 핵심 정보 결여.
- `Add_AI_Signals()` L374: `update_step = 20` 고정 → 20영업일 간격으로만 모델 갱신. 급변하는 시장에서 반응 지연.

**Lookahead Bias:**
- ✅ `Add_AI_Signals()` L378: `train_end = i - FORECAST_PERIOD` — **정상. 미래 참조 완벽 차단.**
- ✅ `Analyze_Full()` 5-Fold CV L139: `safe_train_idx = train_idx[:-FORECAST_PERIOD]` — **정상.**
- ⚠️ `Analyze_Full()` L163~L172: 최종 예측 모델은 전체 데이터 학습 — **약한 bias** (위 설명 참조).

---

### 5. `backtest.py` (367줄)

**핵심 로직 요약:**
- `Get_Trade_Decision()`: 국면별 가중 투표 방식 매매 판단 (Bull/Sideways/Bear 3전략).
- `Backtest_Strategy()`: 순회하며 매매 일지 생성 + 성과 통계.
- ATR 기반 Chandelier Exit + 최초 ATR 손절 이중 방어.

**강점:**
- 국면별 전략 분리(추세추종 vs 평균회귀 vs 방어매매)는 교과서적으로 올바른 접근.
- 가중 투표 시스템(signal += 0.3 등)으로 보조 지표의 확신도 반영.
- AI 확신도 게이트(L176): `signal > 0 and not ai_pass → 0` — 매수 필터로 활용.
- 매도 시 수수료 양방향 차감 (`entry × (1+fee)`, `exit × (1-fee)`) — 현실적.

**결함/리스크:**
- **커스텀 샤프 지수** (L334): `(avg_return / std_return) × √(trade_count)` — 이것은 **표준 샤프 지수가 아님**. 표준 샤프는 연간화된 초과수익/변동성. 이 커스텀 지표는 거래 횟수가 많을수록 무조건 높아지는 편향이 있음.
- **Single position only**: 한 번에 하나의 포지션만 보유 가능 → 여러 종목 동시 매매 불가.
- Bull 전략 L74: `df['Close'].iloc[i] > df['Upper'].iloc[i-1]` — 어제의 Upper와 오늘의 Close 비교는 의도적이나 직관적이지 않음.
- **MDD(Maximum Drawdown) 미산출**: 리스크의 핵심 지표인 MDD가 없어 전략의 실전 위험도 파악 불가.

**Lookahead Bias:**
- ✅ 모든 시점에서 `df.iloc[i]`, `df.iloc[i-1]`만 참조 — **정상.**
- ✅ `AI_Prob`, `Model_Precision`은 `Add_AI_Signals()`의 Walk-Forward로 생성 — 간접적으로 **정상.**

---

### 6. `kelly.py` (213줄)

**핵심 로직 요약:**
- `Calculate_Half_Kelly()`: 라플라스 정밀도 + AI 확신도 + 동적 손익비 → 투입 비중.
- `Get_Position_Size()`: Satellite 자금 내에서 켈리 비중 → 매수 주수 → 손절가.

**강점:**
- Half-Kelly 적용은 파산 확률을 이론적으로 0에 가깝게 만드는 표준 관행.
- `MAX_WEIGHT_PER_TRADE = 0.20`(20%)로 단일 종목 몰빵 방지.
- 동적 손익비 (`target_profit / stop_risk`)는 고정 비율보다 현실적.
- `confidence_weight` 상한 1.5로 레버리지 폭주 방지.

**결함/리스크:**
- 켈리 공식의 `p`(승률)에 `model_precision`을 직접 대입 — 모델 정밀도는 "양성 예측 중 실제 양성 비율"이지 실제 "이 매매의 승률"이 아님. 실전에서 켈리가 과대 비중을 지시할 위험.
- `AI_TARGET_PCT = 10%`일 때 `target_profit = price × 0.10`, `stop_risk = ATR × 1.5` → IONQ(ATR~$2, 가격~$30) 기준 손익비 ≈ 3.0/3.0 = 1.0. 손익비 1.0에서 정밀도 60%면 켈리 = 0.60 - 0.40/1.0 = 0.20 → Half = 0.10 → Max(0.10, 0.20) = 0.10. **상대적으로 보수적으로 작동하여 실전에서 큰 문제는 없을 것**.

**Lookahead Bias:** 없음 (입력값에 의존, 자체 데이터 참조 없음)

---

### 7. `portfolio.py` (264줄)

**핵심 로직 요약:**
- Macro 모드: SciPy SLSQP로 샤프 최대화 (Mean-Variance Optimization).
- Micro 모드: 역변동성(Inverse Volatility) 배분.
- 몬테카를로 효율적 전선 시각화.

**강점:**
- Macro/Micro 듀얼 모드 설계는 용도에 맞게 적절.
- 데이터 로드 실패 시 균등 비중 폴백 → 런타임 에러 방지.

**결함/리스크:**
- **전형적 in-sample 최적화**: 전체 기간의 수익률/공분산으로 최적 비중 산출 → 미래를 포함한 데이터로 비중 결정. 실전에서는 rolling/expanding window가 필요.
- Micro 모드의 역변동성은 "리스크 균등 배분"이지 "최적 배분"이 아님 — 이는 설계 의도이므로 결함이 아니라 제약 사항.

**Lookahead Bias:**
- ⚠️ **Macro 모드**: 전체 기간 공분산/수익률 사용 → **포트폴리오 백테스트에 사용하면 bias**. 단, 현재 시점의 비중 결정용(forward-looking)이라면 정상.

---

### 8. `optimize.py` (256줄)

**핵심 로직 요약:**
- Layer 1: 지표 산출 파라미터(RSI_PERIOD 등) 포함 전체 20개 탐색 (느림).
- Layer 2: 매매 판단 파라미터만 12개 탐색 (빠름).
- Expectancy Score = `(avg_return × 100) × win_rate × √trade_count`.

**강점:**
- 2-Layer 분리로 속도와 정밀도 트레이드오프 제공.
- 독소 조항(최소 거래수, 최소 승률, 마이너스 수익률 탈락)은 과적합 억제.
- Optuna의 TPE(Tree-structured Parzen Estimator) 활용은 그리드 서치보다 효율적.

**결함/리스크:**
- **과적합 위험**: 200 trial × 12~20 파라미터 → config.TICKERS 2개(APLD, RKLB)에 대해 최적화 → 극소 표본에 과적합될 가능성 매우 높음.
- Layer 1의 `adx_threshold` (L145)를 탐색하면서 L151에서 다시 `0`으로 덮어쓰기 → **버그**. Layer 1에서 ADX 탐색이 무의미.
- Expectancy Score 공식의 `√trade_count`는 거래가 많을수록 보너스 → 과매매를 유도할 수 있음 (독소 조항으로 일부 완화되나 완전하지 않음).

**Lookahead Bias:**
- ✅ 최적화 자체는 전체 기간에 대해 수행되므로 **본질적으로 in-sample 최적화**. 이것 자체가 bias이지만, 파라미터 튜닝의 표준적 한계이며 out-of-sample 검증이 별도 필요.

---

### 9. `trade_journal.py` (745줄)

**핵심 로직 요약:**
- Excel 3시트(매매일지/AI추천로그/월간통계) 기반 실전 기록 시스템.
- CLI로 매수/매도/통계/AI검증 수행. predict.py와 자동 연동.

**강점:**
- **가장 실전적인 모듈**. AI 추천 사후 검증(10일 후 실제 가격 대조)은 포워드 테스팅의 핵심 인프라.
- "놓친 수익(Missed Profit)" 추적은 심리적 피드백 루프로 매우 유용.
- `Acted` 컬럼으로 "AI가 맞았는데 안 산 것" vs "AI가 맞았고 산 것" 구분.
- CLI 인터페이스(`log scan`)로 screener → predict → 기록 원클릭 파이프라인.

**결함/리스크:**
- Excel 파일 동시 접근 시 `PermissionError` → 단일 사용자 환경에서만 안전.
- `update_ai_results()`에서 FinanceDataReader로 개별 종목 데이터를 반복 호출 → 추천 건수가 많으면 느림.

**Lookahead Bias:** 없음 (기록 시스템이므로 해당 없음)

---

### 10. `alert.py` (562줄)

**핵심 로직 요약:**
- trade_journal 보유종목 + 수동 감시종목 대상 실시간 모니터링.
- 손절가 이탈/접근, 익절 구간, 급등/급락 조건 판단.
- 텔레그램 봇 + 콘솔 비프음 알림.

**강점:**
- 2-source 감시(journal 자동 + 수동 추가) 설계는 유연함.
- 중복 알림 방지(cooldown 300~600초) 구현.
- 알림 이력 JSON 저장(최근 500건)으로 감사 추적 가능.

**결함/리스크:**
- `_get_current_prices()`에서 `fdr.DataReader(ticker, start=today)` → 장 마감 후에만 "현재가" 확인 가능. 실시간 장중 모니터링은 불가 (FinanceDataReader는 EOD 데이터).
- 이는 구조적 한계로, 실시간 알림을 위해서는 WebSocket 또는 별도 실시간 API 필요.

**Lookahead Bias:** 없음

---

### 11. `visualize.py` (310줄)

**핵심 로직 요약:**
- 5단 패널(캔들+BB, MACD, RSI, Stoch, ADX) + 국면 배경색 + 매매 마커.
- backtest trade_log 연동 또는 자체 시뮬레이션 지원.

**강점:**
- `_extract_signals()`에서 trade_log 재사용 → backtest와 시각화의 일관성 보장.
- `_apply_regime_background()` 분리로 코드 재사용성 확보.

**결함/리스크:**
- 자체 시뮬레이션 모드에서 `kelly.py` 연동 없이 자체 로직으로 매매 → backtest와 미세한 차이 발생 가능 (이미 trade_log 모드로 해결 가능하므로 큰 문제 아님).

**Lookahead Bias:** 없음 (시각화 전용)

---

## 🎯 전체 시스템 Lookahead Bias 요약

| 모듈 | 판정 | 의심 지점 | 심각도 |
|------|------|-----------|--------|
| ta.py | ✅ PASS | 없음 | — |
| predict.py (Walk-Forward) | ✅ PASS | L378 정상 차단 | — |
| predict.py (Analyze_Full) | ⚠️ MINOR | L163 전체 재학습 | 낮음 |
| screener.py | ⚠️ MINOR | L219 전체 재학습 | 낮음 |
| backtest.py | ✅ PASS | 없음 | — |
| portfolio.py (Macro) | ⚠️ MODERATE | 전체 기간 공분산 | 중간 |
| optimize.py | ⚠️ INHERENT | in-sample 최적화 | 구조적 |

---

## 🏗️ 시스템 전체 아키텍처 평가

### 강점 (살릴 부분)
1. **screener → predict 2단계 파이프라인**: 속도와 정밀도의 균형이 탁월.
2. **Walk-Forward AI 신호 부착**: backtest의 AI 연동이 미래 참조 없이 올바르게 구현됨.
3. **trade_journal.py**: 실전 포워드 테스팅 인프라로서 가치가 매우 높음.
4. **국면별 전략 분리**: Bull/Sideways/Bear 각각의 전략이 논리적으로 일관됨.
5. **다중 방어 계층**: Kelly Half → MAX_WEIGHT 캡 → ATR 손절 → 트레일링 스탑.

### 결함 (검증/수정 필요)
1. **AI_TARGET_PCT = 10%**: 양성 비율이 너무 낮아 모델이 유의미한 신호를 생성하지 못할 가능성.
2. **in-sample 과적합**: optimize.py가 2개 종목에만 최적화 → 범용성 의문.
3. **커스텀 샤프 지수**: 업계 표준과 다른 지표로 v2와 직접 비교 불가.
4. **MDD 미산출**: 전략의 실전 위험도를 측정할 수 없음.

### 구조적 한계 (개선 필요하지만 알고리즘 변경 범위)
1. 단일 포지션 모델 → 복수 종목 동시 보유 불가.
2. FinanceDataReader EOD 한계 → 실시간 모니터링 불가.
3. GMM 롤링 윈도우 속도 → 대규모 유니버스에 부적합 (screener에서 이미 우회).
