# Phase 1 — 팩터별 스코어링 방식 분리

## 목표

팩터마다 독립적인 스코어링 방식과 가중치 설정 가능하게 변경.
젠포트 UI의 "팩터별 함수 + 방향 선택" 구조를 코드로 반영.

## 배경 / 문제 인식

이전 구조:
```python
FACTOR_WEIGHTS = {'PSR': 0.15, 'ROE': 0.20}   # 가중치만 분리
SCORING_METHOD = 'rank'                       # 스코어링 방식은 전체 공통
```

문제: PSR(낮을수록 좋음)과 ROE(높을수록 좋음)이 같은 `rank` 방식으로 처리됨.
점수가 뒤집혀 의도와 반대 결과 발생.

## 결정 사항

`FACTOR_WEIGHTS` + `SCORING_METHOD` 두 변수를 단일 `FACTORS` 딕셔너리로 통합.
각 팩터마다 `weight`와 `scoring`을 독립 설정.

```python
FACTORS = {
    'PSR': {'weight': 0.15, 'scoring': 'rank_asc'},   # 낮을수록 점수 ↑
    'ROE': {'weight': 0.20, 'scoring': 'rank_desc'},  # 높을수록 점수 ↑
}
```

**scoring 옵션**:
- `rank_asc` — 원시값 낮을수록 1.0
- `rank_desc` — 원시값 높을수록 1.0
- `zscore` — 표준화 후 0~1 클리핑

추가로 `SORT_ORDER` 도입 (매수 우선순위 정렬 방향):
- `desc` — score_total 높은 종목 우선
- `asc` — score_total 낮은 종목 우선 (역발상 전략용)

## 수정 파일

- `configs/config.py` — FACTORS 딕셔너리, SORT_ORDER 신설
- `factors/factor_base.py` — `score()` 메서드가 `config.FACTORS[name]['scoring']`을 읽어 분기
- `scoring/scorer.py` — FACTOR_WEIGHTS 참조를 FACTORS로 전면 교체
- `factors/fundamental.py` + `factors/technical.py` — 클래스에서 `higher_is_better` 속성 제거 (config 기반으로 일원화)

## 해결한 기술 이슈

- 기존 `higher_is_better` 속성은 클래스 안에 박혀 있어 변경하려면 코드를 고쳐야 했음.
  → config 기반으로 옮겨 사용자가 코드 수정 없이 방향만 바꿀 수 있게 함.
- scorer.py에서 `weight_used` 합계로 자동 정규화 → 일부 팩터 데이터 누락 시에도 안정적.

## 검증 결과

7개 활성 팩터 매핑 정상 확인:

```
PSR             rank_asc   (15%)
POR             rank_asc   (15%)
PBR             rank_asc   (10%)
SALES_GROWTH    rank_desc  (15%)
OP_GROWTH       rank_desc  (15%)
ROE             rank_desc  (20%)
RSI             rank_asc   (10%)
```

가중치 합계 1.0, 부호 방향 모두 의도대로 정확.

## 남은 한계

- 진입 조건식 (RSI <= 50, ROE >= 0.05 같은 1차 필터) 없음 → Phase 2
- 팩터에 함수 적용 (이동평균/순위/변화율 등) 미지원 → Phase 7
