# Phase: Screener 종목 분류 정보 표시 (시총/거래소/섹터)

## Context

사용자 요청: "screener로 뽑은 종목에 대해서 이게 소형주, 중형주? 아니면 뭐 나스닥? snp? 어디에 속하는 지도 떴으면 좋겠어"

v10.2까지 screener는 종목명/AI확률/정밀도/기술지표만 출력. 종목이 어떤 그룹(시총 규모, 거래소, 섹터)에 속하는지는 표시 안 됨 → 추가.

## 구현

### 1. 데이터 소스 — 새 호출 거의 없이 해결

| 분류 | 소스 | 추가 비용 |
|---|---|---|
| 시총 규모 | 기존 `market_cap_cache`의 `mc` 값 | 무료 (이미 있음) |
| 거래소 | yfinance screener API 응답의 `exchange` 필드 | 무료 (이미 옴, 파싱만 추가) |
| 섹터 | yfinance `Ticker.info`의 `sector` | 종목별 1회 호출, 30일 캐시 |

### 2. 신규 파일: [sector_cache.py](../sector_cache.py)

`market_cap_cache.py`와 동일한 패턴:
- JSON 파일 캐시 (`sector_cache.json`)
- 종목별 `fetched_at` 타임스탬프로 만료 판단
- 만료/누락 종목만 yfinance 호출 (캐시 적중분은 즉시 반환)

### 3. config.py — 캐시 설정 추가

```python
SECTOR_CACHE_PATH = 'sector_cache.json'
SECTOR_CACHE_DAYS = 30   # 섹터는 거의 안 바뀜
```

### 4. market_cap_cache.py — exchange 필드 추가

screener API 응답의 `exchange` 코드를 친화적 이름으로 변환:
- `NMS` / `NGM` / `NCM` → `NASDAQ`
- `NYQ` → `NYSE`
- 그 외 → 원본 코드

### 5. screener.py 변경

- `classify_cap(mc)` 헬퍼: `Small (<$2B) / Mid ($2~10B) / Large ($10B+)`
- `get_universe()` 반환: `list` → `(list, screener_meta)` 튜플 (메타 함께 반환)
- `_quick_analyze(ticker, df, meta=None)` 시그니처 확장 — meta로 Cap_Class/Exchange/Sector 부착
- `ai_scanner(candidates_data, screener_meta=None)` — 시작 시 `get_sectors()` 일괄 호출 + 종목별 meta 합쳐서 `_quick_analyze`에 전달
- 대시보드: 종목 라인 아래 `🏷️ NASDAQ · Mid-cap ($5.2B) · Technology` 출력

## 분류 기준

```python
def classify_cap(market_cap_usd):
    if market_cap_usd < 2e9:    return "Small"   # < $2B
    elif market_cap_usd < 10e9: return "Mid"     # $2B~$10B
    else:                       return "Large"   # $10B+
```

S&P/MSCI 통상 기준. screener 시총 범위 $1B~$20B 안에서 Small/Mid/Large가 모두 잡힘.

## 검증 (캐시 갱신 후)

| Ticker | Exchange | Cap_Class | 시총 | Sector |
|---|---|---|---|---|
| IONQ | **NYSE** | Large-cap | $21.5B | Technology |
| APLD | **NASDAQ** | Large-cap | $13.3B | Technology |
| RKLB | **NASDAQ** | Large-cap | $76.7B | Industrials |

3종목 모두 분류 정보 정상 부착. 다만 RKLB는 $76.7B로 시총 상한 ($20B)을 크게 초과 — 시장 변동으로 인한 자연 결과. 다음 screener 실행 시 universe 필터에서 제외됨.

## 산출물

- 신규: [sector_cache.py](../sector_cache.py)
- 신규: [data/sector_cache.json](../sector_cache.json) (자동 생성)
- 수정: [config.py](../config.py) — SECTOR_CACHE_PATH/DAYS
- 수정: [market_cap_cache.py](../market_cap_cache.py) — exchange 필드 파싱
- 수정: [screener.py](../screener.py) — classify_cap 추가, get_universe 튜플 반환, _quick_analyze/ai_scanner 메타 인자, 대시보드 분류 라벨

## 다음 작업 후보

1. **PLTR/SOFI 진단** — v10.2에서도 게이트 미통과 종목 분석
2. **backtest 전체 재실행** — v10.2 새 운용값으로 5종목 수익률 측정
3. **스케줄러 자동화** — 매일 screener+alert 자동 실행
4. **자동매매 Phase A** — 잔고/현재가 API 읽기 전용 연동
