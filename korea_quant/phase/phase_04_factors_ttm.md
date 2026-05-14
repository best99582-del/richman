# Phase 4 — 16개 팩터 확장 + TTM 기간 기준 도입

## 목표

기존 활성 팩터 7개를 16개로 확장. 사용자가 원한 팩터 전부 구현 가능하게.
각 팩터의 기간 기준(TTM / 분기말 / 분기 YoY)을 명확히 정립.

## 배경 / 문제 인식

이전 활성 팩터: PSR, POR, PBR, SALES_GROWTH, OP_GROWTH, ROE, RSI (7개).
사용자 요청 추가 팩터:
- 원시값: 매출액, 영업이익, 당기순이익
- 배수: PER, PCR, PGPR (기존 외 추가)
- 성장률: 순이익성장률, 매출총이익성장률
- 수익성: ROA, 영업이익률

→ 총 16개로 확장.

또한 같은 PER이라도 분자(시총)와 분모(순이익)의 기간을 어떻게 잡느냐에 따라
결과가 크게 달라짐. 명확한 기준 합의 필요.

## 결정 사항 (사용자와 1:1 합의)

### 기간 기준 매트릭스

| 팩터 | 명칭 | 분자 | 분모 |
|---|---|---|---|
| PER | PER_TTM | 시가총액 | TTM 순이익 |
| PBR | PBR_Q | 시가총액 | 분기말 자기자본 |
| PSR | PSR_TTM | 시가총액 | TTM 매출액 |
| POR | POR_TTM | 시가총액 | TTM 영업이익 |
| PCR | PCR_TTM | 시가총액 | TTM 영업현금흐름 |
| PGPR | PGPR_TTM | 시가총액 | TTM 매출총이익 |
| 매출성장률 | SALES_GROWTH_Q | (당기 분기누적 - 전년 동기) / \|전년 동기\| | 분기 YoY |
| 매출총이익성장률 | GP_GROWTH_Q | 동일 형태 | 분기 YoY |
| 영업이익성장률 | OP_GROWTH_Q | 동일 형태 | 분기 YoY |
| 순이익성장률 | NET_GROWTH_Q | 동일 형태 | 분기 YoY |
| ROE | ROE_Q | TTM 순이익 | 분기말 자기자본 |
| ROA | ROA_Q | TTM 순이익 | 분기말 총자산 |
| 영업이익률 | OP_MARGIN_TTM | TTM 영업이익 | TTM 매출액 |
| 매출액 (원시값) | SALES_TTM | TTM | - |
| 영업이익 (원시값) | OP_PROFIT_TTM | TTM | - |
| 당기순이익 (원시값) | NET_PROFIT_TTM | TTM | - |

### 적자/음수 처리
사용자 선택: 그대로 계산해서 반환. 필터링은 ENTRY_CONDITIONS에서 직접.

### EV/EBIT vs POR_TTM
사용자와 논의 후 POR_TTM 유지. 한국 IFRS에서 영업이익 ≈ EBIT이고,
EV/EBIT은 순부채(차입금-현금) 추가 수집 필요한데 커버리지 떨어짐.

## 수정 파일

- `configs/config.py`:
  - FACTORS 딕셔너리 전면 갱신 (새 명명 규칙 반영)
  - 활성 7개 + 비활성 10개 (주석으로 남김)
- `factors/fundamental.py`:
  - 전면 재작성. 16개 팩터 클래스 + `_ratio()` / `_yoy()` 유틸
  - `ALL_FUNDAMENTAL_FACTORS` 레지스트리 갱신
- `data/data_loader.py`:
  - `finstate()` → `finstate_all()` 전환 (CF, 매출원가, 매출총이익 회수)
  - 손익계산서(IS) + 포괄손익계산서(CIS) 둘 다 처리
  - `get_financial_summary()`에서 TTM 직접 추출 (`thstrm_add_amount` 필드)
- `universe/universe.py`:
  - `_add_financials()` 단일 트랙으로 단순화 (DART가 TTM 직접 제공하므로 역산 불필요)
  - CF만 별도 TTM 역산 (DART CF는 `thstrm_add_amount` 미제공)
- `scoring/scorer.py`:
  - 그룹 합산 컬럼명 갱신 (VALUE_FACTORS, GROWTH_FACTORS 등)

## 해결한 기술 이슈

### 이슈 1 — finstate() 데이터 부족
- 증상: `finstate()`는 IS/BS 핵심 5개 계정만 반환. CF, 매출원가, 매출총이익 누락.
- 해결: `finstate_all()`로 전환. 전체 계정 (IS, BS, CF, CIS, SCE 포함) 수집.

### 이슈 2 — 분기 보고서 필드 매핑
- 증상: `finstate_all()`에서 `frmtrm_amount`가 NaN으로 옴.
- 원인: 분기 보고서는 `frmtrm_amount` 대신 `frmtrm_q_amount`에 전년 동기 누적 저장.
- 해결: 분기 보고서 분기인지 판별하여 `frmtrm_q_amount` 사용.

### 이슈 3 — TTM 직접 취득
- 발견: DART가 `thstrm_add_amount` 필드로 IS 계열 TTM을 이미 계산해서 제공.
- 효과: 별도 연간 보고서 추가 호출하여 역산할 필요 없음.
  단, CF는 `thstrm_add_amount` 미제공 → 직접 역산 (전년 연간 + 분기 누적 - 전년 동기 누적).

### 이슈 4 — CIS 미처리로 IS 수집률 5%
- 증상: 1,729 종목 중 sales 수집 94개 (5%).
- 원인: IFRS 기업 다수가 IS 대신 포괄손익계산서(CIS)만 공시.
  `sj_div == 'IS'` 필터에서 CIS 행이 모두 제외됨.
- 해결: `sj_div in ('IS', 'CIS')` 로 변경. 수집률 5% → 90%.

### 이슈 5 — operating_cf_prev 컬럼 누락
- 증상: CF TTM 역산 결과 전부 NaN.
- 원인: universe.py의 `fin_cols` 리스트에 `operating_cf_prev` 항목 누락 → join에서 빠짐.
- 해결: 컬럼 목록에 추가. operating_cf_ttm 수집률 0 → 88%.

### 이슈 6 — 공시 시차 보정
- 증상: 2026년 5월 기준 자동 계산이 `fin_year=2026, fin_quarter=1`로 잡혔는데
  1분기 보고서는 5월 15일 마감 직후라 데이터 부족.
- 해결: 마감 + 1.5개월 여유 두고 직전 분기로 폴백:
  - 1~5월 → 직전 연도 3Q
  - 6월 → 직전 연도 연간
  - 7~8월 → 당해 1Q
  - 9~11월 → 당해 반기
  - 12월 → 당해 3Q

## 검증 결과

### 단위 테스트 (가짜 데이터)
16개 팩터 전부 정상 계산 (PER 12.5배, PBR 3.33배, ROE 26.7% 등 산술 검증 통과).

### 실데이터 수집률 (KRX 1,729 종목)

| 컬럼 | 수집률 |
|---|---|
| sales (분기누적) | 1551 / 1729 (89.7%) |
| op_profit | 1632 / 1729 (94.4%) |
| net_profit | 1482 / 1729 (85.7%) |
| gross_profit | 1492 / 1729 (86.3%) |
| operating_cf | 1572 / 1729 (91.0%) |
| equity | 1650 / 1729 (95.4%) |
| total_assets | 1654 / 1729 (95.7%) |
| sales_ttm | 1553 / 1729 (89.8%) |
| op_profit_ttm | 1632 / 1729 (94.4%) |
| net_profit_ttm | 1482 / 1729 (85.7%) |
| operating_cf_ttm | 1521 / 1729 (87.9%) |

### 스크리너 실행
TOP 20 종목 정상 산출. CSV 저장 확인.
6개 활성 팩터 (RSI 제외, --no-tech 옵션) 가중치 합계 0.90.

## 남은 한계

- DART 수집 실패 종목 ~6%는 외국 상장사 / SPAC / 신규 상장 (당기 자료 없음). 본질적 한계.
- 비활성 10개 팩터는 코드 준비 완료, 활성화는 사용자 판단.
- PER, PCR, PGPR 등 TTM 배수는 음수 분모 시 NaN 처리. 적자 종목 필터는 ENTRY_CONDITIONS에서 직접 설정 필요.
- 데이터 캐시 정책: raw 캐시(개별 종목) + batch 캐시 + universe 캐시 3단. 분기 바뀌면 batch + universe 캐시만 삭제하면 됨.
