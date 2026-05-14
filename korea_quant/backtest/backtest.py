# ============================================================================
# korea_quant/backtest/backtest.py
# ============================================================================
# 역할:
#   시점별 동적 리밸런싱 백테스트 엔진 (vectorbt 기반).
#   분기/월 단위 리밸런싱 날짜마다 Universe 재구성 → 팩터 스코어링 → TOP_N 선별 →
#   비중 산출 → vectorbt 시뮬레이션 → 성과 지표 산출.
#
# 처리 흐름:
#   [1] get_rebalance_dates()      - 분기/월 말 영업일 자동 생성
#   [2] 각 리밸런싱 시점마다
#         get_universe(as_of_date=date)   - 그 시점 기준 Universe (시점별 동적)
#         score_universe()                - 팩터 스코어링
#         select_portfolio()              - TOP_N + 비중
#       → {date: {ticker: weight}} 이력 누적
#   [3] get_price_matrix()         - 전체 후보 종목 일별 종가
#   [4] _build_size_df()           - 날짜 × 종목 비중 행렬 (리밸런싱 날만 비중 입력)
#   [5] vectorbt Portfolio.from_orders(size_type='targetpercent')
#       → 회전율 효율적 매매 자동 처리 (기존 보유 중 새 비중과 차이 나는 만큼만 매매)
#   [6] 성과 지표 (CAGR, MDD, Sharpe, 연도별 수익률, 회전율) + 벤치마크 비교
#   [7] CSV 저장
#
# Survivorship Bias 한계 (Phase 5 의 옵션 A):
#   FDR StockListing은 현재 시점 시총/거래량만 제공.
#   과거 시점 백테스트라도 종목 리스트는 현재 살아있는 종목으로 한정됨.
#   결과 출력 첫 줄에 명시. Phase 8에서 옵션 C (DART corp_code 시계열)로 보강 예정.
#
# 수수료 처리:
#   vectorbt fees 파라미터는 단일값 (매수/매도 분리 미지원).
#   현재는 평균값 (fee_buy + fee_sell)/2 적용. 정확한 분리는 Phase 6 검토.
# ============================================================================

import sys
import os
import logging
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from configs import config
from data.data_loader import get_price_matrix, get_price, get_financial_batch
from universe.universe import get_universe
from scoring.scorer import score_universe, select_portfolio

logger = logging.getLogger(__name__)


# ============================================================================
# [내부] 사전 수집 — 리밸런싱 날짜들이 필요로 하는 DART 분기 조합 일괄 수집
# ============================================================================

def _resolve_fin_quarter(as_of_date: str) -> tuple:
    """
    as_of_date → (fin_year, fin_quarter).
    universe._add_financials() 의 분기 결정 로직과 동일.

    공시 마감일 + 1.5개월 여유로 직전 분기 보고서 사용:
      1~5월  : 직전 연도 3Q
      6월    : 직전 연도 연간 (4Q)
      7~8월  : 당해 1Q
      9~11월 : 당해 2Q (반기)
      12월   : 당해 3Q
    """
    ref = pd.Timestamp(as_of_date)
    y, m = ref.year, ref.month
    if m <= 5:   return y - 1, 3
    if m <= 6:   return y - 1, 4
    if m <= 8:   return y,     1
    if m <= 11:  return y,     2
    return y, 3


def _prefetch_financials(tickers: list, rebal_dates: list, verbose: bool = True):
    """
    백테스트 시작 전 모든 리밸런싱 날짜가 필요로 하는 분기 보고서를 일괄 수집.
    같은 분기를 여러 리밸런싱 시점이 공유할 때 캐시 1회 생성 후 재활용 가능하게 함.

    PCR_TTM 팩터가 활성이면 CF TTM 역산용 연간 보고서도 추가 수집.
    """
    # 필요한 (year, quarter) 조합 수집
    needed = set()
    for date_str in rebal_dates:
        needed.add(_resolve_fin_quarter(date_str))

    # PCR_TTM 활성이면 분기 보고서마다 fin_year - 1 연간도 필요
    if 'PCR_TTM' in config.FACTORS:
        ann_needed = set()
        for (fy, fq) in needed:
            if fq != 4:
                ann_needed.add((fy - 1, 4))
        needed |= ann_needed

    # 분기 시간순 정렬
    needed_sorted = sorted(needed)

    if verbose:
        print(f'\n[사전 수집] 필요한 보고서 {len(needed_sorted)}종 일괄 수집')
        for (y, q) in needed_sorted:
            label = '연간' if q == 4 else f'Q{q}'
            print(f'  - {y}{label}')

    for i, (year, quarter) in enumerate(needed_sorted, 1):
        if verbose:
            label = '연간' if quarter == 4 else f'Q{quarter}'
            print(f'\n  [{i}/{len(needed_sorted)}] {year}{label} 수집...')
        get_financial_batch(
            tickers=tickers,
            year=year,
            quarter=quarter,
            use_cache=True,
            verbose=verbose,
        )


# ============================================================================
# [유틸] 리밸런싱 날짜 생성
# ============================================================================

def get_rebalance_dates(start: str, end: str, freq: str = 'Q') -> list:
    """
    리밸런싱 날짜 목록 생성 (분기 말 또는 월 말 영업일).

    Args:
        start, end : 'YYYY-MM-DD' 문자열
        freq       : 'Q' 분기 / 'M' 월간

    Returns:
        list of 'YYYY-MM-DD' 문자열. 주말이면 직전 영업일로 조정.
    """
    idx = pd.date_range(start=start, end=end, freq=f'{freq}E')  # Q말 / M말
    dates = []
    for d in idx:
        # 주말이면 앞쪽 영업일로 (월요일 → 금요일)
        while d.weekday() >= 5:
            d -= pd.Timedelta(days=1)
        dates.append(d.strftime('%Y-%m-%d'))
    return dates


# ============================================================================
# [내부] 비중 DataFrame 구성
# ============================================================================

def _build_size_df(
    price_index: pd.DatetimeIndex,
    tickers: list,
    history: dict,
    rebal_dates: list,
) -> pd.DataFrame:
    """
    날짜 × 종목 비중 행렬 생성.
    리밸런싱 날짜에만 새 비중 입력, 나머지 날짜는 NaN (vectorbt가 hold로 해석).

    Args:
        price_index : 가격 매트릭스의 DatetimeIndex
        tickers     : 전체 후보 종목 리스트
        history     : {date_str: {ticker: weight}} 시점별 비중 이력
        rebal_dates : 리밸런싱 날짜 문자열 리스트

    Returns:
        DataFrame (index=날짜, columns=ticker, 대부분 NaN)
    """
    size_df = pd.DataFrame(np.nan, index=price_index, columns=tickers)

    for date_str in rebal_dates:
        weights = history.get(date_str, {})
        if not weights:
            continue

        # 해당 날짜가 거래일이 아니면 그 이후 첫 거래일로
        target_dt = pd.Timestamp(date_str)
        valid_dates = price_index[price_index >= target_dt]
        if valid_dates.empty:
            continue
        actual_date = valid_dates[0]

        # 그 날짜에 전체 종목 비중 입력 (TOP_N 외 종목은 0)
        row = pd.Series(0.0, index=tickers)
        for ticker, w in weights.items():
            if ticker in row.index:
                row[ticker] = w
        size_df.loc[actual_date] = row

    return size_df


# ============================================================================
# [핵심] 백테스트 실행
# ============================================================================

def run_backtest(
    start: str = None,
    end: str = None,
    fee_buy: float = None,
    fee_sell: float = None,
    slippage: float = None,
    init_cash: float = None,
    verbose: bool = True,
) -> dict:
    """
    시점별 동적 리밸런싱 팩터 전략 백테스트.

    Args:
        start, end : 'YYYY-MM-DD' (None이면 config 기본값)
        fee_buy    : 매수 수수료 (None이면 config.FEE_BUY)
        fee_sell   : 매도 수수료 (None이면 config.FEE_SELL)
        slippage   : 슬리피지 (None이면 config.SLIPPAGE)
        init_cash  : 초기 자본금 (None이면 config.INITIAL_CAPITAL)
        verbose    : 진행 상황 출력

    Returns:
        dict - portfolio(vbt 객체), returns, total_return, cagr, mdd, sharpe,
               benchmark_cagr, alpha, turnover, history, tickers
    """
    import vectorbt as vbt

    start     = start     or config.START_DATE
    end       = end       or config.END_DATE
    fee_buy   = fee_buy   if fee_buy   is not None else config.FEE_BUY
    fee_sell  = fee_sell  if fee_sell  is not None else config.FEE_SELL
    slippage  = slippage  if slippage  is not None else config.SLIPPAGE
    init_cash = init_cash if init_cash is not None else config.INITIAL_CAPITAL

    avg_fee = (fee_buy + fee_sell) / 2

    # -------------------------------------------------------------------------
    # [1] 리밸런싱 날짜
    # -------------------------------------------------------------------------
    rebal_dates = get_rebalance_dates(start, end, config.REBALANCE_FREQ)
    if verbose:
        print('=' * 65)
        print(f'  korea_quant 백테스트')
        print(f'  기간:      {start} ~ {end}')
        print(f'  리밸런싱:  {config.REBALANCE_FREQ} ({len(rebal_dates)}회)')
        print(f'  초기자금:  {init_cash:,.0f}원')
        print(f'  수수료:    매수 {fee_buy:.2%} / 매도 {fee_sell:.2%} (평균 {avg_fee:.2%} 적용)')
        print(f'  슬리피지:  {slippage:.2%}')
        print('=' * 65)
        print('  [주의] Survivorship Bias: 현재 살아있는 종목으로 백테스트.')
        print('         결과는 낙관적으로 편향됨. Phase 8에서 보강 예정.')
        print('=' * 65)

    # -------------------------------------------------------------------------
    # [2a] 사전 수집 — 필요한 모든 DART 분기 일괄 수집 (캐시 적중률 극대화)
    # -------------------------------------------------------------------------
    if verbose:
        print(f'\n[1/7] 사전 DART 보고서 일괄 수집...')

    # tickers 후보: 현재 시점 Universe 종목 리스트로 일괄 수집
    try:
        seed_universe = get_universe(
            add_technicals=False,
            add_financials=False,
            use_cache=True,
            verbose=False,
        )
        seed_tickers = list(seed_universe.index)
        _prefetch_financials(seed_tickers, rebal_dates, verbose=verbose)
    except Exception as e:
        logger.warning('사전 수집 실패 (계속 진행): %s', e)

    # -------------------------------------------------------------------------
    # [2b] 각 리밸런싱 시점마다 Universe + 스코어링 + TOP_N + 비중
    # -------------------------------------------------------------------------
    if verbose:
        print(f'\n[2/7] 시점별 Universe 구성 + 팩터 스코어링 ({len(rebal_dates)}회)...')

    history = {}      # {date_str: {ticker: weight}}
    all_tickers = set()

    for i, date_str in enumerate(rebal_dates, 1):
        try:
            universe = get_universe(
                as_of_date=date_str,
                add_technicals=False,    # 백테스트 속도 위해 기술지표 제외
                add_financials=True,
                use_cache=True,
                verbose=False,
            )
            if universe.empty:
                logger.warning('Universe 비어있음: %s', date_str)
                history[date_str] = {}
                continue

            scored = score_universe(universe, verbose=False)
            if 'score_total' not in scored.columns or scored['score_total'].isna().all():
                logger.warning('스코어링 실패: %s', date_str)
                history[date_str] = {}
                continue

            portfolio = select_portfolio(scored, as_of_date=date_str)
            weights = portfolio['weight'].to_dict()
            history[date_str] = weights
            all_tickers.update(weights.keys())

            if verbose:
                print(f'  [{i:2d}/{len(rebal_dates)}] {date_str} → '
                      f'{len(weights)}종목 선별 (전체 후보 누적 {len(all_tickers)})')
        except Exception as e:
            logger.error('리밸런싱 시점 처리 실패 (%s): %s', date_str, e)
            history[date_str] = {}

    if not all_tickers:
        logger.error('선별된 종목 없음 - 백테스트 중단')
        return {}

    all_tickers = sorted(all_tickers)

    # -------------------------------------------------------------------------
    # [3] 가격 매트릭스
    # -------------------------------------------------------------------------
    if verbose:
        print(f'\n[3/7] 가격 데이터 수집 ({len(all_tickers)}개 종목)...')

    price_matrix = get_price_matrix(all_tickers, start, end, use_cache=True)
    if price_matrix.empty:
        logger.error('가격 데이터 수집 실패')
        return {}

    # 거래정지일 ffill, 상장 전 NaN 유지
    price_matrix = price_matrix.ffill()

    if verbose:
        print(f'  거래일 수: {len(price_matrix)}일 '
              f'({price_matrix.index[0].date()} ~ {price_matrix.index[-1].date()})')

    # -------------------------------------------------------------------------
    # [4] 비중 DataFrame 구성
    # -------------------------------------------------------------------------
    if verbose:
        print(f'\n[4/7] 비중 행렬 구성...')

    size_df = _build_size_df(price_matrix.index, list(price_matrix.columns),
                             history, rebal_dates)

    rebal_filled = size_df.notna().any(axis=1).sum()
    if verbose:
        print(f'  실제 리밸런싱 적용 날짜: {rebal_filled}회')

    # -------------------------------------------------------------------------
    # [5] vectorbt 시뮬레이션
    # -------------------------------------------------------------------------
    if verbose:
        print(f'\n[5/7] vectorbt 시뮬레이션...')

    try:
        pf = vbt.Portfolio.from_orders(
            close=price_matrix,
            size=size_df,
            size_type='targetpercent',   # 비중 기반 (회전율 효율적)
            init_cash=init_cash,
            fees=avg_fee,
            slippage=slippage,
            cash_sharing=True,
            group_by=True,
            call_seq='auto',
            freq='d',
        )
    except Exception as e:
        logger.error('vectorbt 시뮬레이션 실패: %s', e)
        return {}

    # -------------------------------------------------------------------------
    # [6] 성과 지표
    # -------------------------------------------------------------------------
    if verbose:
        print(f'\n[6/7] 성과 지표 계산...')

    returns = pf.returns()
    total_return = float(pf.total_return())
    years = (price_matrix.index[-1] - price_matrix.index[0]).days / 365.25
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0
    mdd = float(pf.max_drawdown())
    sharpe = float(pf.sharpe_ratio())

    # 회전율 (간단 추정): 리밸런싱 횟수 × 평균 종목 교체율
    turnover = _estimate_turnover(history, rebal_dates)

    # -------------------------------------------------------------------------
    # [6b] 벤치마크 비교
    # -------------------------------------------------------------------------
    bench_cagr = None
    alpha = None
    try:
        bench = get_price(config.BENCHMARK_TICKER, start, end, use_cache=True)
        if not bench.empty:
            bench_total = (bench['Close'].iloc[-1] / bench['Close'].iloc[0]) - 1
            bench_cagr = (1 + bench_total) ** (1 / years) - 1 if years > 0 else 0.0
            alpha = cagr - bench_cagr
    except Exception as e:
        logger.warning('벤치마크 수집 실패: %s', e)

    result = {
        'portfolio':     pf,
        'returns':       returns,
        'total_return':  total_return,
        'cagr':          cagr,
        'mdd':           mdd,
        'sharpe':        sharpe,
        'years':         years,
        'turnover':      turnover,
        'benchmark_cagr': bench_cagr,
        'alpha':         alpha,
        'history':       history,
        'tickers':       all_tickers,
        'price_matrix':  price_matrix,
        'fee_buy':       fee_buy,
        'fee_sell':      fee_sell,
        'slippage':      slippage,
    }

    if verbose:
        _print_stats(result)

    # -------------------------------------------------------------------------
    # [7] CSV 저장
    # -------------------------------------------------------------------------
    if verbose:
        print(f'\n[7/7] 결과 저장...')

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')

    ret_path = os.path.join(config.REPORT_DIR, f'backtest_returns_{today}.csv')
    returns.to_csv(ret_path, encoding='utf-8-sig')
    if verbose:
        print(f'  일별 수익률: {ret_path}')

    hist_path = os.path.join(config.REPORT_DIR, f'backtest_history_{today}.csv')
    hist_rows = []
    for date_str in rebal_dates:
        weights = history.get(date_str, {})
        for ticker, w in weights.items():
            hist_rows.append({'date': date_str, 'ticker': ticker, 'weight': w})
    if hist_rows:
        pd.DataFrame(hist_rows).to_csv(hist_path, index=False, encoding='utf-8-sig')
        if verbose:
            print(f'  리밸런싱 이력: {hist_path}')

    return result


# ============================================================================
# [내부] 회전율 추정
# ============================================================================

def _estimate_turnover(history: dict, rebal_dates: list) -> float:
    """
    평균 종목 교체율(%) 추정.
    연속한 두 리밸런싱 사이 종목 교체 비율의 평균.
    """
    prev_set = None
    rates = []
    for date_str in rebal_dates:
        cur_set = set(history.get(date_str, {}).keys())
        if prev_set is not None and prev_set:
            replaced = len(cur_set - prev_set)
            rate = replaced / max(len(prev_set), 1)
            rates.append(rate)
        prev_set = cur_set
    return float(np.mean(rates)) if rates else 0.0


# ============================================================================
# [출력] 성과 요약
# ============================================================================

def _print_stats(result: dict):
    print('\n' + '=' * 65)
    print('  백테스트 성과 요약')
    print('=' * 65)
    print(f'  기간:        {result["years"]:.1f}년')
    print(f'  누적 수익:   {result["total_return"]:+.1%}')
    print(f'  CAGR:        {result["cagr"]:+.1%}')
    if result.get('benchmark_cagr') is not None:
        print(f'  벤치마크:    {result["benchmark_cagr"]:+.1%} (KODEX 200)')
        print(f'  알파:        {result["alpha"]:+.1%}')
    print(f'  MDD:         {result["mdd"]:.1%}')
    print(f'  샤프 지수:   {result["sharpe"]:.2f}')
    print(f'  평균 회전율: {result["turnover"]:.1%} (리밸런싱당 종목 교체율)')
    print('=' * 65)

    # 연도별 수익률
    try:
        annual = result['returns'].resample('YE').apply(lambda x: (1 + x).prod() - 1)
        print('\n  연도별 수익률:')
        for date, ret in annual.items():
            bar = '+' * min(int(abs(ret) * 30), 30) if ret >= 0 else '-' * min(int(abs(ret) * 30), 30)
            sign = '+' if ret >= 0 else ''
            print(f'    {date.year}: {sign}{ret:.1%}  {bar}')
    except Exception as e:
        logger.debug('연도별 수익률 출력 실패: %s', e)


# ============================================================================
# [단독 실행]
# ============================================================================

if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)

    result = run_backtest(
        start='2021-01-01',
        end='2024-12-31',
        verbose=True,
    )

    if result:
        print('\n[OK] 백테스트 완료')
    else:
        print('\n[FAIL] 백테스트 실패 - 로그 확인')
