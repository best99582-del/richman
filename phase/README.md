# Screener 개편 프로젝트 — 진행 기록

## 전체 목적

screener의 시총 필터가 실제로 작동하지 않는 문제 해결 + 중소형주 타겟 정밀화.

**문제 진단** (2026-05-13):
- `fdr.StockListing('NASDAQ')`이 MarketCap 컬럼을 반환하지 않음
- → [screener.py:153](../screener.py#L153)의 `if 'MarketCap' in df.columns:` 분기가 항상 False
- → 시총 필터 미작동, 단순히 fdr 반환 순서 상위 500개만 사용 중

## 최종 결정사항 (사용자 확정)

| 항목 | 기존 | 변경 후 |
|---|---|---|
| 거래소 | NASDAQ만 | **NASDAQ + NYSE** |
| 시총 범위 | $3B~$50B | **$1B~$20B** |
| 유동성 | 거래량 2M주 | **거래대금 $20M+** |
| ATR 변동성 | 3~10% | **3~12%** |
| 주가 하한 | $5 | $5 (유지) |
| 상장 기간 | 250일 | 250일 (유지) |
| 추가 제외 | — | **금융주, 리츠, 펀드, 지주회사** |
| 시총 데이터 소스 | (작동 안 함) | **yfinance fast_info + 캐싱** |
| 캐시 갱신 주기 | — | **1주일** |

## 단계별 진행

| 단계 | 내용 | 상태 | 기록 |
|---|---|---|---|
| **1** | yfinance 시총 캐싱 시스템 구축 (주 1회 갱신) | ✅ 코드 완료 / 🔄 1차 빌드 진행 중 | [phase_1.md](phase_1.md) |
| **2** | `get_nasdaq_universe()` → `get_universe()` 개편 (NASDAQ+NYSE, 업종 제외) | ✅ 코드 완료 (검증은 캐시 빌드 후) | [phase_2.md](phase_2.md) |
| **3** | config 상수 조정 + 거래대금 필터로 교체 (구 phase 4 흡수) | ✅ 코드 완료 (검증은 캐시 빌드 후) | [phase_3.md](phase_3.md) |
| ~~4~~ | ~~`filter_hot_stocks` 거래대금 필터 추가~~ | ✅ Phase 3에 흡수됨 | — |
| **5** | 통합 검증 (통과 종목 분포 / TICKERS 호환 / 회귀 점검) | ✅ **완료** (V1~V6 모두 통과, 2026-05-14) | [phase_5.md](phase_5.md) |
| 6 (보조) | 백업 파일 정리 — `_archive/`로 이동, .gitignore 등록 | ✅ **완료** (2026-05-14, 7개 파일 + 폴더 1개 이동) | [phase_6_backups.md](phase_6_backups.md) |

## 후속 작업 (Screener 개편 이후)

| 단계 | 내용 | 상태 | 기록 |
|---|---|---|---|
| 후속 1 | ta 라이브러리 부분 교체 (RSI/MACD/BB/ATR/ADX) | ✅ 완료 | (커밋 d7bf392) |
| 후속 2 | Volume_Ratio → Volume_Spike 교체 | ✅ 완료 (2026-05-14) | [phase_vr_spike.md](phase_vr_spike.md) |
| 후속 3 | Optuna 재최적화 (Volume_Spike+Slow_K/D 반영) | ✅ 완료 (2026-05-14, 합계 +777%p) | [phase_optuna_rerun.md](phase_optuna_rerun.md) |

## 작업 원칙

- 각 단계 시작 전 백업 생성 (`파일명_backup.py`)
- 각 단계 완료 후 `phase_N.md`에 결정사항/검증결과 기록
- 한 단계씩 사용자 확인 후 다음 단계 진행
- 선택지는 AskUserQuestion으로 제시 (사용자가 직접 선택)
