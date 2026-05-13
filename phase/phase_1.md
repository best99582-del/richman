# Phase 1: yfinance 시총 캐싱 시스템 구축

## 목적

`fdr.StockListing`이 MarketCap을 제공하지 않으므로 yfinance의 `fast_info`로 시총을 조회하고, 일주일 단위로 캐싱하여 재사용.

## 설계

### 신규 파일: [market_cap_cache.py](../market_cap_cache.py)

**책임:**
- yfinance fast_info로 종목 리스트의 시총 일괄 조회
- 결과를 JSON 파일에 캐싱
- 캐시 신선도 검사 (1주일 이내면 재사용)

### 캐시 파일: [market_cap_cache.json](../market_cap_cache.json) (신규)

**구조:**
```json
{
  "updated_at": "2026-05-13T10:00:00",
  "data": {
    "IONQ": 20850000000,
    "PLTR": 326030000000,
    ...
  }
}
```

### 공개 함수

| 함수 | 역할 |
|---|---|
| `get_market_caps(tickers, force_refresh=False) -> dict[str, float]` | 메인 진입점. 캐시 신선하면 캐시 반환, 아니면 yfinance 조회 후 캐시 저장 |
| `_is_fresh(cache_path, days=7) -> bool` | 캐시 파일 mtime 기준 신선도 |
| `_fetch_market_caps(tickers) -> dict` | yfinance 일괄 조회 (진행상황 출력) |
| `_load_cache(path) -> dict` | JSON 로드 |
| `_save_cache(path, data) -> None` | JSON 저장 |

### config.py 추가 상수

```python
MARKET_CAP_CACHE_PATH = 'market_cap_cache.json'
MARKET_CAP_CACHE_DAYS = 7  # 캐시 유효기간 (일)
```

## 구현 결정사항

| 결정 | 선택 | 사유 |
|---|---|---|
| 캐시 위치 | 프로젝트 루트 (`market_cap_cache.json`) | trade_journal.xlsx와 동일 위치 |
| 캐시 형식 | JSON | 가독성, 디버깅 편의 |
| 갱신 단위 | 7일 (mtime 기준) | 사용자 지정 |
| 실패 처리 | 종목 단위 try/except, None은 캐시에서 제외 | 일부 실패해도 전체 중단 안 함 |
| 강제 갱신 옵션 | `force_refresh=True` 인자 | 디버깅/수동 갱신용 |
| 진행률 표시 | 100개마다 print | 30~40분 작업이라 진행 가시화 필요 |
| 부분 갱신 | **하지 않음** (전체 일괄) | 매주 한 번이라 단순화 우선 |

## 1단계는 screener.py를 건드리지 않음

이 단계는 **헬퍼 모듈만 신규 생성**. screener.py 통합은 phase 2에서.

## 검증 방법

1. **단위 동작**: 샘플 5개 종목 직접 조회 → 캐시 저장 → 두 번째 호출은 캐시 사용
2. **신선도 검사**: 캐시 파일 mtime을 8일 전으로 조작 → 강제 재조회 트리거 확인
3. **부분 실패**: 존재하지 않는 티커 포함 시 정상 종목만 캐시되는지

## 예상 시간

- 코드 작성: 즉시
- 캐시 1회 빌드: NASDAQ 3,877 + NYSE 2,755 ≈ 6,600 종목 × 0.6초 = **약 60~70분**
- → 사용자가 별도로 빌드 명령 돌리는 게 효율적 (작성 완료 후 사용자 판단)

## 상태

- [x] phase_1.md 작성
- [x] market_cap_cache.py 구현 (5함수 + 단독실행 모드)
- [x] config.py 상수 추가 (MARKET_CAP_CACHE_PATH, MARKET_CAP_CACHE_DAYS)
- [x] 샘플 5개로 단위 동작 검증 ([TEST 1] 통과)
- [x] 캐시 재사용 검증 ([TEST 2] 통과)
- [x] 캐시 병합 보존 검증 ([TEST 3] 통과 — 기존 5개 + 신규 1개 = 6개)
- [x] 신선도 검사 검증 (8일 전 타임스탬프 → 만료 판정 정상)
- [ ] 1차 NASDAQ+NYSE 전체 캐시 빌드 — **사용자 판단으로 별도 실행 (약 60~70분)**

## 구현 후 추가 발견사항

### 부분 누락 시 병합 처리 (Edit로 보강)

초기 구현은 누락 종목이 있으면 **전체 요청 티커만 재조회 → 기존 캐시 폐기** 버그가 있었음.
수정 후: `_is_fresh(7) == True && 일부 누락`이면 **누락분만 추가 조회해서 기존 캐시와 병합**.

### force_refresh=True의 한계 (안내사항)

`force_refresh=True`로 부분 티커만 호출하면 캐시가 그 티커들로 축소됨.
실전에서는 phase 2의 `get_universe()`가 항상 전체 종목 리스트로 호출하므로 문제 없음.
사용자 단독 실행 시(`python market_cap_cache.py IONQ`) 캐시가 IONQ만 남게 됨 — 의도된 동작.

## 검증 결과 요약

| TEST | 시나리오 | 결과 |
|---|---|---|
| 1 | 최초 조회 (5개) | yfinance 호출 → 캐시 생성 ✅ |
| 2 | 동일 5개 재호출 | 캐시 사용 (yfinance 호출 안 함) ✅ |
| 3 | 기존 5개 + 신규 1개 | 누락분 1개만 yfinance → 캐시 6개로 병합 ✅ |
| 4 | 신선도 만료 (8일 전) | `_is_fresh()` False → 재조회 트리거 ✅ |

샘플 시총 결과:
- IONQ: $20.85B
- PLTR: $326.03B
- AAPL: $4329.83B
- APLD: $12.55B
- RKLB: $68.04B
- NVDA: $5366.06B

## 1차 캐시 빌드 안내

사용자가 별도로 실행:
```powershell
python market_cap_cache.py
```
- NASDAQ 3,877 + NYSE 2,755 → 중복 제거 후 약 6,500 종목
- 종목당 약 0.6초 → **예상 소요 60~70분**
- 백그라운드 실행 권장
- 빌드 완료 시 `market_cap_cache.json` 생성됨
