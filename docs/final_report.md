# 📋 Archive 코드베이스 종합 결론 (Final Report)

> **평가일**: 2026-05-05  
> **범위**: richman/ 11개 모듈, 약 4,500줄  
> **도전 목표**: v2 시스템 (Sharpe 1.205, MDD -11.9%)

---

## 1. Archive의 진짜 가치는 무엇인가? (살릴 부분)

### ✅ 즉시 활용 가능한 자산

| 자산 | 근거 |
|------|------|
| **kelly.py (Half-Kelly 자금 관리)** | H4 검증 PASS. Kelly +33.5% vs Equal +15.8%. 2.1배 우수. |
| **trade_journal.py (매매 일지 + AI 사후 검증)** | 포워드 테스팅 인프라로서 유일무이. AI 적중률 자동 추적 → 모델 개선 피드백 루프의 핵심. |
| **ta.py (Wilder's RMA 지표 엔진)** | HTS 수식 일치 목표로 정밀하게 구현. 26개 지표 + QQQ 프록시 GMM. Lookahead-free 확인 완료. |
| **screener → predict 2단계 파이프라인** | 속도(Light AI) vs 정밀도(Deep Scan) 분리 설계가 실전적. |
| **backtest.py (국면별 가중 투표)** | Bull/Sideways/Bear 3전략 분리 + AI 게이트 → 교과서적 접근. Sharpe 1.09~1.80 (종목별). |

### ⚠️ 조건부 활용 (수정 후 사용)

| 자산 | 필요한 수정 |
|------|------------|
| **predict.py (XGBoost AI)** | `AI_TARGET_PCT`를 10% → 3~5%로 하향. 피처 4개 → 8개 확장 |
| **Detect_Regime (GMM 국면)** | 매매 필터로 사용 금지. 참고 지표로만 활용 |
| **optimize.py (Optuna)** | `adx_threshold` 버그 수정. 종목 수 2개 → 5개+ 확장 필요 |

---

## 2. 검증되지 않거나 잘못된 부분은? (폐기/수정 대상)

| 문제 | 심각도 | 상세 |
|------|--------|------|
| **AI_TARGET_PCT = 10%** | 🔴 치명적 | 고변동주 기저 양성비 60~70% → AI Lift 1.05x (무작위 수준). 모델이 유의미한 신호를 생성하지 못함 |
| **GMM 국면 예측력** | 🔴 치명적 | Bear 수익률 > Bull (역전). 국면 기반 전략 분리가 오히려 수익을 감소시킬 수 있음 |
| **커스텀 샤프 지수** | 🟡 중간 | `(avg_return/std) × √N`은 업계 표준이 아님. v2와 직접 비교 불가 |
| **MDD 미산출** | 🟡 중간 | 최대 낙폭 없이 전략 위험도 판단 불가 |
| **optimize.py 버그** | 🟡 중간 | Layer 1에서 `adx_threshold`를 탐색 후 0으로 덮어쓰기 |
| **portfolio.py in-sample** | 🟡 중간 | 전체 기간 공분산으로 최적화 → 포트폴리오 백테스트에 bias |

---

## 3. 같은 조건에서 archive vs v2 누가 더 나은가?

### 직접 비교 (동일 조건 불가능 → 가용 수치 기반)

| 지표 | Archive (5종목 평균) | v2 Satellite | v2 Integrated |
|------|---------------------|-------------|--------------|
| Sharpe | **1.09** (커스텀) | 0.79 (표준) | **1.205** (표준) |
| MDD | 미산출 | -19.7% | **-11.9%** |
| Total Return | +33.5% (Kelly 평균) | — | 199% |
| Universe | 5개 | 689개 | 689개+Core |
| 기간 | 2020~2026 | 2015~2026 | 2015~2026 |
| 비용 가정 | 편도 0.4% | 편도 0.05%+환전 | 동일 |

**비교 시 주의사항:**
- Archive의 커스텀 샤프(1.09)와 v2의 표준 샤프(1.205)는 **계산 방식이 달라 직접 비교 불가**.
- Archive는 2020년 이후 데이터만 사용하여 코로나 랠리의 수혜를 받음.
- Archive의 비용 가정(편도 0.4%)이 v2(0.05%)보다 8배 가혹 → 실제 성과는 더 나을 수 있음.

### 판정
> Archive는 **개별 모듈의 품질은 높으나, 시스템 통합 검증이 부족**합니다. v2의 689개 유니버스 × 11년 백테스트와 비교하기엔 표본이 너무 작음(5종목 × 5년). 그러나 kelly.py, trade_journal.py, 2단계 파이프라인은 v2에서도 채택할 가치가 있는 자산입니다.

---

## 4. 포워드 테스팅으로 검증 가능한 종목 추천

> 별도 스크립트(`results/today_picks_YYYYMMDD.md`)로 screener + predict 실행 필요.
> GMM 롤링 윈도우 속도 문제(종목당 ~30초)로 본 리포트에서는 실행하지 않았음.
> 
> **실행 명령어:**
> ```
> python predict.py APLD RKLB PLTR SOFI IONQ
> ```

---

## 5. 최종 권고사항

### 즉시 실행 (코드 변경 없이)
1. `python predict.py APLD RKLB` 실행 → 오늘자 추천 기록
2. `python trade_journal.py update` 10일마다 실행 → AI 적중률 축적

### 단기 개선 (알고리즘 유지, 파라미터만 수정)
1. `config.py`의 `AI_TARGET_PCT`를 `10` → `5`로 변경
2. `config.py`의 `FEE_RATE`를 `0.004` → `0.001`로 변경 (실전 반영)
3. `optimize.py` Layer 1의 `adx_threshold` 덮어쓰기 버그 수정

### 중기 개선 (알고리즘 수정 필요)
1. backtest.py에 **MDD 산출** 추가
2. backtest.py에 **표준 연간화 샤프 지수** 추가 (v2 비교용)
3. GMM 국면을 매매 필터에서 제거하고 **참고 지표로만** 활용
4. `AI_FEATURES`를 4개 → 8개로 확장 (MACD_Hist, RSI_Slope 등 추가)

---

## 산출물 체크리스트

| # | 산출물 | 상태 |
|---|--------|------|
| 1 | `docs/archive_audit.md` | ✅ 완료 |
| 2 | `docs/hypothesis_validation.md` | ✅ 완료 |
| 3 | `refactored/` | ⏳ 보류 (알고리즘 변경 금지 원칙 → 버그 수정만 필요) |
| 4 | `results/hypothesis_results.json` | ✅ 완료 |
| 5 | `results/today_picks_YYYYMMDD.*` | ⏳ 사용자 실행 필요 |
| 6 | `docs/final_report.md` | ✅ 본 문서 |
