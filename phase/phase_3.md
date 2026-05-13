# Phase 3: 필터 임계값 조정 + 거래대금 필터 추가

## 목적

사용자 확정 임계값을 config.py에 반영하고, `filter_hot_stocks`에 **거래대금 필터**를 추가.

## 임계값 변경 (사용자 확정)

| 상수 | 기존 | 변경 후 | 사유 |
|---|---|---|---|
| `SCREENER_MIN_MARKET_CAP` | $3B | **$1B** | 중소형주 외연 확대 (단, $500M 안 갈 정도로는 보수적) |
| `SCREENER_MAX_MARKET_CAP` | $50B | **$20B** | $20B 초과 대형주는 +10% 급등 드묾 |
| `SCREENER_MAX_VOLATILITY` | 10% | **12%** | 변동성 기회 확대 (단, 15% 가지 않음 — 손절폭 폭발 위험) |
| `SCREENER_MIN_VOLATILITY` | 3% | **3%** (유지) | |
| `SCREENER_MIN_PRICE` | $5 | **$5** (유지) | |
| `SCREENER_MIN_DATA_DAYS` | 250 | **250** (유지) | |
| **신규** `SCREENER_MIN_TURNOVER` | — | **$20M** | 거래량 대신 거래대금($) 기준 — 절대 유동성 |
| `SCREENER_MIN_VOLUME` | 2M주 | **제거 또는 보조** | 거래대금이 더 정확 (가격×수량) |
| `SCREENER_TOP_N` | 500 | **제거** | 더 이상 사용 안 됨 (phase 2에서 무력화) |

## 거래대금 vs 거래량 — 왜 바꾸나

| 시나리오 | 거래량 1M주 | 거래대금 $20M |
|---|---|---|
| $5 주식 | 통과 ($5M 대금) | 차단 |
| $50 주식 | 통과 ($50M 대금) | 통과 |
| $500 주식 | 통과 ($500M 대금) | 통과 |

→ 거래량 기준은 **저가주에 유리**(투기성↑). 거래대금이 진짜 유동성 지표.

## 구현 변경

### config.py

```python
# Before
SCREENER_TOP_N = 500
SCREENER_MIN_VOLUME = 2_000_000
SCREENER_MIN_VOLATILITY = 3.0
SCREENER_MAX_VOLATILITY = 10.0
SCREENER_MIN_MARKET_CAP = 3e9
SCREENER_MAX_MARKET_CAP = 50e9

# After
SCREENER_MIN_VOLATILITY = 3.0
SCREENER_MAX_VOLATILITY = 12.0       # 10 → 12
SCREENER_MIN_MARKET_CAP = 1e9        # 3e9 → 1e9
SCREENER_MAX_MARKET_CAP = 20e9       # 50e9 → 20e9
SCREENER_MIN_TURNOVER = 20_000_000   # 신규 — 20일 평균 거래대금 ($)
# SCREENER_TOP_N, SCREENER_MIN_VOLUME — 삭제
```

### screener.py filter_hot_stocks

```python
# Before
avg_volume = df['Volume'].tail(20).mean()
if avg_volume < config.SCREENER_MIN_VOLUME:
    continue

# After
avg_turnover = (df['Volume'] * df['Close']).tail(20).mean()
if avg_turnover < config.SCREENER_MIN_TURNOVER:
    continue
```

## SCREENER_MIN_VOLUME 사용처 점검

phase 2 grep 결과:
- `config.py:182` (정의)
- `screener.py:244` (사용)

→ 사용처는 한 곳뿐. 안전하게 제거 가능.

## SCREENER_TOP_N 사용처 점검

- `config.py:180` (정의)
- 다른 사용처 없음 (phase 2에서 함수 시그니처 변경하며 자연 제거)

→ 안전하게 제거.

## 검증 방법

1. **import/단독 실행**: screener.py가 정상 로드되는지
2. **거래대금 환산 확인**: APLD($44.59, 평균 거래량 약 1M주) → 거래대금 $44M → 통과
3. **IONQ/PLTR/SOFI 통과 확인**
4. **저가주 차단 확인**: $5 종목이 거래량 5M주(=거래대금 $25M)면 통과, 2M주(=거래대금 $10M)면 차단

## 백업

config.py는 이미 phase 1에서 백업됨 (`config_backup.py`). 추가 백업 불필요.

## 상태

- [x] phase_3.md 작성
- [x] config.py 임계값 수정 (시총 $1B~$20B, 변동성 상한 12%)
- [x] config.py 신규 상수 `SCREENER_MIN_TURNOVER = $20M`
- [x] config.py 폐기 상수 `SCREENER_TOP_N`, `SCREENER_MIN_VOLUME` 제거
- [x] screener.py `filter_hot_stocks` 거래대금 필터로 교체 ([screener.py:240,244](../screener.py#L240))
- [x] grep 점검 — 코드에 폐기 상수 사용처 0건 (docs만 잔존)
- [x] 임포트 스모크 테스트 통과
- [ ] (캐시 빌드 완료 후) 실제 종목 분포 점검