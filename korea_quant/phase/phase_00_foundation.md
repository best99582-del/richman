# Phase 0 — 초기 시스템 골격

## 목표

richman/ 기존 미국 나스닥 AI 스윙 트레이딩 시스템과 분리하여
한국 시장 팩터 투자 백테스트/스크리닝 시스템 `korea_quant/` 신규 구축.

## 배경

- richman/ 루트는 미국 중소형주 + AI 예측 + 단기 스윙 전용 구조
- 한국 시장은 데이터 소스(DART, KRX, FDR), 회계 기준(IFRS/K-GAAP),
  거래 비용 구조(증권거래세 등)가 다르므로 분리 운영 결정
- 기존 richman/ 루트 파일은 일절 수정 금지

## 결정 사항

- 폴더 구조: `korea_quant/` 하위에 모든 모듈 격리
- 데이터 소스: FinanceDataReader(가격/시총) + OpenDartReader(재무제표)
- 백테스트 엔진: vectorbt (Phase 5에서 본격 구현 예정)
- 모든 상수는 `configs/config.py` 단일 진입점

## 수정 파일 (신규 생성)

```
korea_quant/
├── configs/config.py         # 모든 상수 중앙 관리
├── data/data_loader.py       # FDR + DART 통합
├── factors/factor_base.py    # 팩터 추상 베이스 (ABC)
├── factors/fundamental.py    # 재무 팩터
├── factors/technical.py      # 기술 팩터 (RSI/MACD/Volume_Ratio)
├── universe/universe.py      # Universe 동적 생성 + 1차 필터
├── scoring/scorer.py         # 종합 스코어링 + 포트폴리오 선별
├── screener/screener.py      # 현재 시점 스크리닝 실행
├── backtest/backtest.py      # 골격만 (Phase 5에서 채움)
├── main.py                   # CLI 진입점
└── requirements.txt
```

## 해결한 기술 이슈

- **pykrx 차단**: KRX 서버 세션 인증 정책 변경 → FDR로 우회
- **opendartreader 패키지명**: import는 `opendartreader` (소문자), 클래스는 `OpenDartReader`
- **DART CFS vs OFS**: 연결재무제표 우선, 별도재무제표 보완 로직

## 검증 결과

- `config.py` 단독 실행 시 모든 상수 정상 출력
- `data_loader.py` 단독 실행 시 KRX 전체 종목 리스팅 정상
- 삼성전자 분기 재무 수집 성공

## 남은 한계

- 모든 팩터가 동일한 스코어링 방식 사용 → Phase 1에서 해결
- ENTRY_CONDITIONS 등 조건식 없음 → Phase 2에서 추가
- 백테스트 엔진 미구현 → Phase 5
