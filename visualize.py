# ============================================================================
# 🎨 [퀀트 유니버스] 전략 시각화 보드 (visualize.py)
# ============================================================================
# 역할: 5단 지표 패널 + 국면 배경색 + 매매 타점을 시각화하여 전략을 직관적으로 검증
# 파이프라인 위치: [6단계] 시각화
# 의존성: config.py, ta.py, predict.py, backtest.py
#
# 차트 구성:
#   [Panel 0] 캔들차트 + 볼린저밴드 + MA20 + 매수/매도 마커 + 트레일링 스탑
#   [Panel 1] MACD + Signal + Histogram
#   [Panel 2] RSI + 과매수/과매도 기준선
#   [Panel 3] Stochastic (Slow_K / Slow_D)
#   [Panel 4] ADX + 횡보 판단 임계선
#   [배경] 국면별 색상 (Bull: 그린, Sideways: 오렌지, Bear: 라벤더)
# ============================================================================

import logging

import numpy as np
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt

import config
from ta import Make_Indicators
from predict import Add_AI_Signals
from backtest import Backtest_Strategy, Get_Trade_Decision

# --- 로거 설정 ---
logger = logging.getLogger(__name__)


# ============================================================================
# [핵심 함수] 전략 시각화
# ============================================================================

def Plot_Strategy(
    ticker: str = None,
    df_input: pd.DataFrame = None,
    start_date: str = config.START_DATE,
    trade_log: pd.DataFrame = None
):
    """
    주가 + 국면 배경 + 매매 타점 + 주요 지표를 5단 패널 차트로 시각화합니다.
    
    두 가지 사용 방식:
        1. 직접 호출: ticker만 전달 → 데이터 다운로드 + 지표 산출 + 매매 시뮬 + 차트
        2. 파이프라인 연동: df_input + trade_log 전달 → 이미 계산된 결과를 시각화만
    
    Args:
        ticker: 종목 티커 (df_input이 None일 때 데이터 다운로드용)
        df_input: 지표 + AI 신호가 부착된 DataFrame
        start_date: 데이터 시작일
        trade_log: backtest.py에서 반환된 매매 일지 DataFrame
                   None이면 내부에서 매매 시뮬레이션 수행
    """
    display_name = ticker if ticker else 'DataFrame'
    print(f"🎨 [{display_name}] 전략 분석 차트 생성 중...")

    # --- [1] 데이터 준비 ---
    if df_input is None:
        from data_loader import load_ohlcv
        df = load_ohlcv(ticker, start=start_date)
        df = Make_Indicators(df)
        df = Add_AI_Signals(df)
        df = df.dropna()
    else:
        df = df_input.copy()

    # --- [2] 매매 신호 추출 (trade_log 기반 또는 자체 시뮬레이션) ---
    buy_signals, sell_signals, trailing_stops, total_return = _extract_signals(
        df, ticker, trade_log
    )

    # --- [3] 차트 스타일 설정 ---
    mc = mpf.make_marketcolors(
        up=config.CHART_UP_COLOR,
        down=config.CHART_DOWN_COLOR,
        edge='inherit', wick='inherit', volume='in'
    )
    style = mpf.make_mpf_style(
        marketcolors=mc, gridstyle='--', y_on_right=False
    )

    # --- [4] 추가 지표 레이어 구성 ---
    apds = [
        # [Main Panel] 볼린저밴드 + MA20
        mpf.make_addplot(df['Upper'], color='#BBBBBB', alpha=0.3),
        mpf.make_addplot(df['Lower'], color='#BBBBBB', alpha=0.3),
        mpf.make_addplot(df['MA20'], color='blue', alpha=0.4, width=1),

        # [Main Panel] 트레일링 스탑 라인 + 매수/매도 마커
        mpf.make_addplot(
            trailing_stops, type='scatter',
            color='orange', markersize=3, alpha=0.6
        ),
        mpf.make_addplot(
            buy_signals, type='scatter',
            markersize=120, marker='^', color='#2ECC71'
        ),
        mpf.make_addplot(
            sell_signals, type='scatter',
            markersize=120, marker='v', color='#E74C3C'
        ),

        # [Panel 1] MACD (모멘텀 전환)
        mpf.make_addplot(df['MACD'], panel=1, color='orange', ylabel='MACD'),
        mpf.make_addplot(df['MACD_Signal'], panel=1, color='blue'),
        mpf.make_addplot(
            df['MACD_Hist'], type='bar', panel=1, color='gray', alpha=0.3
        ),

        # [Panel 2] RSI (과매수/과매도)
        mpf.make_addplot(
            df['RSI'], panel=2, color='#9B59B6',
            ylabel='RSI', ylim=(0, 100)
        ),
        mpf.make_addplot(
            np.full(len(df), 70), panel=2,
            color='red', alpha=0.3, linestyle='--'
        ),
        mpf.make_addplot(
            np.full(len(df), 30), panel=2,
            color='blue', alpha=0.3, linestyle='--'
        ),

        # [Panel 3] Stochastic (횡보장 보조 신호)
        mpf.make_addplot(df['Slow_K'], panel=3, color='#F1C40F', ylabel='Stoch'),
        mpf.make_addplot(df['Slow_D'], panel=3, color='#3498DB'),

        # [Panel 4] ADX (추세 강도 참고)
        mpf.make_addplot(
            df['ADX'], panel=4, color='black',
            ylabel='ADX', ylim=(0, 60)
        ),
        mpf.make_addplot(
            np.full(len(df), 25), panel=4,
            color='gray', alpha=0.3, linestyle='--'
        ),
    ]

    # --- [5] 차트 렌더링 ---
    return_pct = (total_return - 1) * 100
    fig, axes = mpf.plot(
        df, type='candle', style=style, addplot=apds,
        title=f'\n{display_name} AI Alpha Strategy Viewer '
              f'(Total Return: {return_pct:.1f}%)',
        ylabel='Price', volume=True,
        figratio=(16, 12), tight_layout=True,
        show_nontrading=False, returnfig=True
    )

    print(f"✅ [{display_name}] 분석 차트 렌더링 완료.")
    plt.show()


# ============================================================================
# [내부 유틸리티] 매매 신호 추출
# ============================================================================

def _extract_signals(
    df: pd.DataFrame,
    ticker: str,
    trade_log: pd.DataFrame = None
) -> tuple:
    """
    매매 타점(매수/매도 마커)과 트레일링 스탑 라인을 추출합니다.
    
    trade_log가 있으면 backtest 결과를 그대로 사용하여 로직 중복을 방지.
    없으면 자체적으로 Get_Trade_Decision을 호출하여 시뮬레이션.
    
    Args:
        df: 전체 지표가 산출된 DataFrame
        ticker: 종목 티커
        trade_log: backtest.py의 매매 일지 (None이면 자체 시뮬레이션)
    
    Returns:
        tuple: (buy_signals, sell_signals, trailing_stops, total_return)
    """
    buy_signals = np.full(len(df), np.nan)
    sell_signals = np.full(len(df), np.nan)
    trailing_stops = np.full(len(df), np.nan)
    total_return = 1.0

    # --- 방법 1: trade_log 활용 (backtest 결과 재사용) ---
    if trade_log is not None and len(trade_log) > 0:
        for _, trade in trade_log.iterrows():
            # 매수 마커
            if trade['Entry_Date'] in df.index:
                idx = df.index.get_loc(trade['Entry_Date'])
                buy_signals[idx] = df['Low'].iloc[idx] * 0.97

            # 매도 마커
            if trade['Exit_Date'] in df.index:
                idx = df.index.get_loc(trade['Exit_Date'])
                sell_signals[idx] = df['High'].iloc[idx] * 1.03

            total_return *= (1 + trade['Return'])

        # 트레일링 스탑은 trade_log만으로 복원이 어려우므로 간소화
        # (향후 backtest에서 daily_stop을 기록하면 정확한 복원 가능)
        return buy_signals, sell_signals, trailing_stops, total_return

    # --- 방법 2: 자체 시뮬레이션 (trade_log 없을 때) ---
    params = {
        'rsi_buy': config.RSI_BUY,
        'rsi_sell': config.RSI_SELL,
        'bb_squeeze_ratio': config.BB_SQUEEZE_RATIO,
        'ai_filter': config.AI_FILTER,
        'trailing_atr_mult': config.TRAILING_ATR_MULT,
    }

    in_position = False
    entry_price = 0.0
    highest_price = 0.0
    active_stop_price = 0.0

    for i in range(1, len(df)):
        decision = Get_Trade_Decision(i, df, params)
        current_price = df['Close'].iloc[i]

        # 진입
        if decision == 1 and not in_position:
            buy_signals[i] = df['Low'].iloc[i] * 0.97
            entry_price = current_price * (1 + config.FEE_RATE)
            active_stop_price = current_price - (
                df['ATR'].iloc[i] * config.ATR_STOP_MULTIPLIER
            )
            highest_price = current_price
            in_position = True

        # 보유 중
        elif in_position:
            if current_price > highest_price:
                highest_price = current_price

            # Chandelier Exit 트레일링 스탑
            current_atr = df['ATR'].iloc[i]
            ts_price = highest_price - (current_atr * params['trailing_atr_mult'])
            trailing_stops[i] = ts_price

            # 청산 조건
            should_exit = (
                decision == -1 or
                current_price <= active_stop_price or
                current_price <= ts_price
            )

            if should_exit:
                sell_signals[i] = df['High'].iloc[i] * 1.03
                exit_price = current_price * (1 - config.FEE_RATE)
                trade_ret = (exit_price / entry_price) - 1
                total_return *= (1 + trade_ret)
                in_position = False

    return buy_signals, sell_signals, trailing_stops, total_return


# ============================================================================
# [테스트] 단독 실행
# ============================================================================

if __name__ == "__main__":
    target_ticker = config.TICKERS[0]

    # 방법 1: 단독 시각화 (자체 시뮬레이션)
    Plot_Strategy(target_ticker, start_date='2023-06-01')

    # 방법 2: backtest 결과 연동 시각화 (권장)
    # result = Backtest_Strategy(target_ticker)
    # if result['trade_count'] > 0:
    #     Plot_Strategy(target_ticker, trade_log=result['trade_log'])