# Phase 6 (보조): 백업 파일 정리 계획

## 목적

수정 작업 중 누적된 `*_backup.py` 파일들을 정리. **모든 phase 검증 완료 후** 안전성 확인 후 실행.

## 현재 백업 파일 현황

| 파일 | 크기 | 생성 시점 | 백업 이유 |
|---|---|---|---|
| [config_backup.py](../config_backup.py) | 11.8KB | 2026-05-12 20:52 | kelly.py 손익비 고정 변경 직전 |
| [kelly_backup.py](../kelly_backup.py) | 6.5KB | 2026-05-12 20:52 | 동적 손익비 → 고정 변경 직전 |
| [predict_backup.py](../predict_backup.py) | 18.0KB | 2026-05-12 20:52 | Kelly_Weight_Ref 제거 변경 직전 |
| [screener_backup.py](../screener_backup.py) | 17.6KB | 2026-05-13 21:22 | get_nasdaq_universe → get_universe 변경 직전 |
| [backup/predict_book.py](../backup/predict_book.py) | 3.6KB | 2026-04-25 01:42 | predict.py 초기 프로토타입 (target=3%, 8 피처). 현재 코드 어디서도 import 안 함 |

## 분석

### 보존 가치 평가

| 백업 | 현재 시점 차이 | 보존 가치 | 권장 |
|---|---|---|---|
| config_backup | v10 변경 전 (WIN_LOSS_RATIO 추가, 시총 임계값 변경) | 🟡 중간 | phase 5 통과 후 1~2주 보관 후 제거 |
| kelly_backup | v10 변경 전 (동적 손익비) | 🟡 중간 | 동일 |
| predict_backup | v10 변경 전 (Kelly_Weight_Ref) | 🟢 낮음 | 단일 함수 변경, 빠른 제거 가능 |
| screener_backup | v10 변경 전 (구 get_nasdaq_universe) | 🔴 높음 | phase 5 검증 끝날 때까지 필수 보존 |
| backup/predict_book.py | predict.py 초기 프로토타입 | 🟢 낮음 | 정체 파악 완료. archive/로 안전하게 이동 가능 |

### git 백업과의 관계

**핵심 질문**: 이 프로젝트가 git 저장소인가?

CLAUDE.md 환경 정보에 따르면 **이 프로젝트는 git 저장소가 아님** (`Is a git repository: false`).
→ 모든 백업이 **유일한 복구 수단**. 신중하게.

## 정리 단계 (제안)

### Stage 1: 안전성 확보 (지금 가능)

1. **`backup/predict_book.py` 정체 파악**
   - 내용 확인. 현재 코드 어디서도 import 안 하는지 grep
   - 안전하면 `phase/archive/` 같은 폴더로 이동, 위험하면 그대로 보존

2. **백업 인덱스 작성**
   - `backup/INDEX.md` 또는 phase 폴더에 백업 이력 기록
   - 어느 파일이 언제, 어느 변경 직전 백업인지 명시

### Stage 2: phase 5 완료 후 정리

3. **screener_backup.py**: phase 5 검증 통과 시 archive/ 이동 (제거 X)
4. **predict_backup.py**: 동일
5. **kelly_backup.py, config_backup.py**: 동일

### Stage 3: 1~2주 안정 운영 후 (장기)

6. 실전 운영 중 회귀 문제 없으면 archive/ 폴더 전체 삭제
7. 또는 git init 후 커밋으로 영구 보관

## 일괄 삭제는 권장하지 않음

- git이 없으므로 실수하면 복구 불가
- phase 5에서 회귀 발견 시 백업 즉시 필요
- 디스크 사이즈 영향 미미 (총 57KB)

## 결정 필요 사항

1. `backup/predict_book.py` 정체 파악 (선행 필수)
2. archive 폴더로 옮길지, 그대로 둘지
3. git init을 이번 phase에서 진행할지 (별도 작업)

## 상태

- [x] phase_6_backups.md 계획 작성
- [x] backup/predict_book.py 정체 파악 완료 (predict.py 초기 프로토타입)
- [x] git init + GitHub 연동 완료 (별도 작업)
- [x] 백업 파일 archive 이동 완료 (2026-05-14)
- [x] `.gitignore`에 `_archive/` 추가

## 실행 결과 (2026-05-14)

### 이동된 파일

`_archive/backups_v10/`:
- config_backup.py (May 12)
- kelly_backup.py (May 12)
- predict_backup.py (May 12)
- screener_backup.py (May 13)
- ta_backup.py (May 14, ta→indicators 리네임 직전)
- market_cap_cache_backup.py (May 13)

`_archive/old_backup_folder/`:
- predict_book.py (구 backup/ 폴더 — predict.py 초기 프로토타입)

### 보존 정책

- 디스크에 그대로 남음 → 필요시 복원 가능
- git 추적 안 함 (`.gitignore`의 `_archive/`)
- 모든 변경 이력은 이미 git에 보존됨 (필요시 `git show HASH:파일명`으로 복원 가능)

### 장기 정리 (선택)

3~6개월 운영 후 회귀 문제 없으면 `_archive/` 전체 삭제 검토.