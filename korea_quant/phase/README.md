# korea_quant Phase 작업 이력

각 Phase별 결과, 결정사항, 해결한 문제를 시간순으로 기록.
새 Phase를 마치면 같은 형식으로 한 파일 추가.

---

## 완료된 Phase

| Phase | 제목 | 핵심 결과물 | 파일 |
|---|---|---|---|
| 0 | 초기 시스템 골격 | korea_quant/ 폴더 전체 구조, 핵심 모듈 8개 | [phase_00_foundation.md](phase_00_foundation.md) |
| 1 | 팩터별 스코어링 방식 분리 | FACTORS 딕셔너리 (팩터마다 scoring + weight 독립) | [phase_01_factor_scoring.md](phase_01_factor_scoring.md) |
| 2 | 진입 조건식 + 논리식 | ENTRY_CONDITIONS, ENTRY_LOGIC (AND/OR/괄호 조합) | [phase_02_entry_conditions.md](phase_02_entry_conditions.md) |
| 3 | Universe 필터 확장 + ATR 비중 | INCLUDE_SECTORS, WHITELIST/BLACKLIST, ATR 비중 | [phase_03_universe_atr.md](phase_03_universe_atr.md) |
| 4 | 16개 팩터 확장 + TTM 도입 | 팩터 16종 완성, DART finstate_all, CIS 처리 | [phase_04_factors_ttm.md](phase_04_factors_ttm.md) |
| 5 | 백테스트 엔진 (시점별 동적 리밸런싱) | vectorbt 기반 백테스트 인프라 검증 완료. 2021-01~2023-09 CAGR -10.5%, 알파 -5.2%p (튜닝 필요) | [phase_05_backtest.md](phase_05_backtest.md) |

---

## 참고 문서 (Phase 무관, 영구 참조)

| 파일 | 내용 |
|---|---|
| [reference_genport_analysis.md](reference_genport_analysis.md) | 젠포트 백테스트 UI 전체 분석 + 우리 시스템과의 매핑표 |

---

## 진행 예정 Phase

| Phase | 제목 | 우선순위 |
|---|---|---|
| 6 | 매도 조건 (목표가/손절가/트레일링/조건매도) | 높음 |
| 7 | 팩터 함수 시스템 (이동평균/순위/변화율) | 중간 |
| 8 | Universe 필터 보강 (관리/감리 실제 필터, 규모별 선택) | 중간 |
| 9 | 최적화 (Optuna) + HTML 리포트 (quantstats) | 낮음 |
| 10 | 추가 팩터 (수급/모멘텀/마켓타이밍) | 낮음 |

### Phase 5 미해결 후속

- 2023Q3, 2023연간, 2024Q2, 2024Q3 분기 보고서 추가 수집 (DART API 응답 정상화 시점에)
- 2021-01-01 ~ 2024-12-31 전체 기간 백테스트 재실행

---

## 작성 가이드

각 phase 파일은 아래 섹션 포함:

1. **목표** — 이 Phase에서 무엇을 해결하려 했나
2. **배경 / 문제 인식** — 시작 시점의 상태와 한계
3. **결정 사항** — 사용자와 합의한 설계 결정 (선택지/이유 포함)
4. **수정 파일** — 어떤 파일에 어떤 변경 들어갔나
5. **해결한 기술 이슈** — 디버깅/리팩터링 과정 중 발견·해결한 것
6. **검증 결과** — 어떻게 확인했고 어떤 수치로 끝났나
7. **남은 한계 / 후속 작업** — 다음 Phase로 넘긴 항목
