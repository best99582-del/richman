# ============================================================================
# korea_quant/reports/report.py
# ============================================================================
# 역할: 백테스트 결과 성과 리포트 생성 (quantstats 기반)
#   - CAGR, MDD, 샤프, 승률
#   - 벤치마크(KOSPI ETF) 대비 초과 수익
#   - 연도별 수익률
#   - HTML 리포트 저장
# ============================================================================

import sys
import os
import logging

import pandas as pd
import numpy as np
import FinanceDataReader as fdr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from configs import config

logger = logging.getLogger(__name__)


# ============================================================================
# [벤치마크] KOSPI ETF 수익률 수집
# ============================================================================

def get_benchmark_returns(start: str, end: str) -> pd.Series:
    """
    KODEX 200 ETF (069500) 일별 수익률 반환.
    수집 실패 시 빈 Series.
    """
    try:
        df = fdr.DataReader(config.BENCHMARK_TICKER, start, end)
        returns = df['Close'].pct_change().dropna()
        returns.name = 'KOSPI200'
        return returns
    except Exception as e:
        logger.warning('벤치마크 수익률 수집 실패: %s', e)
        return pd.Series(dtype=float)


# ============================================================================
# [핵심] 성과 지표 계산
# ============================================================================

def calc_stats(returns: pd.Series) -> dict:
    """
    일별 수익률 Series → 주요 성과 지표 dict 반환.

    Args:
        returns: 일별 전략 수익률 (소수점, 예: 0.012 = 1.2%)

    Returns:
        dict — cagr, mdd, sharpe, win_rate, total_return, volatility
    """
    if returns is None or returns.empty:
        return {}

    returns = returns.dropna()
    cum = (1 + returns).cumprod()
    total_return = cum.iloc[-1] - 1
    years = (returns.index[-1] - returns.index[0]).days / 365.25
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0

    # MDD
    rolling_max = cum.cummax()
    drawdown = (cum - rolling_max) / rolling_max
    mdd = drawdown.min()

    # 샤프 (무위험 수익률 0% 가정, 연환산)
    volatility = returns.std() * np.sqrt(252)
    sharpe = (cagr / volatility) if volatility > 0 else 0.0

    # 승률 (일 기준)
    win_rate = (returns > 0).mean()

    return {
        'total_return': total_return,
        'cagr': cagr,
        'mdd': mdd,
        'sharpe': sharpe,
        'win_rate': win_rate,
        'volatility': volatility,
        'years': years,
    }


# ============================================================================
# [출력] 콘솔 리포트
# ============================================================================

def print_report(returns: pd.Series, benchmark_returns: pd.Series | None = None):
    """
    성과 지표 콘솔 출력.

    Args:
        returns:           전략 일별 수익률
        benchmark_returns: 벤치마크 일별 수익률 (None이면 생략)
    """
    stats = calc_stats(returns)
    if not stats:
        print('[WARNING] 수익률 데이터 없음')
        return

    print('\n' + '=' * 55)
    print('  성과 리포트')
    print('=' * 55)
    print(f'  분석 기간:   {returns.index[0].date()} ~ {returns.index[-1].date()} ({stats["years"]:.1f}년)')
    print(f'  누적 수익:   {stats["total_return"]:+.1%}')
    print(f'  CAGR:        {stats["cagr"]:+.1%}')
    print(f'  MDD:         {stats["mdd"]:.1%}')
    print(f'  샤프 지수:   {stats["sharpe"]:.2f}')
    print(f'  변동성:      {stats["volatility"]:.1%} (연환산)')
    print(f'  일 승률:     {stats["win_rate"]:.1%}')

    if benchmark_returns is not None and not benchmark_returns.empty:
        b_stats = calc_stats(benchmark_returns)
        if b_stats:
            excess_cagr = stats['cagr'] - b_stats['cagr']
            print(f'\n  --- 벤치마크(KOSPI200) 비교 ---')
            print(f'  벤치마크 CAGR:   {b_stats["cagr"]:+.1%}')
            print(f'  초과 수익 (CAGR): {excess_cagr:+.1%}')
            print(f'  벤치마크 MDD:    {b_stats["mdd"]:.1%}')

    # 연도별 수익률
    print(f'\n  연도별 수익률:')
    try:
        annual = returns.resample('YE').apply(lambda x: (1 + x).prod() - 1)
        for date, ret in annual.items():
            bar = ('+'  * int(abs(ret) * 30)) if ret >= 0 else ('-' * int(abs(ret) * 30))
            sign = '+' if ret >= 0 else ''
            print(f'    {date.year}: {sign}{ret:.1%}  {bar[:30]}')
    except Exception:
        pass

    print('=' * 55)


# ============================================================================
# [HTML] quantstats 리포트 저장
# ============================================================================

def save_html_report(
    returns: pd.Series,
    benchmark_returns: pd.Series | None = None,
    output_path: str | None = None,
):
    """
    quantstats HTML 리포트 저장.

    Args:
        returns:          전략 일별 수익률
        benchmark_returns: 벤치마크 수익률
        output_path:      저장 경로 (None이면 reports/report.html)
    """
    try:
        import quantstats as qs
    except ImportError:
        print('[WARNING] quantstats 미설치. pip install quantstats')
        return

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    path = output_path or os.path.join(config.REPORT_DIR, 'report.html')

    try:
        if benchmark_returns is not None and not benchmark_returns.empty:
            qs.reports.html(
                returns,
                benchmark=benchmark_returns,
                output=path,
                title='korea_quant 팩터 전략',
            )
        else:
            qs.reports.html(
                returns,
                output=path,
                title='korea_quant 팩터 전략',
            )
        print(f'[OK] HTML 리포트 저장: {path}')
    except Exception as e:
        logger.error('HTML 리포트 저장 실패: %s', e)


# ============================================================================
# [단독 실행] 샘플 수익률로 리포트 테스트
# ============================================================================

if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)

    print('=' * 55)
    print('report.py - 성과 리포트 확인')
    print('=' * 55)

    # 샘플 수익률 생성 (실제 백테스트 결과 대신)
    np.random.seed(42)
    dates = pd.date_range('2021-01-01', '2024-12-31', freq='B')
    sample_returns = pd.Series(
        np.random.normal(0.0006, 0.012, len(dates)),
        index=dates,
        name='strategy'
    )

    benchmark = get_benchmark_returns('2021-01-01', '2024-12-31')

    print_report(sample_returns, benchmark)

    print('\n[OK] report.py 확인 완료')
    print('=' * 55)
