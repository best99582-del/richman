# Phase 2: get_universe() 개편

## 목적

`get_nasdaq_universe()`를 개편하여 **NASDAQ + NYSE 통합 + 금융/리츠/펀드 제외 + 시총 캐시 활용** 유니버스를 반환.

## 설계 결정사항

### 거래소
NASDAQ (3,877개) + NYSE (2,755개) → 중복 제거 약 6,500개

### 제외 Industry 키워드 (사용자 확정)

| 키워드 | 매칭 종목 수 | 사유 |
|---|---|---|
| 은행 | 515 | 금리 외부변수 강함 |
| 보험 | 168 | 보험사 특수 동학 |
| REIT | 354 | 배당주 성격, 모멘텀 적음 |
| 폐쇄형 펀드 | 394 | 펀드는 분석 대상 아님 |
| 투자 지주 | 603 | SPAC/지주회사 제외 |
| 투자 관리 | 119 | 자산운용사 |
| 투자 은행 | 64 | IB |
| 신탁 | 1 | |

**중복 제거 후 약 2,200개 제외 → 약 4,400개 유지**

### 제외하지 않는 것 (사용자 결정)

| 항목 | 사유 |
|---|---|
| 블록체인 (APLD, IREN, COIN 포함) | APLD는 현재 코어 종목 |
| ADR (ASML, ARM 등 385개) | 미국 정규장 거래, 시총/거래대금 필터가 소형 ADR 걸러냄 |
| 대출 (SOFI 포함) | SOFI는 핀테크 분류이지 전통 금융 아님 |

### 종목 코드 정규화

- 알파벳만 (`[^A-Z]` 제외) — `BRK.B` 같은 도트 종목 제외 (yfinance/yfinance 호환성)
- ETF는 fdr에서 별도 분리되어 있어 자연 미포함 (확인 필요)

### 시총 필터링

1. `market_cap_cache.get_market_caps(전체 티커)` 호출
2. **캐시가 없는 종목은 통과**(보수적 — 모르는 종목 일단 포함) ← 또는 제외(엄격)
3. **$1B ~ $20B 범위만 통과** (phase 3에서 config로 빠짐 — 일단 v9 기존 값 유지)

→ 사용자 결정: **캐시에 없는 종목은 일단 제외** (시총 모르는 종목 매매 위험)

## 함수 시그니처 변경

```python
# Before
def get_nasdaq_universe(top_n: int = None) -> list: ...

# After
def get_universe(force_refresh: bool = False) -> list:
    """
    NASDAQ + NYSE 통합 유니버스. 시총 필터 + 업종 제외 적용.
    force_refresh=True면 시총 캐시 강제 갱신.
    """
```

**Breaking change**: 함수 이름 변경. 호출처(`screener.py:439`, `trade_journal.py log scan`)도 같이 수정.

## config.py 추가 (phase 3에서 미세조정 예정)

```python
# 업종 제외 키워드 (Industry 컬럼 기준 부분 일치)
SCREENER_EXCLUDE_INDUSTRIES = [
    '은행', '보험', 'REIT', '폐쇄형 펀드',
    '투자 지주', '투자 관리', '투자 은행', '신탁',
]

# 사용 거래소 (FinanceDataReader StockListing 인자)
SCREENER_EXCHANGES = ['NASDAQ', 'NYSE']
```

## 수정 파일

### screener.py
- `get_nasdaq_universe` → `get_universe`로 함수명 변경
- 함수 시그니처/로직 전면 재작성
- 캐시 호출 통합
- 호출처 `if __name__ == "__main__"` 블록 (라인 439) 업데이트

### config.py
- `SCREENER_EXCLUDE_INDUSTRIES` 신규
- `SCREENER_EXCHANGES` 신규
- (기존 `SCREENER_TOP_N`은 더 이상 의미 없음 — phase 3에서 제거)

### trade_journal.py
- `from screener import get_nasdaq_universe` 호출 — grep 후 확인 필요

### 기타 검증
- 함수명 변경으로 인한 import 깨짐 grep

## 검증 방법

1. **단위 호출**: `get_universe()` 실행 → 통과 종목 수 출력
   - 예상: 시총 $1B~$20B 통과 약 800~1500개 (실제 데이터 의존)
2. **TICKERS 호환**: IONQ, PLTR, APLD, RKLB, SOFI, IREN이 통과하는지 확인
3. **제외 검증**: 은행주 샘플(JPM, BAC 등)이 결과에 없는지 확인
4. **연동 검증**: `screener.py` 단독 실행이 정상 작동하는지 확인

## 백업

작업 전 백업:
- `screener.py` → `screener_backup.py`
- `config.py` → `config_backup.py` (이미 phase 1에서 생성됨, 덮어쓰지 않음)

## 상태

- [x] phase_2.md 작성
- [x] screener.py 백업 (`screener_backup.py`)
- [x] `get_universe()` 작성 ([screener.py:143](../screener.py#L143))
- [x] config.py 상수 추가 (`SCREENER_EXCHANGES`, `SCREENER_EXCLUDE_INDUSTRIES`)
- [x] screener.py 단독 실행부 업데이트 (`__main__`의 함수 호출 변경)
- [x] trade_journal.py 호출처 업데이트 (`from screener import get_universe`)
- [x] import 깨짐 grep 점검 — 코드 외 docs/backup만 잔존
- [x] import 스모크 테스트 통과
- [ ] 단위 검증 — **캐시 빌드 완료 대기 중** (예상 ~53분 남음)
- [ ] TICKERS 호환 확인 — 캐시 완료 후

## 캐시 빌드 진행

- 시작: phase 1 완료 직후
- 대상: NASDAQ 3,877 + NYSE 2,755 → 중복 제거 6,157개
- 진행률 확인 시점: 11% (700/6157, 경과 411초)
- 평균 종목당 0.59초 → 총 예상 시간 약 60분
- 실패율 약 10% (delisted, ETF 등)

## 보조 함수 추가

`get_universe()` 외에 내부 헬퍼 2개 추가:
- `_fetch_exchange_listing(exchange)`: fdr 호출 + 알파벳 정규화 + Exchange 컬럼 부착
- `_exclude_industries(df, keywords)`: Industry 부분 일치로 제외 (regex `|` 패턴)

## 의존성

**캐시 빌드(phase 1 마무리)가 완료되어야 검증 가능.** 코드 작성은 병렬 진행, 검증만 대기.