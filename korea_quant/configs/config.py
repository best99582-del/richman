# ============================================================================
# korea_quant/configs/config.py
# ============================================================================
# 역할: korea_quant 시스템의 모든 상수를 한곳에서 관리 (Single Source of Truth)
# 규칙: 이 파일 외의 코드에 숫자/문자열 상수 직접 삽입 금지.
#       전략을 바꾸려면 이 파일만 수정하면 됨.
#
# 섹션 구성:
#   1. Universe 필터 (시총/거래량/업종/화이트·블랙리스트)
#   2. 팩터 정의 (16개 중 활성 팩터의 가중치/스코어링 방식)
#   3. 진입 조건식 (스코어링 전 1차 필터, AND/OR 논리식)
#   4. 매수 우선순위 정렬
#   5. 포트폴리오 구성 (TOP_N, 비중 방식, 리밸런싱 주기)
#   6. 백테스트 (기간/수수료/슬리피지/벤치마크)
#   7. 데이터 소스 (DART API 키 등)
#   8. 파일 경로
# ============================================================================


# ============================================================================
# [섹션 1] Universe 필터 (1차 종목 선별)
# ============================================================================
# get_universe() 호출 시 KRX 전체 상장 종목에서 아래 조건으로 1차 필터링.

MARKET_CAP_MIN = 30_000_000_000      # 시총 하한 - 300억 원 (소형주 제외)
MARKET_CAP_MAX = 3_000_000_000_000   # 시총 상한 - 3,000억 원 (대형주 제외)
MIN_AVG_VOLUME = 50_000              # 20일 평균 거래량 최소 (유동성 확보)
MIN_ROE = 0.0                        # ROE 최소 (0% = 적자기업 포함, 양수만 원하면 0.0 위로 조정)

# 업종 제외 (FDR StockListing의 Sector 컬럼에서 매칭) - 항상 적용
EXCLUDE_SECTORS = ['금융업', '보험업', '은행', '증권']

# 업종 포함 선택: [] 이면 전체 업종 허용. 값이 있으면 해당 업종만 통과.
# 예: ['반도체', '바이오/헬스케어', 'IT/플랫폼']
INCLUDE_SECTORS = []

# 관리종목/감리종목 제외 여부 (DART/KRX 표시 종목)
EXCLUDE_ADMIN = True
EXCLUDE_SUPERVISED = True

# 화이트리스트: 지정 종목은 필터 조건과 무관하게 Universe에 강제 포함
# 예: ['005930', '000660']
WHITELIST = []

# 블랙리스트: 지정 종목은 모든 조건을 통과해도 항상 제외
# 예: ['009150', '035720']
BLACKLIST = []


# ============================================================================
# [섹션 2] 팩터 정의 (16개 중 활성 팩터)
# ============================================================================
# 활성 팩터마다 가중치(weight)와 스코어링 방식(scoring)을 설정.
# scorer.score_universe()가 이 딕셔너리를 읽어 자동으로 점수화.
#
# scoring 옵션:
#   'rank_asc'  - 원시값 낮을수록 1.0에 가까운 점수
#                  → PER, PSR, POR, PBR 등 valuation (싼게 좋음)
#                  → RSI (과매도 반등 기대)
#   'rank_desc' - 원시값 높을수록 1.0에 가까운 점수
#                  → ROE, 성장률 (높을수록 좋음)
#   'zscore'    - 표준화 후 0~1 클리핑 (이상치에 민감, 잘 안 씀)
#
# 가중치 합계가 1.0이 되도록 권장 (자동 정규화되긴 함).

FACTORS = {
    # ------------------------------------------------------------------------
    # [밸류에이션 배수] 시가총액 대비 실적 비율 - 낮을수록 저평가
    # ------------------------------------------------------------------------
    'PSR_TTM': {                         # 시총 / TTM 매출액
        'weight':  0.15,
        'scoring': 'rank_asc',
    },
    'POR_TTM': {                         # 시총 / TTM 영업이익
        'weight':  0.15,
        'scoring': 'rank_asc',
    },
    'PBR_Q': {                           # 시총 / 분기말 자기자본
        'weight':  0.10,
        'scoring': 'rank_asc',
    },

    # ------------------------------------------------------------------------
    # [성장률] 분기 YoY 누적 기준 - 높을수록 좋음
    #   (당기 분기누적 - 전년 동기누적) / |전년 동기누적|
    # ------------------------------------------------------------------------
    'SALES_GROWTH_Q': {                  # 매출 성장률
        'weight':  0.15,
        'scoring': 'rank_desc',
    },
    'OP_GROWTH_Q': {                     # 영업이익 성장률
        'weight':  0.15,
        'scoring': 'rank_desc',
    },

    # ------------------------------------------------------------------------
    # [수익성]
    # ------------------------------------------------------------------------
    'ROE_Q': {                           # TTM 순이익 / 분기말 자기자본
        'weight':  0.20,
        'scoring': 'rank_desc',
    },

    # ------------------------------------------------------------------------
    # [기술 지표] (Universe.add_technicals=True 일 때만 활성)
    # ------------------------------------------------------------------------
    'RSI': {                             # RSI(14), 낮을수록 과매도 반등 기대
        'weight':  0.10,
        'scoring': 'rank_asc',
    },

    # ------------------------------------------------------------------------
    # [비활성 팩터] 주석 해제 시 활성화. 가중치 합계 1.0 맞추도록 조정.
    # 모든 팩터 클래스는 factors/fundamental.py 에 이미 구현됨.
    # ------------------------------------------------------------------------
    # 'PER_TTM':        {'weight': 0.00, 'scoring': 'rank_asc'},   # 시총/TTM 순이익
    # 'PCR_TTM':        {'weight': 0.00, 'scoring': 'rank_asc'},   # 시총/TTM 영업현금흐름
    # 'PGPR_TTM':       {'weight': 0.00, 'scoring': 'rank_asc'},   # 시총/TTM 매출총이익
    # 'GP_GROWTH_Q':    {'weight': 0.00, 'scoring': 'rank_desc'},  # 매출총이익 성장률
    # 'NET_GROWTH_Q':   {'weight': 0.00, 'scoring': 'rank_desc'},  # 순이익 성장률
    # 'ROA_Q':          {'weight': 0.00, 'scoring': 'rank_desc'},  # TTM 순이익/분기말 총자산
    # 'OP_MARGIN_TTM':  {'weight': 0.00, 'scoring': 'rank_desc'},  # TTM 영업이익/TTM 매출
    # 'SALES_TTM':      {'weight': 0.00, 'scoring': 'rank_desc'},  # 원시값 (사이즈 팩터)
    # 'OP_PROFIT_TTM':  {'weight': 0.00, 'scoring': 'rank_desc'},  # 원시값
    # 'NET_PROFIT_TTM': {'weight': 0.00, 'scoring': 'rank_desc'},  # 원시값
}


# ============================================================================
# [섹션 3] 진입 조건식 (스코어링 전 1차 필터)
# ============================================================================
# 팩터 원시값 기준으로 조건을 정의하여 미충족 종목을 사전 제외.
# 스코어링 단계에서는 통과한 종목들만 평가하므로 결과가 더 명확해짐.
#
# 각 조건 항목:
#   id     : 'A', 'B', 'C'... 논리식에서 참조할 이름
#   factor : 평가할 팩터/컬럼명 (Universe DataFrame 컬럼 또는 팩터 클래스 name)
#   op     : '>=', '<=', '>', '<', '=='
#   value  : 비교할 숫자
#
# ENTRY_LOGIC : 조건들을 AND/OR/괄호로 조합한 식
#   예: 'A AND B'
#   예: 'A AND (B OR C)'
#   예: ''  → 빈 문자열이면 모든 조건을 AND로 자동 조합
#
# ENTRY_CONDITIONS = [] 이면 조건 필터 없이 전체 Universe 스코어링.

ENTRY_CONDITIONS = [
    # {'id': 'A', 'factor': 'RSI',            'op': '<=', 'value': 50},
    # {'id': 'B', 'factor': 'SALES_GROWTH_Q', 'op': '>=', 'value': 0.0},
    # {'id': 'C', 'factor': 'ROE_Q',          'op': '>=', 'value': 0.05},
]

ENTRY_LOGIC = ''   # 비어있으면 ENTRY_CONDITIONS 전부 AND


# ============================================================================
# [섹션 4] 매수 우선순위 정렬
# ============================================================================
# 'desc' : score_total 높은 종목부터 선택 (기본 - 고점수 선호)
# 'asc'  : score_total 낮은 종목부터 선택 (역발상 전략용)

SORT_ORDER = 'desc'


# ============================================================================
# [섹션 5] 포트폴리오 구성
# ============================================================================

TOP_N = 20                 # 최종 선별 종목 수

# 비중 배분 방식
# 'equal' : 동일가중 (1/TOP_N)
# 'score' : 팩터 점수 비례 (점수 높을수록 비중 ↑)
# 'atr'   : ATR 역비례 (변동성 낮을수록 비중 ↑)
WEIGHT_METHOD = 'equal'

# ATR 비중 설정 (WEIGHT_METHOD = 'atr' 일 때만 사용)
ATR_PERIOD     = 14        # ATR 계산 기간 (일)
ATR_PRICE_DAYS = 30        # ATR 계산용 가격 데이터 기간 (일)
ATR_MAX_WEIGHT = 0.20      # 단일 종목 최대 비중 상한 (예: 20%)

REBALANCE_FREQ = 'Q'       # 리밸런싱 주기: 'Q' 분기 / 'M' 월간


# ============================================================================
# [섹션 6] 백테스트
# ============================================================================

START_DATE = '2018-01-01'
END_DATE   = '2024-12-31'

INITIAL_CAPITAL = 50_000_000   # 초기 투자금 (원) - 5,000만 원

FEE_BUY  = 0.003           # 매수 수수료 0.3%
FEE_SELL = 0.003 + 0.0018  # 매도 수수료 0.3% + 증권거래세 0.18% = 0.48%
SLIPPAGE = 0.001           # 슬리피지 0.1% (양방향)

BENCHMARK_TICKER = '069500'  # KODEX 200 ETF (KOSPI 추종 벤치마크)


# ============================================================================
# [섹션 7] 데이터 소스
# ============================================================================

# OpenDART API 키 (재무 데이터 수집용)
# https://opendart.fss.or.kr/ 에서 발급
DART_API_KEY = '86ab9aecbd83a559eb8c3eff6c78edac25f9cc1b'

FINANCIAL_PERIOD = 'Q'     # 'Q' 분기 보고서 / 'A' 연간 사업보고서 기준
VOLUME_AVG_DAYS  = 20      # 거래량 평균 산출 기간


# ============================================================================
# [섹션 8] 경로
# ============================================================================

import os

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # korea_quant/

DATA_DIR   = os.path.join(_BASE, 'data', 'cache')   # CSV 캐시 저장 디렉토리
REPORT_DIR = os.path.join(_BASE, 'reports')         # 스크리닝/백테스트 결과 저장


# ============================================================================
# [단독 실행] 현재 설정값 콘솔 출력
# ============================================================================

if __name__ == '__main__':
    print('=' * 60)
    print('korea_quant config 확인')
    print('=' * 60)
    print(f'  Universe: 시총 {MARKET_CAP_MIN/1e8:.0f}억 ~ {MARKET_CAP_MAX/1e8:.0f}억')
    print(f'  최소 거래량: {MIN_AVG_VOLUME:,}주 ({VOLUME_AVG_DAYS}일 평균)')
    print(f'  제외 업종: {EXCLUDE_SECTORS}')
    print(f'  포함 업종: {INCLUDE_SECTORS if INCLUDE_SECTORS else "전체"}')
    print(f'  관리종목 제외: {EXCLUDE_ADMIN} | 감리종목 제외: {EXCLUDE_SUPERVISED}')
    print(f'  화이트리스트: {WHITELIST if WHITELIST else "없음"}')
    print(f'  블랙리스트:   {BLACKLIST if BLACKLIST else "없음"}')
    print()
    print(f'  팩터 수: {len(FACTORS)}개 | 가중치 합계: {sum(f["weight"] for f in FACTORS.values()):.2f}')
    print(f'  {"팩터":<15} {"가중치":>6}  {"스코어링"}')
    print('  ' + '-' * 35)
    for name, cfg in FACTORS.items():
        print(f'  {name:<15} {cfg["weight"]:>6.0%}  {cfg["scoring"]}')
    print()
    if ENTRY_CONDITIONS:
        logic = ENTRY_LOGIC if ENTRY_LOGIC else ' AND '.join(c['id'] for c in ENTRY_CONDITIONS)
        print(f'  진입 조건식 ({len(ENTRY_CONDITIONS)}개) | 논리: {logic}')
        for c in ENTRY_CONDITIONS:
            print(f'    [{c["id"]}] {c["factor"]} {c["op"]} {c["value"]}')
    else:
        print(f'  진입 조건식: 없음 (전체 Universe 스코어링)')
    print()
    weight_detail = f'(ATR {ATR_PERIOD}일, 상한 {ATR_MAX_WEIGHT:.0%})' if WEIGHT_METHOD == 'atr' else ''
    print(f'  정렬 방향: {SORT_ORDER} | TOP_N: {TOP_N}종목 | 비중: {WEIGHT_METHOD} {weight_detail} | 리밸: {REBALANCE_FREQ}')
    print()
    print(f'  백테스트: {START_DATE} ~ {END_DATE}')
    print(f'  초기자금: {INITIAL_CAPITAL/1e4:,.0f}만원')
    print(f'  수수료: 매수 {FEE_BUY:.2%} / 매도 {FEE_SELL:.2%} / 슬리피지 {SLIPPAGE:.2%}')
    print()
    print(f'  DATA_DIR:   {DATA_DIR}')
    print(f'  REPORT_DIR: {REPORT_DIR}')
    print('=' * 60)
