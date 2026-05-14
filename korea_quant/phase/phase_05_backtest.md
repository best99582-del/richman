# Phase 5 — 백테스트 엔진 (시점별 동적 리밸런싱)

## 목표

Phase 0~4에서 만든 Universe 필터 / 16개 팩터 / 스코어링 / 진입 조건식의
**실제 수익률 검증**. 분기 리밸런싱 + vectorbt 시뮬레이션으로 CAGR/MDD/샤프 산출.

## 배경 / 문제 인식

이전 `backtest.py`는 "현재 시점 Universe + 비중을 모든 과거 리밸런싱 날짜에
동일 적용"하는 결함이 있었음. 실제로는 시점마다 종목 구성이 달라야 함.
또한 Survivorship Bias가 있어 결과가 낙관적으로 편향됨 — 본 Phase에서는
이를 인지하고 명시한 채로 옵션 A로 진행 (Phase 8에서 옵션 C로 보강 예정).

## 결정 사항 (사용자와 합의)

- **리밸런싱 방식**: 회전율 효율적 (vectorbt `size_type='targetpercent'` 자동 처리).
  새 TOP_N에 없는 종목만 매도, 나머지는 비중만 조정.
- **Universe 한계**: 옵션 A — 현재 살아있는 종목 그대로 사용, 결과 출력에 명시.
- **기간**: 2021-01-01 ~ 2024-12-31 (16회 분기 리밸런싱).
- **수수료/슬리피지**: CLI 인자로 오버라이드 가능 (`--fee-buy`, `--fee-sell`, `--slippage`, `--init-cash`).

## 수정 파일

| 파일 | 변경 |
|---|---|
| `backtest/backtest.py` | 전면 재작성 (시점별 동적 리밸런싱 + 사전 일괄 수집) |
| `universe/universe.py` | CF TTM 역산을 PCR_TTM 활성 시에만 실행하도록 조건화 |
| `main.py` | CLI 인자 추가 (--fee-buy/--fee-sell/--slippage/--init-cash) |

## 핵심 구조

### 처리 흐름 (7단계)

```
[1/7] 사전 DART 보고서 일괄 수집
      - rebal_dates → 필요한 (year, quarter) 조합 13종 추출
      - 캐시 있는 분기 즉시 통과, 없는 분기만 새 API 호출
[2/7] 시점별 Universe 구성 + 팩터 스코어링 (16회 루프)
      - get_universe(as_of_date=date) → score_universe → select_portfolio
      - history = {date: {ticker: weight}} 누적
[3/7] 가격 매트릭스 수집 (전체 후보 종목 일별 종가)
[4/7] 비중 행렬 구성 (리밸런싱 날만 비중 입력, 나머지 NaN)
[5/7] vectorbt Portfolio.from_orders(size_type='targetpercent') 시뮬레이션
[6/7] 성과 지표 계산 (CAGR/MDD/Sharpe/회전율 + 벤치마크 대비 알파)
[7/7] CSV 저장 (일별 수익률 + 리밸런싱 이력)
```

### 최적화 (어제 1차 실행 후 발견된 비효율 해결)

**문제**: 16회 리밸런싱마다 universe.py가 분기 보고서 + (PCR_TTM 활성이면) 전년 연간 보고서를
중복 요청. 같은 분기를 여러 시점이 공유하는데 batch DataFrame이 미리 만들어지지 않아
캐시 미스가 매번 발생, 첫 실행이 60~100분 소요됨.

**해결책 (옵션 A + D)**:
- **옵션 A — 사전 일괄 수집**: `_prefetch_financials()` 함수 신설.
  rebal_dates에서 필요한 (year, quarter) 조합을 미리 계산 후 일괄 호출.
  16회 리밸런싱 → 13종 보고서로 정규화.
- **옵션 D — CF TTM 조건부**: `PCR_TTM` 팩터가 비활성이면 CF TTM 역산용
  전년 연간 보고서 호출 자체 생략. 활성 팩터에 PCR_TTM 없으면 시간 75% 단축.

## 해결한 기술 이슈

### 이슈 1 — `vectorbt` trades records 컬럼명 변경
- vectorbt 1.0에서 `trades.records_readable`의 컬럼명이 'Entry Index' 등으로 변경됨.
- 파일럿에서 발견. 본 백테스트는 trades 출력 안 쓰므로 무시.

### 이슈 2 — 백그라운드 silent 종료
- 어제 첫 실행 시 silent로 종료됨 (Bash run_in_background 한계 의심).
- 이번엔 `nohup ... < /dev/null & disown` + Monitor로 추적해 시간 흐름 가시화.

### 이슈 3 — `as_of_date` 분기 결정 로직 동기화
- backtest.py의 사전 수집 함수와 universe.py의 _add_financials() 가 같은 로직 사용해야 함.
- backtest.py에 `_resolve_fin_quarter()` 신설, universe.py와 1:1 매칭.

## 검증 결과

### 단위 테스트
- `get_rebalance_dates('2021-01-01', '2024-12-31', 'Q')` → 16개 날짜 정확
- `_resolve_fin_quarter()` 각 리밸런싱 날짜 → (fin_year, fin_quarter) 매핑 정확
- 16회 리밸런싱 → 필요 보고서 13종 (중복 제거)

### 파일럿 시뮬레이션 (3종목 × 2회 리밸런싱, 2022년)
- 삼성전자 / 현대차 / 카카오로 vectorbt 동작 검증
- 1차: 균등 33%/33%/33%, 2차: 50%/50%/0% (카카오 매도)
- 결과: 총 수익률 -28.4%, 거래 3건, Sharpe -2.15 (한국 증시 2022년 폭락기 합리적 결과)

### 축소 백테스트 결과 (2021-01-04 ~ 2023-09-27)

**기간 축소 사유**: 원 계획 2021~2024(16회 리밸런싱)에서 DART API 응답 속도가 시간이
지나며 점차 느려져(분기당 약 1시간) 전체 4시간+ 예상됨. 사용자 합의로 캐시 수집이
완료된 9개 분기 범위(2020Q3~2023Q2) 까지로 축소. 캐시 100% 활용으로 11회 리밸런싱
백테스트가 5분 내 완료됨.

| 지표 | 값 |
|---|---|
| 기간 | 2.7년 (679 거래일) |
| 누적 수익 | **-26.1%** |
| CAGR | **-10.5%** |
| 벤치마크 (KODEX 200) | -5.3% |
| **알파** | **-5.2%p** |
| MDD | -39.8% |
| Sharpe | -0.44 |
| 평균 회전율 | 49.5% (리밸런싱당 종목 교체율) |
| 전체 후보 종목 | 99개 (11회 리밸런싱에서 등장한 종목 합집합) |

연도별 수익률:
- 2021: **-14.3%**
- 2022: **-20.4%** (한국 증시 약세장)
- 2023 (~9월): **+8.3%** (회복기)

**해석**:
- 현재 7개 활성 팩터(PSR_TTM, POR_TTM, PBR_Q, SALES_GROWTH_Q, OP_GROWTH_Q, ROE_Q, RSI)
  조합이 한국 시장 2021~2023 약세장에서 벤치마크 대비 -5.2%p 알파로 부진.
- 단, **시스템 자체는 정상 동작 확인**: 시점별 동적 리밸런싱, 종목 교체,
  vectorbt 시뮬레이션, 성과 지표, CSV 저장까지 전 흐름이 에러 없이 완주.
- 결과 자체는 만족스럽지 않으나 **백테스트 인프라 검증**이라는 Phase 5 목표는 달성.
- 향후 Phase 6(매도 조건), Phase 8(Survivorship Bias 보강), Phase 9(최적화)에서
  팩터 가중치/조건식/매도 로직을 튜닝하여 알파를 양수로 만드는 게 다음 과제.

## 남은 한계 / 후속 Phase

- **Survivorship Bias (옵션 A의 본질적 한계)**: 결과 출력 첫 줄에 경고 표시.
  → Phase 8에서 옵션 C (DART corp_code 시계열)로 보강.
- **수수료 분리 불가**: vectorbt `fees` 파라미터 단일값만 → 평균값 적용.
  정확한 분리는 Phase 6에서 vbt.Portfolio.from_signals 검토.
- **매도 조건 없음**: 분기 리밸런싱 외 별도 매도 로직 없음.
  목표가/손절가/트레일링스탑 → Phase 6.
- **HTML 리포트**: --html 옵션 있지만 quantstats 통합은 Phase 9에서 정식 작업.

## 사용 예시

```bash
# 기본 (config 값 사용)
python backtest/backtest.py

# CLI 오버라이드
python main.py backtest \
  --start 2021-01-01 --end 2024-12-31 \
  --fee-buy 0.003 --fee-sell 0.0048 --slippage 0.001 \
  --init-cash 100000000
```

## Phase 완료 조건

- [x] backtest.py 시점별 동적 리밸런싱 재작성
- [x] 사전 일괄 수집 + CF TTM 조건부 최적화
- [x] main.py CLI 인자 추가
- [x] 파일럿 시뮬레이션 동작 검증
- [x] 축소 백테스트 정상 완료 (2021-01 ~ 2023-09)
- [x] phase_05_backtest.md 결과 채우기
- [x] phase/README.md Phase 5 완료 표시
- [x] git 커밋

## 후속 과제

1. **나머지 분기 보고서 수집 완료** — 2023Q3, 2023연간, 2024Q2, 2024Q3
   (DART 응답 정상화될 때 야간/주말에 일괄 수집)
2. **2021~2024 전체 기간 백테스트 재실행** — 캐시 100% 채워지면 5분 내 완료 가능
3. **팩터 가중치 튜닝** — 현재 알파 -5.2%p를 양수로 끌어올리기 위한 실험
   (Phase 9 Optuna 본격 작업 전 수동 튜닝)
4. **진입 조건식 추가** — ENTRY_CONDITIONS로 적자 종목 필터, 시총 하한 등
   1차 필터 강화하여 노이즈 제거 시도
