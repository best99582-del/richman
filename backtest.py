# ============================================================================
# 💹 [퀀트 유니버스] 백테스트 엔진 (backtest.py)
# ============================================================================
# 역할: 통합 기술 전략으로 과거 매매를 시뮬레이션하고 성과를 검증
# 파이프라인 위치: [5단계] 시뮬레이션
# 의존성: config.py, ta.py, predict.py, kelly.py
#
# 핵심 구조:
#   1. Get_Trade_Decision() — 매 시점마다 매수/매도/관망 판단 (가중 투표)
#      국면 구분 없이 통합 기술 신호 사용 (BB 돌파, RSI, MACD, 다이버전스)
#   2. Backtest_Strategy()  — 전체 기간 순회하며 매매 일지(Trade Log) 생성
#
# 성과 지표:
#   - 승률 (Win Rate)
#   - 회당 평균 수익률 (Avg Return)
#   - 커스텀 샤프 지수 = (평균수익/표준편차) × √매매횟수
# ============================================================================

import logging

import numpy as np
import pandas as pd

import config
from indicators import Make_Indicators
from predict import Add_AI_Signals
from kelly import Get_Position_Size

# --- 로거 설정 ---
logger = logging.getLogger(__name__)


# ============================================================================
# [핵심 함수 1] 매매 판단 엔진 — 가중 투표 방식
# ============================================================================

def Get_Trade_Decision(i: int, df: pd.DataFrame, params: dict) -> int:
    """
    특정 시점(i)의 시장 데이터를 종합 분석하여 매수/매도/관망을 결정합니다.

    국면 구분 없이 통합 기술 신호 + AI 확신도로 판단:
    - BB 상단 돌파 + 스퀴즈: 주 매수 트리거
    - RSI 과매도 구간: 보조 매수
    - RSI 과매수 이탈 / BB 하단 + MACD 데드크로스: 매도
    - MACD 교차 / 다이버전스: 확신도 보조
    - AI 확신도 < AI_FILTER → 매수 신호 전부 차단

    Returns:
        int: 1 (매수) / -1 (매도) / 0 (관망)
    """
    ai_prob = df['AI_Prob'].iloc[i]
    ai_pass = ai_prob >= params['ai_filter']

    is_bb_squeeze = df['BandWidth'].iloc[i] > (
        df['BB_Width_MA'].iloc[i] * params['bb_squeeze_ratio']
    )

    rsi = df['RSI'].iloc[i]
    signal = 0.0

    # =================================================================
    # [매수] BB 상단 돌파 + 스퀴즈 탈출 (모멘텀 돌파 — 주 신호)
    # =================================================================
    if (df['Close'].iloc[i] > df['Upper'].iloc[i - 1]) and is_bb_squeeze:
        signal = 1.0

    # [매수] RSI 과매도 구간 반등 (보조 신호)
    elif rsi < params['rsi_buy']:
        signal = 0.7

    # =================================================================
    # [매도] RSI 과매수에서 이탈 (모멘텀 소진)
    # =================================================================
    if df['RSI'].iloc[i - 1] > params['rsi_sell'] and rsi < params['rsi_sell']:
        signal = -1.0

    # [매도] BB 하단 접근 + MACD 데드크로스 (하락 전환 확정)
    if (df['Close'].iloc[i] < df['Lower'].iloc[i] * 1.05) and (df['MACD_Cross'].iloc[i] == -1):
        signal = -1.0

    # =================================================================
    # [보조] MACD 교차 / 다이버전스 — 확신도 조절
    # =================================================================
    if df['MACD_Cross'].iloc[i] == 1 and signal > 0:
        signal = min(signal + 0.3, 1.0)
    if df['MACD_Cross'].iloc[i] == -1 and signal < 0:
        signal = max(signal - 0.3, -1.0)
    if df['MACD_Zero_Cross'].iloc[i] == 1 and signal > 0:
        signal = min(signal + 0.2, 1.0)
    if df['MACD_Zero_Cross'].iloc[i] == -1 and signal < 0:
        signal = max(signal - 0.2, -1.0)
    if df['Divergence'].iloc[i] == -1 and signal > 0:
        signal -= 0.3

    # =================================================================
    # [게이트] AI 확신도 미달 시 매수 차단
    # =================================================================
    if signal > 0 and not ai_pass:
        signal = 0.0

    if signal >= 0.7:
        return 1
    if signal <= -0.7:
        return -1
    return 0


# ============================================================================
# [핵심 함수 2] 백테스트 실행 엔진
# ============================================================================

def Backtest_Strategy(
    ticker: str = None,
    df_input: pd.DataFrame = None,
    start_date: str = config.START_DATE,
    opt_params: dict = None
) -> dict:
    """
    매매 일지(Trade Log) 기반으로 전략의 과거 성과를 검증합니다.
    
    복리 계좌 시뮬레이션이 아닌 "매 거래의 수익률"을 기록하여
    순수 전략의 승률/수익률/샤프 지수를 평가합니다.
    
    Args:
        ticker: 종목 티커 (df_input이 None일 때 데이터 다운로드용)
        df_input: 이미 지표+AI 신호가 부착된 DataFrame (optimize.py 속도 최적화)
        start_date: 데이터 시작일 (기본 config.START_DATE)
        opt_params: Optuna 최적화 파라미터 오버라이드 딕셔너리
    
    Returns:
        dict: {
            'sharpe': 커스텀 샤프 지수,
            'win_rate': 승률,
            'avg_return': 회당 평균 수익률,
            'trade_count': 총 매매 횟수,
            'avg_days': 평균 보유 기간,
            'trade_log': 전체 매매 일지 DataFrame
        }
        매매 0회 시 sharpe=-99 반환
    """
    # --- [1] 데이터 준비 ---
    if df_input is None:
        from data_loader import load_ohlcv
        df = load_ohlcv(ticker, start=start_date, drop_intraday=True)
        df = Make_Indicators(df)
        df = Add_AI_Signals(df)
        df = df.dropna()
    else:
        df = df_input.copy()

    # --- [2] 파라미터 초기화 (config 기본값 → Optuna 오버라이드) ---
    params = {
        'rsi_buy': config.RSI_BUY,
        'rsi_sell': config.RSI_SELL,
        'bb_squeeze_ratio': config.BB_SQUEEZE_RATIO,
        'ai_filter': config.AI_FILTER,
        'trailing_atr_mult': config.TRAILING_ATR_MULT,
    }
    if opt_params:
        params.update(opt_params)

    # --- [3] 매매 상태 변수 ---
    trade_log = []        # 개별 매매 기록 리스트
    in_position = False   # 현재 포지션 보유 여부
    entry_price = 0.0     # 수수료 포함 진입 단가
    entry_date = None     # 진입 일자
    active_stop_price = 0.0  # 최초 ATR 기반 손절가
    highest_price = 0.0   # 보유 중 최고가 (트레일링 스탑용)

    # --- [4] 시뮬레이션 루프 ---
    for i in range(1, len(df)):
        decision = Get_Trade_Decision(i, df, params)
        current_price = df['Close'].iloc[i]

        # ===== 진입 (Buy) =====
        if decision == 1 and not in_position:
            # kelly.py에서 손절가 산출 (주수와 켈리 비중도 받지만 여기서는 손절가만 사용)
            _, stop_price, _ = Get_Position_Size(
                config.CAPITAL, current_price, df['ATR'].iloc[i],
                df['Model_Precision'].iloc[i], df['AI_Prob'].iloc[i]
            )
            entry_price = current_price * (1 + config.FEE_RATE)  # 수수료 포함 진입가
            entry_date = df.index[i]
            active_stop_price = stop_price
            highest_price = current_price
            in_position = True

        # ===== 청산 (Sell) =====
        elif in_position:
            # 보유 중 최고가 갱신 (트레일링 스탑 기준점)
            if current_price > highest_price:
                highest_price = current_price

            # Chandelier Exit: 고점 - (현재 ATR × 배수)
            current_atr = df['ATR'].iloc[i]
            trailing_stop = highest_price - (current_atr * params['trailing_atr_mult'])

            # 청산 조건: 매도 신호 OR 최초 손절 OR 트레일링 스탑
            should_exit = (
                decision == -1 or
                current_price <= active_stop_price or
                current_price <= trailing_stop
            )

            if should_exit:
                exit_price = current_price * (1 - config.FEE_RATE)  # 수수료 차감 청산가
                exit_date = df.index[i]

                trade_return = (exit_price / entry_price) - 1
                holding_days = (exit_date - entry_date).days

                trade_log.append({
                    'Ticker': ticker,
                    'Entry_Date': entry_date,
                    'Exit_Date': exit_date,
                    'Return': trade_return,
                    'Days': holding_days,
                    'Result': 1 if trade_return > 0 else 0,
                })
                in_position = False

    # --- [5] 성과 통계 산출 ---
    if not trade_log:
        return {
            'sharpe': -99.0,
            'win_rate': 0.0,
            'avg_return': 0.0,
            'trade_count': 0,
            'avg_days': 0.0,
            'trade_log': pd.DataFrame(),
        }

    log_df = pd.DataFrame(trade_log)
    win_rate = log_df['Result'].mean()
    avg_return = log_df['Return'].mean()
    std_return = log_df['Return'].std()

    # [커스텀 샤프] optimize.py 전용 — 안정적으로 자주 이기는 파라미터 선호
    sharpe = (avg_return / std_return * np.sqrt(len(log_df))) if std_return > 0 else -99.0

    # [표준 연간화 샤프] 참고용 — 스윙 단위 수익률을 일간으로 단순 환산한 근사치
    avg_days = log_df['Days'].mean()
    if avg_days > 0 and std_return > 0:
        daily_ret = avg_return / avg_days
        daily_std = std_return / np.sqrt(avg_days)
        std_sharpe = (daily_ret - config.RISK_FREE_RATE / 252) / daily_std * np.sqrt(252)
    else:
        std_sharpe = 0.0

    # [MDD] 최대 낙폭 — 전략의 실전 위험도 측정 핵심 지표
    # 매매 일지 기반으로 누적 자본곡선을 재구성하여 계산
    cumulative = (1 + log_df['Return']).cumprod()
    rolling_max = cumulative.cummax()
    drawdown = (cumulative - rolling_max) / rolling_max
    mdd = float(drawdown.min()) if len(drawdown) > 0 else 0.0

    # [총 수익률] 복리 누적 수익률
    total_return = float(cumulative.iloc[-1]) - 1.0 if len(cumulative) > 0 else 0.0

    result = {
        'sharpe': sharpe,           # 커스텀 샤프 (optimize 전용)
        'std_sharpe': std_sharpe,   # 표준 연간화 샤프 (v2 비교용)
        'mdd': mdd,                 # 최대 낙폭 (MDD)
        'total_return': total_return,  # 복리 누적 수익률
        'win_rate': win_rate,
        'avg_return': avg_return,
        'trade_count': len(log_df),
        'avg_days': log_df['Days'].mean(),
        'trade_log': log_df,
    }

    # --- [6] 단독 실행 시 콘솔 리포트 ---
    if df_input is None:
        print(f"\n🏁 [{ticker}] 스윙 매매 로그 백테스트 완료")
        print(f"  ▶ 총 매매 횟수: {result['trade_count']}회")
        print(f"  ▶ 평균 승률: {result['win_rate']:.2%}")
        print(f"  ▶ 회당 평균 수익률: {result['avg_return']:.2%}")
        print(f"  ▶ 평균 보유 기간: {result['avg_days']:.1f}일")
        print(f"  ▶ 커스텀 샤프: {result['sharpe']:.2f}  |  표준 샤프: {result['std_sharpe']:.2f}")
        print(f"  ▶ MDD: {result['mdd']:.2%}  |  누적수익: {result['total_return']:.2%}")

    return result


# ============================================================================
# [테스트] 단독 실행
# ============================================================================

if __name__ == "__main__":
    if config.TICKERS:
        result = Backtest_Strategy(config.TICKERS[0])

        if result['trade_count'] > 0:
            print(f"\n📊 매매 일지 (최근 5건):")
            print(result['trade_log'].tail())