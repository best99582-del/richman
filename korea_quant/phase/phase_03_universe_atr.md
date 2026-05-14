# Phase 3 — Universe 필터 확장 + ATR 비중

## 목표

젠포트 "매매 대상 설정" UI의 추가 옵션 3가지 구현:
1. 업종 포함 선택 (현재는 제외만 있음)
2. 개별 종목 화이트/블랙리스트
3. ATR 기반 변동성 역비례 비중 (Risk Parity 유사)

## 배경 / 문제 인식

이전엔 시총/거래량/금융주 제외만 가능. 사용자가 특정 섹터만 보고 싶거나,
좋아하는 종목 강제 포함 / 싫어하는 종목 강제 제외하는 옵션 부재.

비중도 균등(equal) vs 점수 비례(score)뿐. 변동성 큰 종목과 작은 종목에 같은 자금을
배분하면 변동성 큰 종목이 포트폴리오 위험을 지배하는 문제 있음.

## 결정 사항

### 1. INCLUDE_SECTORS
```python
INCLUDE_SECTORS = []                       # [] 면 전체 허용
# INCLUDE_SECTORS = ['반도체', 'IT/플랫폼']  # 값 있으면 해당 업종만
```

### 2. WHITELIST / BLACKLIST
```python
WHITELIST = ['005930']   # 항상 포함 (필터 조건 무관)
BLACKLIST = ['009150']   # 항상 제외
```

순서: 블랙리스트 제거 → 화이트리스트 강제 추가 (raw listing에서 가져옴).

### 3. ATR 비중
```python
WEIGHT_METHOD = 'atr'    # 'equal' / 'score' / 'atr'
ATR_PERIOD = 14
ATR_PRICE_DAYS = 30
ATR_MAX_WEIGHT = 0.20    # 단일 종목 비중 상한 20%
```

알고리즘:
1. 종목별 ATR 계산 (가격 데이터에서 True Range 14일 평균)
2. ATR / Close = 상대 변동성
3. 1 / 상대변동성 → 변동성 낮을수록 높은 비중
4. 상한 클리핑 후 재정규화 (초과분은 다른 종목에 비례 재분배, 2회 반복)

## 수정 파일

- `configs/config.py`:
  - 섹션 1에 INCLUDE_SECTORS, WHITELIST, BLACKLIST 추가
  - 섹션 5에 ATR 관련 상수 추가, WEIGHT_METHOD에 'atr' 옵션 명시
- `universe/universe.py`:
  - `_apply_sector_include()` 신설 (`_exclude_financial()` 직후 호출)
  - `_apply_whitelist_blacklist()` 신설
- `scoring/scorer.py`:
  - `_calc_atr()` — 종목 리스트 → ATR Series
  - `_atr_weight()` — ATR 역비례 비중 + 상한 클리핑
  - `select_portfolio()`에서 `WEIGHT_METHOD='atr'` 분기 추가

## 해결한 기술 이슈

- **ATR 상한 클리핑 후 합계 보전**:
  단순 클리핑하면 합이 1보다 작아짐 → 초과분을 미클리핑 종목에 비례 재분배.
  2회 반복으로 수렴 보장.
- **상대 변동성 정규화**: ATR을 종가로 나눠 절대 가격 영향 제거 (저가주 vs 고가주 공정 비교).
- **데이터 누락 종목**: ATR 계산 실패 시 중앙값으로 대체 (포트폴리오에서 제외하지 않고 평균 비중).

## 검증 결과

단위 테스트:

```
업종 포함 필터 (['반도체']) — 4종목 중 2종목 통과 ✓
블랙리스트 ['000002'] — 1종목 제외 ✓
equal 비중 — [0.333, 0.333, 0.333] 합계 1.0 ✓
score 비중 — 점수 비례 [0.381, 0.333, 0.286] 합계 1.0 ✓
```

ATR 비중은 백그라운드 가격 데이터 필요해서 별도 검증 (Phase 5 백테스트에서 실측).

## 남은 한계

- 관리종목/감리종목 실제 필터링 로직 미완 (EXCLUDE_ADMIN 상수만 있고 universe.py에서 실제 적용 안 함)
  → Phase 8에서 처리
- 코스피·코스닥 규모별 선택 (대형/중형/소형/초소형) 미구현 → Phase 8
- 1일 최대 매수 종목 수, 종목당 최대 매수 금액 미구현 → Phase 5/6
