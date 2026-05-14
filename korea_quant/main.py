# ============================================================================
# korea_quant/main.py
# ============================================================================
# 역할: 전체 파이프라인 진입점 (CLI)
#
# 실행 모드:
#   python main.py backtest  → 시점별 동적 리밸런싱 백테스트
#   python main.py screen    → 현재 시점 전략 부합 종목 추출
#   python main.py report    → 기존 백테스트 결과로 성과 리포트 생성
#   python main.py all       → backtest → report 순서로 전체 실행
#
# 공통 옵션:
#   --start YYYY-MM-DD    백테스트 시작일 (기본: config.START_DATE)
#   --end   YYYY-MM-DD    백테스트 종료일 (기본: config.END_DATE)
#   --top   N             스크리닝 선별 종목 수 (기본: config.TOP_N)
#   --no-tech             기술적 지표 제외 (스크리닝 속도 향상)
#   --html                quantstats HTML 리포트 저장
#
# 백테스트 전용 옵션 (config 기본값 일회성 오버라이드):
#   --fee-buy   F         매수 수수료 (기본: config.FEE_BUY)
#   --fee-sell  F         매도 수수료 (기본: config.FEE_SELL)
#   --slippage  F         슬리피지 (기본: config.SLIPPAGE)
#   --init-cash N         초기 자본금 (기본: config.INITIAL_CAPITAL)
# ============================================================================

import sys
import os
import logging
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from configs import config

logger = logging.getLogger(__name__)


# ============================================================================
# [모드 1] 백테스트
# ============================================================================

def run_backtest_mode(args):
    """백테스트 모드. CLI 인자로 수수료/슬리피지/초기자금 오버라이드 가능."""
    from backtest.backtest import run_backtest

    result = run_backtest(
        start     = args.start,
        end       = args.end,
        fee_buy   = args.fee_buy,
        fee_sell  = args.fee_sell,
        slippage  = args.slippage,
        init_cash = args.init_cash,
        verbose   = True,
    )

    if not result:
        print('[FAIL] 백테스트 실패')
        return

    # HTML 리포트 옵션 (quantstats - Phase 9에서 본격 구현)
    if args.html:
        try:
            from reports.report import save_html_report, get_benchmark_returns
            returns = result.get('returns')
            if returns is not None and not returns.empty:
                start = args.start or config.START_DATE
                end   = args.end   or config.END_DATE
                benchmark = get_benchmark_returns(start, end)
                save_html_report(returns, benchmark)
        except Exception as e:
            print(f'[WARNING] HTML 리포트 생성 실패: {e}')

    print('\n[OK] 백테스트 완료')


# ============================================================================
# [모드 2] 스크리닝
# ============================================================================

def run_screen_mode(args):
    from screener.screener import run_screener

    result = run_screener(
        top_n=args.top,
        add_technicals=not args.no_tech,
        save_csv=True,
        verbose=True,
    )

    if result.empty:
        print('[FAIL] 스크리닝 결과 없음')
    else:
        print(f'\n[OK] 스크리닝 완료 - {len(result)}개 종목')


# ============================================================================
# [모드 3] 리포트
# ============================================================================

def run_report_mode(args):
    from reports.report import get_benchmark_returns, print_report, save_html_report
    import pandas as pd

    # 저장된 백테스트 수익률 로드
    ret_path = os.path.join(config.REPORT_DIR, 'backtest_returns.csv')

    if not os.path.exists(ret_path):
        print(f'[WARNING] 백테스트 결과 파일 없음: {ret_path}')
        print('  python main.py backtest 를 먼저 실행하세요.')
        return

    try:
        returns = pd.read_csv(ret_path, index_col=0, parse_dates=True, encoding='utf-8-sig')
        # DataFrame인 경우 첫 번째 컬럼 사용
        if isinstance(returns, pd.DataFrame):
            returns = returns.iloc[:, 0]
        returns.name = 'strategy'

        start = returns.index[0].strftime('%Y-%m-%d')
        end   = returns.index[-1].strftime('%Y-%m-%d')
        benchmark = get_benchmark_returns(start, end)

        print_report(returns, benchmark)

        if args.html:
            save_html_report(returns, benchmark)

        print('\n[OK] 리포트 완료')

    except Exception as e:
        logger.error('리포트 생성 실패: %s', e)
        print(f'[FAIL] 리포트 생성 실패: {e}')


# ============================================================================
# [모드 4] 전체 실행
# ============================================================================

def run_all_mode(args):
    print('\n=== [1/2] 백테스트 ===')
    run_backtest_mode(args)

    print('\n=== [2/2] 리포트 ===')
    run_report_mode(args)


# ============================================================================
# [진입점]
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='korea_quant 팩터 투자 시스템',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
실행 예시:
  python main.py backtest                                           # 전체 기간
  python main.py backtest --start 2021-01-01 --end 2024-12-31       # 기간 지정
  python main.py backtest --fee-buy 0.003 --fee-sell 0.0048         # 수수료 일회성
  python main.py backtest --slippage 0.002 --init-cash 100000000    # 슬리피지/자금
  python main.py screen                                             # 현재 스크리닝
  python main.py screen --top 30 --no-tech                          # 30종목, 빠르게
  python main.py report                                             # 저장된 결과 리포트
  python main.py all                                                # 백테스트+리포트
        '''
    )
    parser.add_argument(
        'mode',
        choices=['backtest', 'screen', 'report', 'all'],
        help='실행 모드'
    )
    parser.add_argument('--start', type=str, default=None, help='백테스트 시작일 YYYY-MM-DD')
    parser.add_argument('--end',   type=str, default=None, help='백테스트 종료일 YYYY-MM-DD')
    parser.add_argument('--top',   type=int, default=config.TOP_N, help=f'선별 종목 수 (기본: {config.TOP_N})')
    parser.add_argument('--no-tech', action='store_true', help='기술적 지표 제외')
    parser.add_argument('--html',    action='store_true', help='HTML 리포트 저장')
    parser.add_argument('--verbose', action='store_true', default=True, help='상세 출력')
    # 백테스트 전용: 수수료/슬리피지/초기자금 일회성 오버라이드
    parser.add_argument('--fee-buy',   type=float, default=None, help=f'매수 수수료 (기본 config.FEE_BUY={config.FEE_BUY})')
    parser.add_argument('--fee-sell',  type=float, default=None, help=f'매도 수수료 (기본 config.FEE_SELL={config.FEE_SELL})')
    parser.add_argument('--slippage',  type=float, default=None, help=f'슬리피지 (기본 config.SLIPPAGE={config.SLIPPAGE})')
    parser.add_argument('--init-cash', type=float, default=None, help=f'초기 자본금 (기본 {config.INITIAL_CAPITAL:,.0f}원)')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format='%(levelname)s | %(name)s | %(message)s',
    )

    print('=' * 65)
    print('  korea_quant 팩터 투자 시스템')
    print(f'  모드: {args.mode.upper()} | TOP {args.top}종목')
    if args.start or args.end:
        print(f'  기간: {args.start or config.START_DATE} ~ {args.end or config.END_DATE}')
    print('=' * 65)

    dispatch = {
        'backtest': run_backtest_mode,
        'screen':   run_screen_mode,
        'report':   run_report_mode,
        'all':      run_all_mode,
    }
    dispatch[args.mode](args)


if __name__ == '__main__':
    main()
