# ============================================================================
# ⚡ [퀀트 유니버스] 파라미터 최적화 엔진 (optimize.py)
# ============================================================================
# 역할: Optuna를 활용하여 기대수익(Expectancy Score)을 극대화하는
#       최적 파라미터를 자동 탐색
# 파이프라인 위치: [6단계] 최적화
# 의존성: config.py, ta.py, predict.py, backtest.py
#
# 튜닝 구조:
#   - Layer 1 (지표 산출 파라미터): RSI_PERIOD, MACD_VERSION, STOCH 등
#     → 이 값이 바뀌면 Make_Indicators 재호출 필요 (느림)
#   - Layer 2 (매매 판단 파라미터): RSI 기준값, BB 비율, AI 필터 등
#     → 지표 재계산 없이 backtest만 재실행 (빠름)
#
# Expectancy Score = (평균수익률 × 100) × 승률 × √매매횟수
# ============================================================================

import logging

import numpy as np
import optuna

import config
from indicators import Make_Indicators
from predict import Add_AI_Signals
from backtest import Backtest_Strategy
from data_loader import load_ohlcv

# --- Optuna 로그 레벨 조정 ---
optuna.logging.set_verbosity(optuna.logging.WARNING)
logger = logging.getLogger(__name__)


# ============================================================================
# [Layer 2] 매매 판단 파라미터 최적화 (지표 재계산 불필요 — 빠름)
# ============================================================================

def objective_layer2(trial, processed_dfs: dict) -> float:
    """
    지표가 이미 산출된 데이터를 대상으로 매매 기준값만 튜닝합니다.
    
    12개 파라미터를 탐색하여 바스켓 평균 Expectancy Score를 최대화.
    
    Args:
        trial: Optuna Trial 객체
        processed_dfs: {티커: 전처리 완료 DataFrame} 딕셔너리
    
    Returns:
        float: 바스켓 평균 Expectancy Score (높을수록 좋음, 탈락 시 -99)
    """
    # --- 매매 판단 파라미터 탐색 (통합 전략 — 5개) ---
    opt_params = {
        # RSI 매수/매도 기준 (통합)
        'rsi_buy': trial.suggest_int('rsi_buy', 30, 55),
        'rsi_sell': trial.suggest_int('rsi_sell', 65, 85),

        # BB 스퀴즈 배율
        'bb_squeeze_ratio': trial.suggest_float('bb_squeeze_ratio', 1.2, 3.0),

        # AI 필터 + 트레일링 스탑
        'ai_filter': trial.suggest_float('ai_filter', 0.50, 0.70),
        'trailing_atr_mult': trial.suggest_float('trailing_atr_mult', 1.5, 5.0),
    }

    scores = []

    # --- 바스켓 백테스트 (모든 종목에 동일 파라미터 적용) ---
    for ticker, df_input in processed_dfs.items():
        result = Backtest_Strategy(
            ticker=ticker, df_input=df_input, opt_params=opt_params
        )
        scores.append(_expectancy(result))

    return np.mean(scores)


# ============================================================================
# [Layer 1] 지표 산출 파라미터 최적화 (Make_Indicators 재호출 — 느림)
# ============================================================================

def objective_layer1(trial, raw_dfs: dict) -> float:
    """
    지표 산출 파라미터(RSI 기간, MACD 버전, 스토캐스틱)를 포함하여
    전체 20개 파라미터를 탐색합니다.
    
    지표 재계산이 필요하므로 Layer 2보다 느리지만, 최적의 지표 조합을 탐색 가능.
    
    Args:
        trial: Optuna Trial 객체
        raw_dfs: {티커: 원시 OHLCV DataFrame} (지표 미산출)
    
    Returns:
        float: 바스켓 평균 Expectancy Score
    """
    # --- 지표 산출 파라미터 (ta.py에 전달) ---
    ta_params = {
        'rsi_period': trial.suggest_categorical('rsi_period', [7, 9, 14]),
        'macd_version': trial.suggest_categorical('macd_version', [1, 2, 3]),
        'stoch_period': trial.suggest_categorical('stoch_period', [14, 20]),
        'stoch_slow_k': trial.suggest_categorical('stoch_slow_k', [3, 5]),
        'stoch_slow_d': trial.suggest_categorical('stoch_slow_d', [3, 5]),
    }

    # --- 매매 판단 파라미터 (backtest.py에 전달, 통합 전략) ---
    opt_params = {
        'rsi_buy': trial.suggest_int('rsi_buy', 30, 55),
        'rsi_sell': trial.suggest_int('rsi_sell', 65, 85),
        'bb_squeeze_ratio': trial.suggest_float('bb_squeeze_ratio', 1.0, 2.5),
        'ai_filter': trial.suggest_float('ai_filter', 0.50, 0.70),
        'trailing_atr_mult': trial.suggest_float('trailing_atr_mult', 2.0, 5.0),
    }

    scores = []

    for ticker, raw_df in raw_dfs.items():
        try:
            # 지표 재산출 (ta_params 전달)
            df = Make_Indicators(raw_df, params=ta_params)
            df = Add_AI_Signals(df)
            df = df.dropna()

            result = Backtest_Strategy(
                ticker=ticker, df_input=df, opt_params=opt_params
            )

            scores.append(_expectancy(result))

        except Exception as e:
            logger.warning("Layer1 최적화 실패 (%s): %s", ticker, e)
            scores.append(-99.0)

    return np.mean(scores)


# ============================================================================
# [유틸리티] 공통 헬퍼
# ============================================================================

def _expectancy(result: dict) -> float:
    """백테스트 결과 → Expectancy Score. 독소조항 미통과 시 -99.0."""
    tc = result['trade_count']
    wr = result['win_rate']
    ar = result['avg_return']
    if (tc < config.OPTUNA_MIN_TRADES or tc > config.OPTUNA_MAX_TRADES
            or wr < config.OPTUNA_MIN_WIN_RATE or ar <= 0):
        return -99.0
    return (ar * 100) * wr * np.sqrt(tc)


def _print_best_params(study: optuna.Study, title: str):
    """최적화 결과를 포맷팅하여 콘솔에 출력합니다."""
    print("\n" + "=" * 60)
    print(f"🏆 {title}")
    print("=" * 60)
    print(f"▶ Expectancy Score: {study.best_value:.4f}")
    print(f"▶ 최적 설정값:")
    for key, value in study.best_params.items():
        if isinstance(value, float):
            print(f"   - {key}: {value:.4f}")
        else:
            print(f"   - {key}: {value}")
    print("=" * 60)


# ============================================================================
# [테스트] 단독 실행 — 2단계 최적화
# ============================================================================

if __name__ == "__main__":
    print(f"🚀 [급등주 전용 최적화] 타겟 종목: {config.TEST_TICKERS}")
    print(f"   수수료 {config.FEE_RATE * 100}% 돌파를 위한 최적 파라미터 탐색")

    # --- [Phase 1] 데이터 전처리 (1회) ---
    raw_dfs = {}          # 원시 데이터 (Layer 1용)
    processed_dfs = {}    # 전처리 완료 (Layer 2용)

    for ticker in config.TEST_TICKERS:
        print(f"⏳ {ticker} 데이터 전처리 중...")
        raw_df = load_ohlcv(ticker, start=config.START_DATE, drop_intraday=True)
        raw_dfs[ticker] = raw_df.copy()

        df = Make_Indicators(raw_df)
        df = Add_AI_Signals(df)
        processed_dfs[ticker] = df.dropna()

    print("✅ 데이터 전처리 완료!\n")

    # --- [Phase 2] Layer 2 최적화 (매매 기준값 — 빠름) ---
    print(f"🤖 [Layer 2] 매매 판단 파라미터 최적화 ({config.OPTUNA_N_TRIALS}회)...")
    study_l2 = optuna.create_study(direction='maximize')
    study_l2.optimize(
        lambda trial: objective_layer2(trial, processed_dfs),
        n_trials=config.OPTUNA_N_TRIALS
    )
    _print_best_params(study_l2, "Layer 2 최적 매매 기준값")

    # --- [Phase 3] Layer 1 최적화 (지표 산출 + 매매 기준 — 느림) ---
    n_trials_l1 = config.OPTUNA_N_TRIALS // 2  # Layer 1은 느리므로 절반만
    print(f"🤖 [Layer 1] 전체 파라미터 최적화 ({n_trials_l1}회)...")
    study_l1 = optuna.create_study(direction='maximize')
    study_l1.optimize(
        lambda trial: objective_layer1(trial, raw_dfs),
        n_trials=n_trials_l1
    )
    _print_best_params(study_l1, "Layer 1 최적 전체 파라미터")

    print("\n💡 이 수치들을 config.py에 반영한 뒤 backtest.py로 최종 검증하세요!")