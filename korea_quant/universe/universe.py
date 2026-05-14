# ============================================================================
# korea_quant/universe/universe.py
# ============================================================================
# 역할:
#   현재 시점 또는 임의 날짜 기준으로 분석 대상 종목 집합(Universe)을 구성.
#   원시 종목 리스트 → 1차 필터 → 재무 데이터 부착 → 기술지표 부착 → 캐싱.
#
# 처리 단계 (get_universe() 내부 흐름):
#   [1] 전 종목 리스팅       - data_loader.get_stock_listing()
#   [2] 우선주 / SPAC 제외   - 종목코드 패턴 + 종목명 키워드
#   [3] 시가총액 범위 필터   - config.MARKET_CAP_MIN ~ MAX
#   [4] 최소 거래량 필터     - config.MIN_AVG_VOLUME
#   [5] 업종 필터            - 금융주 제외 + INCLUDE_SECTORS + 화이트/블랙리스트
#   [6] DART 재무 데이터    - 분기 보고서 + CF TTM 역산 (옵션)
#   [7] 기술 지표 부착       - RSI/MACD/Volume_Ratio (옵션, 종목별 OHLCV 수집)
#
# Survivorship Bias 방지:
#   백테스트 시 리밸런싱 날짜를 인자로 받아 해당 시점 Universe 재구성 필요.
#   (현재 FDR StockListing은 현재 시점 데이터만 제공 → Phase 8에서 보강 예정)
#
# 캐시:
#   캐시 키 = f'universe_{date}_tech{0/1}_fin{0/1}'
#   분기/연간 보고서 단위 raw 캐시는 data_loader 쪽에서 별도 관리.
# ============================================================================

import sys
import os
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from configs import config
from data.data_loader import get_stock_listing, get_price, load_cache, save_cache, get_financial_batch
from factors.technical import calc_indicators

logger = logging.getLogger(__name__)


# ============================================================================
# [핵심] Universe 생성
# ============================================================================

def get_universe(
    as_of_date: str | None = None,
    add_technicals: bool = True,
    add_financials: bool = True,
    use_cache: bool = True,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    특정 날짜 기준 Universe 생성 및 1차 필터 적용.

    Args:
        as_of_date: 'YYYY-MM-DD' 또는 None (None이면 오늘 기준 현재 시점)
        add_technicals: True면 RSI/MACD/거래량비율 지표 추가 (종목별 price 로드 필요)
        add_financials: True면 DART 재무 데이터 부착 (PSR/POR/EV_GP/성장률/ROE 팩터 활성화)
        use_cache: 캐시 사용 여부
        verbose: 필터 단계별 종목 수 출력

    Returns:
        DataFrame — 인덱스: Code, 컬럼: Name, Market, Close, MarketCap, Volume, ...
    """
    date_str = as_of_date or datetime.now().strftime('%Y-%m-%d')
    cache_key = f'universe_{date_str}_tech{int(add_technicals)}_fin{int(add_financials)}'

    if use_cache:
        cached = load_cache(cache_key)
        if cached is not None:
            if verbose:
                print(f'[캐시] Universe 로드: {len(cached)}개 종목 ({date_str})')
            return cached

    # -------------------------------------------------------------------------
    # [1단계] 전 종목 리스팅 수집
    # -------------------------------------------------------------------------
    raw = get_stock_listing('KRX', use_cache=use_cache)
    if raw.empty:
        logger.error('Universe 생성 실패: 종목 리스팅 없음')
        return pd.DataFrame()

    df = raw.copy()
    df = df.set_index('Code')
    n_total = len(df)

    if verbose:
        print(f'\n[Universe 생성] 기준일: {date_str}')
        print(f'  전체 상장 종목: {n_total:,}개')

    # -------------------------------------------------------------------------
    # [2단계] 우선주 / SPAC 제외
    # -------------------------------------------------------------------------
    # 우선주: 종목코드 끝자리가 5 (예: 005935 삼성전자우)
    df = df[~df.index.str.endswith('5')]
    # SPAC: 종목명에 '스팩' 포함
    df = df[~df['Name'].str.contains('스팩|SPAC', na=False)]
    if verbose:
        print(f'  우선주/SPAC 제외 후: {len(df):,}개')

    # -------------------------------------------------------------------------
    # [3단계] 시가총액 필터
    # -------------------------------------------------------------------------
    df = df[
        (df['MarketCap'] >= config.MARKET_CAP_MIN) &
        (df['MarketCap'] <= config.MARKET_CAP_MAX)
    ]
    if verbose:
        print(f'  시총 {config.MARKET_CAP_MIN/1e8:.0f}억~{config.MARKET_CAP_MAX/1e8:.0f}억 필터 후: {len(df):,}개')

    # -------------------------------------------------------------------------
    # [4단계] 거래량 필터 (일 거래량 기준 — 정확한 20일 평균은 add_technicals 단계)
    # -------------------------------------------------------------------------
    if 'Volume' in df.columns:
        df = df[df['Volume'] >= config.MIN_AVG_VOLUME]
        if verbose:
            print(f'  최소 거래량({config.MIN_AVG_VOLUME:,}주) 필터 후: {len(df):,}개')

    # -------------------------------------------------------------------------
    # [5단계] 금융주 제외 + 업종 포함/제외 필터 + 화이트/블랙리스트
    # -------------------------------------------------------------------------
    df = _exclude_financial(df, verbose)
    df = _apply_sector_include(df, verbose)
    df = _apply_whitelist_blacklist(df, verbose)

    # -------------------------------------------------------------------------
    # [6단계] DART 재무 데이터 부착 (선택)
    # -------------------------------------------------------------------------
    if add_financials and len(df) > 0 and config.DART_API_KEY:
        df = _add_financials(df, date_str, use_cache, verbose)
    elif add_financials and not config.DART_API_KEY:
        if verbose:
            print('  [SKIP] DART_API_KEY 미설정 - 재무 데이터 생략')

    # -------------------------------------------------------------------------
    # [7단계] 기술지표 추가 (선택)
    # -------------------------------------------------------------------------
    if add_technicals and len(df) > 0:
        df = _add_technicals(df, date_str, verbose)

    if verbose:
        print(f'\n  [최종] Universe: {len(df):,}개 종목')

    if use_cache and not df.empty:
        save_cache(cache_key, df)

    return df


# ============================================================================
# [내부] 금융주 제외
# ============================================================================

def _exclude_financial(df: pd.DataFrame, verbose: bool) -> pd.DataFrame:
    """
    KRX-DESC 업종 정보 활용하여 금융주(은행/보험/증권/금융업) 제외.
    업종 정보 수집 실패 시 코드 패턴으로 대체 필터링.
    """
    import FinanceDataReader as fdr

    try:
        desc = fdr.StockListing('KRX-DESC')
        desc = desc[['Code', 'Sector', 'Industry']].copy()
        desc['Code'] = desc['Code'].astype(str).str.zfill(6)
        desc = desc.set_index('Code')

        df = df.join(desc, how='left')

        # 제외 업종 필터
        exclude_pattern = '|'.join(config.EXCLUDE_SECTORS)
        is_financial = df['Sector'].str.contains(exclude_pattern, na=False)
        n_before = len(df)
        df = df[~is_financial]

        if verbose:
            print(f'  금융주({n_before - len(df)}개) 제외 후: {len(df):,}개')

    except Exception as e:
        logger.warning('금융주 제외 실패 (%s) - 업종 필터 생략', e)

    return df


# ============================================================================
# [내부] 업종 포함 선택 필터
# ============================================================================

def _apply_sector_include(df: pd.DataFrame, verbose: bool) -> pd.DataFrame:
    """
    config.INCLUDE_SECTORS 가 비어있으면 전체 허용.
    값이 있으면 해당 업종에 속한 종목만 남김.
    Sector 컬럼이 없으면 (업종 데이터 수집 실패) 스킵.
    """
    if not config.INCLUDE_SECTORS:
        return df

    if 'Sector' not in df.columns:
        if verbose:
            print('  [SKIP] INCLUDE_SECTORS 설정 있으나 Sector 컬럼 없음 - 필터 생략')
        return df

    include_pattern = '|'.join(config.INCLUDE_SECTORS)
    mask = df['Sector'].str.contains(include_pattern, na=False)
    # 화이트리스트 종목은 업종 필터에서 제외되더라도 나중에 다시 추가되므로 여기선 단순 필터
    n_before = len(df)
    df = df[mask]

    if verbose:
        print(f'  포함 업종 필터({config.INCLUDE_SECTORS}) 후: {len(df):,}개 (제외 {n_before - len(df)}개)')

    return df


# ============================================================================
# [내부] 화이트리스트 / 블랙리스트 적용
# ============================================================================

def _apply_whitelist_blacklist(df: pd.DataFrame, verbose: bool) -> pd.DataFrame:
    """
    WHITELIST: 지정 종목을 Universe에 강제 포함 (원본 raw listing에서 가져옴).
    BLACKLIST: 지정 종목을 항상 제외.
    순서: 화이트리스트 추가 -> 블랙리스트 제거.
    """
    # 블랙리스트 제거
    if config.BLACKLIST:
        blacklist = [str(c).zfill(6) for c in config.BLACKLIST]
        before = len(df)
        df = df[~df.index.isin(blacklist)]
        removed = before - len(df)
        if verbose and removed > 0:
            print(f'  블랙리스트 {removed}개 종목 제외')

    # 화이트리스트 강제 포함
    if config.WHITELIST:
        whitelist = [str(c).zfill(6) for c in config.WHITELIST]
        missing = [c for c in whitelist if c not in df.index]
        if missing:
            try:
                import FinanceDataReader as fdr
                raw = get_stock_listing('KRX', use_cache=True)
                raw = raw.set_index('Code')
                add_rows = raw.loc[[c for c in missing if c in raw.index]]
                df = pd.concat([df, add_rows])
                df = df[~df.index.duplicated(keep='first')]
                if verbose:
                    print(f'  화이트리스트 {len(add_rows)}개 종목 강제 포함')
            except Exception as e:
                logger.warning('화이트리스트 추가 실패: %s', e)

    return df


# ============================================================================
# [내부] DART 재무 데이터 부착
# ============================================================================

def _add_financials(df: pd.DataFrame, as_of_date: str, use_cache: bool, verbose: bool) -> pd.DataFrame:
    """
    Universe 종목 전체에 DART 재무 데이터를 배치 수집하여 컬럼으로 부착.

    finstate_all 사용으로 단일 보고서에 TTM(thstrm_add_amount)이 포함되어 있어
    1회 수집으로 충분. (연간 보고서 추가 수집 불필요)

    부착 컬럼:
      분기 누적:    sales, gross_profit, op_profit, net_profit, operating_cf
      잔액:        equity, total_assets
      전년 동기:    sales_prev, gross_profit_prev, op_profit_prev, net_profit_prev
      TTM:         sales_ttm, gross_profit_ttm, op_profit_ttm, net_profit_ttm, operating_cf_ttm
      당기 별칭:    sales_cur, gross_profit_cur, op_profit_cur (성장률 팩터용)
    """
    # 보고서 공시 마감: 1Q 5/15, 2Q(반기) 8/14, 3Q 11/14, 연간 3/31
    # 마감 + 1.5개월 여유로 안정적인 직전 분기 선택
    ref_date = pd.Timestamp(as_of_date)
    year, month = ref_date.year, ref_date.month

    if month <= 5:
        fin_year, fin_quarter = year - 1, 3
    elif month <= 6:
        fin_year, fin_quarter = year - 1, 4
    elif month <= 8:
        fin_year, fin_quarter = year, 1
    elif month <= 11:
        fin_year, fin_quarter = year, 2
    else:
        fin_year, fin_quarter = year, 3

    if verbose:
        print(f'\n  DART 재무 수집 ({fin_year}Q{fin_quarter} 보고서, finstate_all)...')

    tickers = list(df.index)
    fin_df = get_financial_batch(
        tickers=tickers,
        year=fin_year,
        quarter=fin_quarter,
        use_cache=use_cache,
        verbose=verbose,
    )

    if fin_df.empty:
        if verbose:
            print('  [SKIP] 재무 데이터 수집 실패')
        return df

    # Universe에 재무 컬럼 병합
    fin_cols = [
        # 분기 누적
        'sales', 'gross_profit', 'op_profit', 'net_profit', 'operating_cf',
        # 잔액
        'equity', 'total_assets',
        # 당기 별칭 (성장률 팩터용)
        'sales_cur', 'gross_profit_cur', 'op_profit_cur',
        # 전년 동기
        'sales_prev', 'gross_profit_prev', 'op_profit_prev', 'net_profit_prev',
        'operating_cf_prev',
        # TTM (DART thstrm_add_amount 직접 사용)
        'sales_ttm', 'gross_profit_ttm', 'op_profit_ttm', 'net_profit_ttm', 'operating_cf_ttm',
    ]
    available = [c for c in fin_cols if c in fin_df.columns]
    df = df.join(fin_df[available], how='left')

    # 0값은 NaN으로 변환 (수집 실패 종목 구분)
    for col in available:
        df[col] = pd.to_numeric(df[col], errors='coerce').replace(0, np.nan)

    # -------------------------------------------------------------------------
    # [CF TTM 역산] DART CF는 thstrm_add_amount 미제공 -> 직접 역산
    # operating_cf_ttm = operating_cf(분기누적) + 전년연간 - 전년동기누적(operating_cf_prev)
    # 분기보고서가 연간(quarter==4)이면 분기누적 자체가 TTM
    #
    # 비용 최적화: PCR_TTM 팩터가 활성(config.FACTORS에 포함)일 때만 수행.
    #   - 활성 아니면 전년 연간 보고서 1700+종목 추가 수집(~5~10분) 생략
    #   - 첫 백테스트에서 PCR_TTM 비활성이라면 이 단계가 가장 큰 시간 절약
    # -------------------------------------------------------------------------
    cf_ttm_needed = 'PCR_TTM' in config.FACTORS
    if 'operating_cf_ttm' not in df.columns and 'operating_cf' in df.columns and cf_ttm_needed:
        if fin_quarter == 4:
            df['operating_cf_ttm'] = df['operating_cf']
        else:
            if verbose:
                print(f'\n  CF TTM 역산을 위한 전년 연간 ({fin_year - 1}) 추가 수집...')
            fin_ann = get_financial_batch(
                tickers=tickers,
                year=fin_year - 1,
                quarter=4,
                use_cache=use_cache,
                verbose=verbose,
            )
            if not fin_ann.empty and 'operating_cf' in fin_ann.columns:
                ann_cf = pd.to_numeric(fin_ann['operating_cf'], errors='coerce').replace(0, np.nan)
                ann_cf = ann_cf.reindex(df.index)
                # operating_cf_prev = 분기 보고서의 frmtrm_q (전년 동기 누적)
                prev_q = df.get('operating_cf_prev', pd.Series(np.nan, index=df.index))
                df['operating_cf_ttm'] = df['operating_cf'] + ann_cf - prev_q
    elif not cf_ttm_needed and verbose:
        print(f'  [SKIP] PCR_TTM 비활성 - CF TTM 역산 생략 (시간 절약)')

    valid_q    = df['sales'].notna().sum()        if 'sales' in df.columns        else 0
    valid_ttm  = df['sales_ttm'].notna().sum()    if 'sales_ttm' in df.columns    else 0
    valid_eq   = df['equity'].notna().sum()       if 'equity' in df.columns       else 0
    valid_cf   = df['operating_cf'].notna().sum() if 'operating_cf' in df.columns else 0
    valid_cfttm = df['operating_cf_ttm'].notna().sum() if 'operating_cf_ttm' in df.columns else 0
    if verbose:
        print(f'  재무 유효 종목: 분기 {valid_q} | TTM {valid_ttm} | 자본 {valid_eq} | 영업CF {valid_cf} | 영업CF_TTM {valid_cfttm} (총 {len(df)})')

    return df


# ============================================================================
# [내부] 기술지표 계산 후 Universe에 컬럼 추가
# ============================================================================

def _add_technicals(df: pd.DataFrame, as_of_date: str, verbose: bool) -> pd.DataFrame:
    """
    Universe 종목별 OHLCV 수집 → RSI/MACD_Hist/Volume_Ratio 계산 → 컬럼 추가.
    수집 실패 종목은 NaN으로 처리 (제외하지 않음).
    """
    end_date = as_of_date
    start_date = (pd.Timestamp(as_of_date) - timedelta(days=60)).strftime('%Y-%m-%d')

    records = {}
    total = len(df)
    if verbose:
        print(f'\n  기술지표 계산 중 ({total}개 종목)...', end='', flush=True)

    for i, code in enumerate(df.index):
        try:
            price_df = get_price(code, start_date, end_date, use_cache=True)
            ind = calc_indicators(price_df)
            records[code] = ind
        except Exception:
            records[code] = {}

        if verbose and (i + 1) % 100 == 0:
            print(f' {i+1}', end='', flush=True)

    if verbose:
        print(' 완료')

    tech_df = pd.DataFrame(records).T
    tech_df.index.name = 'Code'

    for col in ['RSI', 'MACD_Hist', 'BB_Width', 'Above_MA20', 'Volume_Ratio']:
        if col in tech_df.columns:
            df[col] = tech_df[col]

    return df


# ============================================================================
# [단독 실행] Universe 생성 확인
# ============================================================================

if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)

    print('=' * 60)
    print('universe.py - Universe 생성 확인')
    print('=' * 60)

    # 기술지표 없이 빠르게 먼저 확인
    universe = get_universe(add_technicals=False, use_cache=False, verbose=True)

    if not universe.empty:
        print(f'\n컬럼: {list(universe.columns)}')
        print(f'\n상위 10개 종목 (시총 기준):')
        top = universe.nlargest(10, 'MarketCap')[['Name', 'MarketCap', 'Close', 'Volume']]
        for code, row in top.iterrows():
            print(f'  {code} {row["Name"]:<15} 시총 {row["MarketCap"]/1e8:>8.0f}억 | {row["Close"]:,}원')

        print(f'\n하위 10개 종목 (시총 기준):')
        bot = universe.nsmallest(10, 'MarketCap')[['Name', 'MarketCap', 'Close', 'Volume']]
        for code, row in bot.iterrows():
            print(f'  {code} {row["Name"]:<15} 시총 {row["MarketCap"]/1e8:>8.0f}억 | {row["Close"]:,}원')

        print(f'\n시총 분포:')
        print(f'  평균: {universe["MarketCap"].mean()/1e8:.0f}억')
        print(f'  중앙값: {universe["MarketCap"].median()/1e8:.0f}억')
        print(f'  최소: {universe["MarketCap"].min()/1e8:.0f}억')
        print(f'  최대: {universe["MarketCap"].max()/1e8:.0f}억')

    print(f'\n[OK] universe.py 확인 완료')
    print('=' * 60)
