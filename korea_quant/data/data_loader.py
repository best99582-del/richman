# ============================================================================
# korea_quant/data/data_loader.py
# ============================================================================
# 역할:
#   외부 데이터 소스 (FinanceDataReader + OpenDartReader) 통합 어댑터.
#   로컬 CSV 캐시(data/cache/)로 반복 호출 최소화.
#
# 데이터 소스 선택 배경:
#   - pykrx 차단됨 (KRX 서버 세션 인증 정책 변경, 400 LOGOUT)
#   - FinanceDataReader: 종목 리스팅 + 가격 OHLCV + 시가총액
#   - OpenDartReader: 재무제표 (DART API, 별도 운영)
#
# 주요 함수 흐름:
#   [가격/시총]
#     get_stock_listing(market)         - 전 종목 리스팅 (Code/Name/Market/Close/Volume/MarketCap)
#     get_price(ticker, start, end)     - 단일 종목 일별 OHLCV
#     get_price_matrix(tickers, ...)    - 복수 종목 종가 매트릭스 (백테스트용)
#
#   [재무제표]
#     get_financial(ticker, y, q)       - DART finstate_all (전체 계정 raw DataFrame)
#     get_financial_summary(ticker,y,q) - raw → 표준 키 dict (sales, op_profit, TTM 등)
#     get_financial_batch(tickers,y,q)  - 복수 종목 summary 배치 수집 → DataFrame
#
# 캐시 정책:
#   load_cache(key) / save_cache(key, df) - CSV 파일 단위 키-값 캐시
#   분기/연간 보고서 단위로 종목별 raw 캐시 저장 → 재실행 시 API 호출 0회
#
# 단위: 모든 금액은 원(KRW) 정수. 비율은 소수 (예: ROE 5% = 0.05)
# ============================================================================

import os
import sys
import logging
from datetime import datetime

import pandas as pd
import FinanceDataReader as fdr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from configs import config

logger = logging.getLogger(__name__)

# OpenDartReader 분기 보고서 코드
REPRT_CODES = {
    1: '11013',   # 1분기보고서
    2: '11012',   # 반기보고서
    3: '11014',   # 3분기보고서
    4: '11011',   # 사업보고서 (연간)
}


# ============================================================================
# [캐시] CSV 저장/불러오기
# ============================================================================

def _cache_path(key: str) -> str:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    safe_key = key.replace('/', '_').replace(' ', '_')
    return os.path.join(config.DATA_DIR, f'{safe_key}.csv')


def load_cache(key: str) -> pd.DataFrame | None:
    path = _cache_path(key)
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, index_col=0, encoding='utf-8-sig')
    logger.debug('캐시 로드: %s (%d행)', key, len(df))
    return df


def save_cache(key: str, df: pd.DataFrame):
    path = _cache_path(key)
    df.to_csv(path, encoding='utf-8-sig')
    logger.debug('캐시 저장: %s (%d행)', key, len(df))


# ============================================================================
# [FDR] 전 종목 리스팅 (시총 / PER / PBR 포함)
# ============================================================================

def get_stock_listing(market: str = 'KRX', use_cache: bool = True) -> pd.DataFrame:
    """
    전 종목 코드/명/시총/거래량/PER/PBR 반환 (현재 시점 기준).

    Args:
        market: 'KRX' / 'KOSPI' / 'KOSDAQ'
        use_cache: True면 당일 캐시 우선 사용

    Returns:
        DataFrame - 컬럼: Code, Name, Market, Close, Volume, Marcap, PER, PBR
    """
    today = datetime.now().strftime('%Y%m%d')
    key = f'listing_{market}_{today}'

    if use_cache:
        cached = load_cache(key)
        if cached is not None:
            return cached

    df = fdr.StockListing(market)

    # 필요 컬럼만 정리
    keep = ['Code', 'Name', 'Market', 'Close', 'Volume', 'Marcap', 'Stocks']
    df = df[[c for c in keep if c in df.columns]].copy()
    df = df.rename(columns={'Marcap': 'MarketCap'})
    df = df.dropna(subset=['Code', 'MarketCap'])
    df['Code'] = df['Code'].astype(str).str.zfill(6)

    _print_quality(df, f'StockListing({market})')

    if use_cache:
        save_cache(key, df)
    return df


# ============================================================================
# [FDR] 단일 종목 OHLCV
# ============================================================================

def get_price(ticker: str, start: str, end: str, use_cache: bool = True) -> pd.DataFrame:
    """
    단일 종목 일별 OHLCV 반환.

    Args:
        ticker: 6자리 종목코드 (예: '005930')
        start, end: 'YYYY-MM-DD' 또는 'YYYYMMDD'

    Returns:
        DataFrame - 인덱스: 날짜, 컬럼: Open, High, Low, Close, Volume
    """
    key = f'price_{ticker}_{start}_{end}'

    if use_cache:
        cached = load_cache(key)
        if cached is not None:
            cached.index = pd.to_datetime(cached.index)
            return cached

    df = fdr.DataReader(ticker, start, end)

    if df is None or df.empty:
        logger.warning('get_price(%s) 결과 없음', ticker)
        return pd.DataFrame()

    df.index = pd.to_datetime(df.index)
    if use_cache:
        save_cache(key, df)
    return df


# ============================================================================
# [FDR] 복수 종목 종가 시계열 (백테스트용)
# ============================================================================

def get_price_matrix(tickers: list[str], start: str, end: str, use_cache: bool = True) -> pd.DataFrame:
    """
    복수 종목 일별 종가 매트릭스 반환 (vectorbt 백테스트 입력용).

    Returns:
        DataFrame - 인덱스: 날짜, 컬럼: 티커별 종가
    """
    key = f'price_matrix_{start}_{end}_{len(tickers)}tickers'

    if use_cache:
        cached = load_cache(key)
        if cached is not None:
            cached.index = pd.to_datetime(cached.index)
            return cached

    frames = {}
    for ticker in tickers:
        df = get_price(ticker, start, end, use_cache=use_cache)
        if not df.empty and 'Close' in df.columns:
            frames[ticker] = df['Close']

    if not frames:
        return pd.DataFrame()

    matrix = pd.DataFrame(frames)
    matrix.index = pd.to_datetime(matrix.index)

    if use_cache:
        save_cache(key, matrix)
    return matrix


# ============================================================================
# [OpenDartReader] 재무제표
# ============================================================================

def get_financial(ticker: str, year: int, quarter: int = 4, use_cache: bool = True) -> pd.DataFrame:
    """
    단일 종목 재무제표 조회 (OpenDartReader.finstate_all).

    finstate() 는 IS/BS 핵심 5개 계정만 반환 → 매출원가/매출총이익/현금흐름 누락.
    finstate_all() 은 전체 계정 반환 (IS, BS, CF, CIS, SCE 포함).
    연결재무제표(CFS) 우선 시도 → 실패 시 별도재무제표(OFS) 폴백.

    Args:
        ticker:  6자리 종목코드 (예: '005930')
        year:    사업연도 (예: 2023)
        quarter: 1/2/3/4 (4=연간 사업보고서)

    Returns:
        DataFrame - account_nm, thstrm_amount(당기), frmtrm_amount(전기) 등 포함
                    fs_div 컬럼 직접 부여 ('CFS' or 'OFS')
    """
    if not config.DART_API_KEY:
        logger.warning('DART_API_KEY 미설정. configs/config.py에 키 입력 필요.')
        return pd.DataFrame()

    key = f'financial_{ticker}_{year}Q{quarter}'
    if use_cache:
        cached = load_cache(key)
        if cached is not None:
            return cached

    import opendartreader
    dart = opendartreader.OpenDartReader(config.DART_API_KEY)
    reprt_code = REPRT_CODES.get(quarter, '11011')

    # CFS(연결) 우선 시도, 실패 시 OFS(별도) 폴백
    df = pd.DataFrame()
    for fs_div in ('CFS', 'OFS'):
        try:
            part = dart.finstate_all(ticker, year, reprt_code=reprt_code, fs_div=fs_div)
        except Exception as e:
            logger.debug('finstate_all(%s %dQ%d %s) 예외: %s', ticker, year, quarter, fs_div, e)
            continue
        if part is None or part.empty:
            continue
        part = part.copy()
        # fs_div 컬럼이 없으면 직접 부여 (finstate_all 일부 버전 한정)
        if 'fs_div' not in part.columns:
            part['fs_div'] = fs_div
        df = pd.concat([df, part], ignore_index=True)
        # CFS에서 데이터 얻었으면 OFS는 보조용으로만 추가 — 위 concat 결과 모두 유지

    if df.empty:
        logger.warning('get_financial(%s %dQ%d) 결과 없음', ticker, year, quarter)
        return pd.DataFrame()

    if use_cache:
        save_cache(key, df)
    return df


def get_financial_summary(ticker: str, year: int, quarter: int = 4) -> dict:
    """
    재무제표에서 핵심 수치만 추출하여 dict 반환.

    finstate_all() 사용 - 분기 보고서 필드 매핑:
      thstrm_amount      : 당기 분기 누적 (예: 2025 1~9월)
      frmtrm_q_amount    : 전년 동기 누적 (예: 2024 1~9월) - YoY 비교용
      thstrm_add_amount  : TTM (DART가 직접 계산해서 제공)
      frmtrm_add_amount  : 전년 TTM

    Returns:
        dict 컬럼:
          분기 누적:   sales, gross_profit, op_profit, net_profit, operating_cf
          잔액:       equity, total_assets
          전년 동기:   sales_prev, gross_profit_prev, op_profit_prev, net_profit_prev
          TTM:        sales_ttm, gross_profit_ttm, op_profit_ttm, net_profit_ttm, operating_cf_ttm
          별칭(성장률용): sales_cur, gross_profit_cur, op_profit_cur
        금액 단위: 원
    """
    df = get_financial(ticker, year, quarter)
    if df.empty:
        return {}

    # 연결재무제표(CFS) 우선, 보조용 별도(OFS)
    if 'fs_div' in df.columns:
        cfs = df[df['fs_div'] == 'CFS']
        ofs = df[df['fs_div'] == 'OFS']
        primary = cfs if not cfs.empty else ofs
        secondary = ofs if not cfs.empty else pd.DataFrame()
    else:
        primary = df
        secondary = pd.DataFrame()

    def _split(d: pd.DataFrame, sj_codes) -> pd.DataFrame:
        """sj_div가 sj_codes(문자열 또는 리스트) 중 하나인 행만 추출."""
        if d.empty or 'sj_div' not in d.columns:
            return pd.DataFrame()
        codes = [sj_codes] if isinstance(sj_codes, str) else list(sj_codes)
        return d[d['sj_div'].isin(codes)]

    # 재무제표 종류별로 행 분리.
    # 손익계산서: IS(단순) 또는 CIS(포괄손익계산서) 둘 다 수용해야 함.
    # 한국 IFRS 기업 다수가 IS 없이 CIS만 공시 → CIS 누락 시 sales 등 5%만 수집됨.
    is_df = _split(primary, ['IS', 'CIS'])
    bs_df = _split(primary, 'BS')
    cf_df = _split(primary, 'CF')
    is_ofs = _split(secondary, ['IS', 'CIS'])
    bs_ofs = _split(secondary, 'BS')
    cf_ofs = _split(secondary, 'CF')

    def _parse(amount) -> int:
        """'1,234,567' 또는 1234567.0 같은 다양한 표현을 정수로 변환. 실패 시 0."""
        try:
            return int(float(str(amount).replace(',', '').strip()))
        except (ValueError, TypeError):
            return 0

    # ------------------------------------------------------------------
    # 계정명 → 표준 키 매핑.
    # DART는 회사마다 계정명이 미묘하게 다름 (IFRS/K-GAAP, 회사 정책).
    # 동의어를 같은 표준 키에 모두 매핑하여 누락 방지.
    # ------------------------------------------------------------------
    is_map = {
        # 매출 (회사 따라 영업수익으로 기재하는 경우도 있음)
        '매출액':         'sales',
        '수익(매출액)':    'sales',
        '영업수익':       'sales',
        # 매출원가 → gross_profit 직접 기재 없을 때 역산용 (sales - cogs)
        '매출원가':       'cogs',
        # 매출총이익 (회사 따라 매출총손익/매출이익으로 표기)
        '매출총이익':     'gross_profit',
        '매출총손익':     'gross_profit',
        '매출이익':       'gross_profit',
        # 영업이익 (적자 표시 변형 포함)
        '영업이익':       'op_profit',
        '영업이익(손실)': 'op_profit',
        '영업손익':       'op_profit',
        # 순이익 - 한국 IFRS는 지배기업 귀속분 별도 표기 → 그 변형까지 수용
        '당기순이익':                          'net_profit',
        '당기순이익(손실)':                    'net_profit',
        '지배기업의소유주에게귀속되는당기순이익': 'net_profit',
        '지배기업 소유주지분':                  'net_profit',
        '지배기업소유주지분순이익':              'net_profit',
        '연결당기순이익':                       'net_profit',
        '분기순이익':                          'net_profit',
        '반기순이익':                          'net_profit',
    }
    bs_map = {
        # 잔액 (시점 개념). 분기 보고서면 분기말 기준.
        '자본총계': 'equity',
        '자본합계': 'equity',
        '자산총계': 'total_assets',
        '자산합계': 'total_assets',
    }
    cf_map = {
        # 영업활동현금흐름. 공백/표기 변형 다수 수용.
        '영업활동으로인한현금흐름':   'operating_cf',
        '영업활동현금흐름':          'operating_cf',
        '영업으로부터창출된현금':     'operating_cf',
        '영업활동으로 인한 현금흐름': 'operating_cf',
    }

    result = {}

    # 분기 보고서 여부 - 전년 동기/TTM 필드 매핑이 분기/연간에 따라 다름.
    is_quarterly = quarter in (1, 2, 3)

    def _extract(rows: pd.DataFrame, account_map: dict, allow_ttm: bool = True):
        """매핑된 계정의 당기/전년동기/TTM 금액을 result dict에 저장.

        분기 보고서:
          thstrm_amount     → 당기 분기누적 (예: 2025 1~9월)
          frmtrm_q_amount   → 전년 동기누적 (예: 2024 1~9월) - YoY용
          thstrm_add_amount → TTM (DART가 직접 계산 제공, IS만)
        연간 보고서:
          thstrm_amount     → 연간
          frmtrm_amount     → 전년 연간
          (TTM = 연간 자체)
        """
        for _, row in rows.iterrows():
            nm = str(row.get('account_nm', '')).strip()
            if nm not in account_map:
                continue
            base = account_map[nm]
            # 이미 채워졌으면 스킵 (중복 행 방지)
            if base in result and result[base] != 0:
                continue
            cur = _parse(row.get('thstrm_amount', 0))
            if cur != 0 or base not in result:
                result[base] = cur
            # 전년 동기 (분기 보고서: frmtrm_q_amount, 연간 보고서: frmtrm_amount)
            if is_quarterly:
                prev = _parse(row.get('frmtrm_q_amount', 0))
            else:
                prev = _parse(row.get('frmtrm_amount', 0))
            if prev != 0:
                result[f'{base}_prev'] = prev
            # TTM
            if allow_ttm:
                if is_quarterly:
                    ttm = _parse(row.get('thstrm_add_amount', 0))
                    if ttm != 0:
                        result[f'{base}_ttm'] = ttm
                else:
                    # 연간 보고서면 당기 누적 = 연간 = TTM
                    if cur != 0:
                        result[f'{base}_ttm'] = cur

    # IS - CFS 우선, OFS 보완
    _extract(is_df, is_map, allow_ttm=True)
    _extract(is_ofs, is_map, allow_ttm=True)

    # BS - 잔액이라 TTM 개념 없음
    _extract(bs_df, bs_map, allow_ttm=False)
    _extract(bs_ofs, bs_map, allow_ttm=False)

    # CF
    _extract(cf_df, cf_map, allow_ttm=True)
    _extract(cf_ofs, cf_map, allow_ttm=True)

    # 매출총이익 역산 (직접 기재 없을 때만)
    if 'gross_profit' not in result and 'sales' in result and 'cogs' in result:
        result['gross_profit'] = result['sales'] - result['cogs']
    if 'gross_profit_prev' not in result and 'sales_prev' in result and 'cogs_prev' in result:
        result['gross_profit_prev'] = result['sales_prev'] - result['cogs_prev']
    if 'gross_profit_ttm' not in result and 'sales_ttm' in result and 'cogs_ttm' in result:
        result['gross_profit_ttm'] = result['sales_ttm'] - result['cogs_ttm']

    # 내부 임시 키 제거
    for tmp in ['cogs', 'cogs_prev', 'cogs_ttm']:
        result.pop(tmp, None)

    # 팩터용 _cur 별칭 (성장률 팩터가 sales_cur 형식으로 참조)
    for base in ['sales', 'gross_profit', 'op_profit']:
        if base in result:
            result[f'{base}_cur'] = result[base]

    return result


# ============================================================================
# [DART 배치] Universe 전 종목 재무 데이터 수집
# ============================================================================

def get_financial_batch(
    tickers: list,
    year: int,
    quarter: int = 4,
    use_cache: bool = True,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    복수 종목 재무 데이터 배치 수집 → Universe 결합용 DataFrame 반환.

    Args:
        tickers:  6자리 종목코드 리스트
        year:     사업연도
        quarter:  1/2/3/4 (4=연간)
        use_cache: 종목별 캐시 사용
        verbose:  진행 상황 출력

    Returns:
        DataFrame — 인덱스: Code, 컬럼:
          당기(분기 누적):   sales, gross_profit, op_profit, net_profit, operating_cf
          잔액:             equity, total_assets
          당기 별칭:        sales_cur, gross_profit_cur, op_profit_cur
          전기 (YoY용):     sales_prev, gross_profit_prev, op_profit_prev, net_profit_prev
        수집 실패 종목은 NaN으로 포함 (제외하지 않음)
    """
    if not config.DART_API_KEY:
        logger.warning('DART_API_KEY 미설정 - 재무 데이터 수집 불가')
        return pd.DataFrame()

    batch_key = f'financial_batch_{year}Q{quarter}_{len(tickers)}tickers'
    if use_cache:
        cached = load_cache(batch_key)
        if cached is not None:
            logger.debug('재무 배치 캐시 로드: %d종목', len(cached))
            if verbose:
                print(f'  [캐시] 재무 데이터 로드: {len(cached)}개 종목 ({year}Q{quarter})')
            return cached

    records = {}
    total = len(tickers)
    success = 0
    fail = 0

    if verbose:
        print(f'  DART 재무 데이터 수집 중 ({total}개 종목, {year}Q{quarter})...')

    for i, ticker in enumerate(tickers):
        try:
            summary = get_financial_summary(ticker, year, quarter)
            if summary:
                records[ticker] = summary
                success += 1
            else:
                records[ticker] = {}
                fail += 1
        except Exception as e:
            logger.debug('재무 수집 실패 (%s): %s', ticker, e)
            records[ticker] = {}
            fail += 1

        if verbose and (i + 1) % 50 == 0:
            print(f'    {i+1}/{total} 완료 (성공: {success}, 실패: {fail})', flush=True)

    result_df = pd.DataFrame(records).T
    result_df.index.name = 'Code'

    if verbose:
        print(f'  수집 완료: 성공 {success}개 / 실패 {fail}개')

    if use_cache and not result_df.empty:
        save_cache(batch_key, result_df)

    return result_df


# ============================================================================
# [통합] Universe 구성용 원시 DataFrame
# ============================================================================

def get_universe_raw(market: str = 'KRX') -> pd.DataFrame:
    """
    전 종목 시총 + 거래량 + PER/PBR 통합 DataFrame 반환.
    universe.py의 필터링 입력으로 사용.

    Returns:
        DataFrame - Code, Name, Market, Close, Volume, MarketCap, Stocks
    """
    df = get_stock_listing(market)

    if df.empty:
        logger.error('get_universe_raw: 데이터 수집 실패')
        return pd.DataFrame()

    # 20일 평균 거래량은 개별 종목 price 조회 필요 - Universe 단계에서 처리
    _print_quality(df, f'Universe raw ({market})')
    return df


# ============================================================================
# [내부] 데이터 품질 출력
# ============================================================================

def _print_quality(df: pd.DataFrame, label: str):
    total = len(df)
    if total == 0:
        print(f'  [WARNING] [{label}] 데이터 없음')
        return
    nan_pct = df.isnull().mean() * 100
    high_nan = nan_pct[nan_pct > 20]
    print(f'  [OK] [{label}] {total:,}개 종목')
    if not high_nan.empty:
        for col, pct in high_nan.items():
            print(f'     [WARNING] {col}: 결측 {pct:.1f}%')


# ============================================================================
# [단독 실행] 동작 확인
# ============================================================================

if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)

    print('=' * 60)
    print('korea_quant data_loader 동작 확인')
    print('=' * 60)

    print('\n[1] 전 종목 리스팅 (KRX)...')
    listing = get_stock_listing('KRX')
    if not listing.empty:
        print(f'  → {len(listing):,}개 종목')
        print(f'  컬럼: {list(listing.columns)}')
        print(listing.head(5).to_string())

    print('\n[2] 삼성전자 OHLCV (최근 10 거래일)...')
    price = get_price('005930', '2024-12-01', '2024-12-31')
    if not price.empty:
        print(f'  → {len(price)}행')
        print(price.tail(5).to_string())

    print('\n[3] 시총 필터 테스트 (300억~3,000억)...')
    if not listing.empty:
        filtered = listing[
            (listing['MarketCap'] >= config.MARKET_CAP_MIN) &
            (listing['MarketCap'] <= config.MARKET_CAP_MAX)
        ]
        print(f'  → 필터 후 {len(filtered):,}개 종목')
        print(filtered[['Code', 'Name', 'MarketCap', 'Close']].head(5).to_string())

    print('\n[4] DART API 키 상태...')
    if config.DART_API_KEY:
        print('  [OK] DART_API_KEY 설정됨 - 재무제표 조회 가능')
    else:
        print('  [WARNING]  DART_API_KEY 미설정 - configs/config.py에 입력 필요')
        print('     PSR/POR/EV_GP/성장률 팩터는 DART 키 필요')

    print('\n[OK] data_loader 확인 완료')
    print('=' * 60)
