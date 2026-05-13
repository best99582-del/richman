# Phase 5: 통합 검증

## 목적

phase 1~3에서 변경한 코드가 **실제로 의도대로 작동**하는지 캐시 빌드 완료 후 검증.

## 의존성

- Phase 1 캐시 빌드(`market_cap_cache.json`) 완료 필수
- 약 6,000 종목의 시총 데이터가 있어야 의미 있는 검증 가능

## 검증 항목

### V1. `get_universe()` 통과 종목 분포

목표: 시총 $1B~$20B + 업종 제외 통과 종목이 합리적 수(약 600~1200개)인지

```python
from screener import get_universe
universe = get_universe()
print(f'유니버스 크기: {len(universe)}개')
```

**판정 기준:**
- 200개 미만: 필터가 과도하게 엄격 → 임계값 재검토
- 200~2000개: 정상
- 2000개 초과: 필터가 약함 → 추가 점검 필요

### V2. TICKERS 호환 확인

목표: 사용자 핵심 종목이 통과하는지

```python
must_pass = ['IONQ', 'PLTR', 'APLD', 'SOFI', 'RKLB', 'IREN']
universe = get_universe()
for t in must_pass:
    status = '✅' if t in universe else '❌'
    print(f'{status} {t}')
```

**탈락 시 점검:**
- 시총 범위 밖? (시총값 직접 출력)
- 업종 제외? (Industry 확인)
- 캐시 누락? (yfinance 조회 실패 종목)

### V3. 제외 검증

목표: 의도한 제외 대상이 실제로 빠지는지

```python
# 금융주 샘플 — 통과되면 안 됨
should_exclude = ['JPM', 'BAC', 'GS', 'WFC']
universe = get_universe()
for t in should_exclude:
    status = '❌ 통과됨(버그)' if t in universe else '✅ 제외'
    print(f'{status} {t}')
```

### V4. `filter_hot_stocks` 거래대금 환산 확인

목표: 거래대금 필터가 의도대로 작동하는지

샘플 종목으로 직접 환산:
- APLD: $44.59 × 평균 거래량 → 거래대금
- 통과/차단 결과가 예상과 일치하는지

### V5. screener.py 단독 실행 회귀

목표: 전체 파이프라인이 끊김 없이 작동

```powershell
python screener.py
```

- 단계별 출력 확인 (유니버스 → 1차 필터 → AI 분석)
- 결과 종목 수, 매수사정권 분포 확인
- 에러/예외 없음

### V6. trade_journal log scan 회귀

```powershell
python trade_journal.py log scan
```

- screener → predict → 기록 흐름 정상
- 새 ID 부여 정상 (phase 0에서 수정한 로직 회귀)

## 발견 시 대응

| 발견 사항 | 대응 |
|---|---|
| 핵심 TICKERS 탈락 | 임계값 조정(시총 하한↓ 또는 변동성 상한↑) 후 재검증 |
| 금융주 통과 | 제외 키워드 추가 |
| 유니버스 너무 큼/작음 | config 미세조정 |
| API/네트워크 에러 | 재실행, 캐시 부분 갱신 |

## 검증 결과 기록 양식

```
### V1 결과
- 유니버스 크기: X개
- 판정: ✅ 정상 / ⚠️ 조정 필요

### V2 결과
- IONQ: ✅/❌ (시총 $X.XB)
- ...
```

## 상태

- [x] phase_5.md 작성
- [ ] 캐시 빌드 완료 대기
- [ ] V1: 유니버스 분포 확인
- [ ] V2: TICKERS 호환
- [ ] V3: 제외 검증
- [ ] V4: 거래대금 필터
- [ ] V5: screener.py 단독 실행
- [ ] V6: trade_journal log scan
- [ ] 발견 사항 정리 및 미세조정