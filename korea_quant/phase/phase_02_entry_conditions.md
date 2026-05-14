# Phase 2 — 진입 조건식 + 논리식

## 목표

젠포트 매수조건 UI의 핵심 기능 구현:
"팩터 연산자 값" 형태의 조건을 여러 개 정의하고 AND/OR/괄호로 조합하여
스코어링 전에 1차 필터링.

## 배경 / 문제 인식

이전엔 시총/거래량 같은 굵직한 필터만 있었음.
"RSI 50 이하이면서 ROE 5% 이상" 같은 세부 조건을 코드로 만들려면
직접 DataFrame 인덱싱을 해야 했음.

젠포트는 UI에서 조건식 + 논리식을 자유롭게 작성 가능.
같은 유연성을 코드로 제공할 필요 있음.

## 결정 사항

`config.py`에 두 변수 신설:

```python
ENTRY_CONDITIONS = [
    {'id': 'A', 'factor': 'RSI',   'op': '<=', 'value': 50},
    {'id': 'B', 'factor': 'ROE_Q', 'op': '>=', 'value': 0.05},
    {'id': 'C', 'factor': 'SALES_GROWTH_Q', 'op': '>=', 'value': 0.0},
]
ENTRY_LOGIC = 'A AND (B OR C)'   # AND/OR/괄호 자유 조합
```

**규칙**:
- `op` 옵션: `>=`, `<=`, `>`, `<`, `==`
- `ENTRY_LOGIC = ''` 이면 모든 조건을 AND로 자동 조합
- `ENTRY_CONDITIONS = []` 이면 조건 필터 없이 전체 Universe 스코어링
- 팩터 데이터가 없는 종목은 해당 조건에서 False 처리 (보수적)

## 수정 파일

- `configs/config.py` — ENTRY_CONDITIONS, ENTRY_LOGIC 섹션 추가
- `scoring/scorer.py`:
  - `apply_entry_conditions()` 함수 신설
  - `_get_factor_raw()` 헬퍼 (컬럼 직접 참조 우선, 없으면 팩터 클래스 compute() 호출)
  - `score_universe()` 맨 앞에서 자동 호출

## 해결한 기술 이슈

- **`AND`를 `&`로 단순 치환 시 문제**: `cond_masks["A"]`의 `A` 부분도 치환되어 깨짐.
  → `re.sub(r'\b' + cid + r'\b', ...)` 단어 경계 사용으로 해결.
- **조건 ID와 키워드 충돌 방지**: `AND`/`OR`을 먼저 `&`/`|`로 치환한 뒤 ID 치환.
- **factor compute() vs 컬럼 참조 우선순위**: 컬럼이 이미 Universe에 있으면 그것을 우선 사용 (속도 + 정확도).

## 검증 결과

단위 테스트로 AND/OR/괄호 조합 모두 정상 동작 확인:

```
입력 5종목, A=RSI<=50, B=ROE>=0.05, C=SALES_GROWTH>=0
─ A AND B          → 2종목 (기대 일치)
─ A OR B           → 4종목 (기대 일치)
─ A AND (B OR C)   → 2종목 (기대 일치)
─ ''  (전체 AND)   → 2종목 (기대 일치)
```

## 남은 한계

- 조건식 좌변에 함수 미지원 (예: `이동평균(RSI, 5) <= 50`) → Phase 7
- 조건식 좌변에 사칙연산 미지원 (예: `op_profit / sales >= 0.1`) → Phase 7
- 매도 조건식 별도 변수 없음 (현재는 진입 조건만) → Phase 6
