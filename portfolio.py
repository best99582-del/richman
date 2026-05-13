# ============================================================================
# 📊 [퀀트 유니버스] 포트폴리오 비중 최적화 엔진 (portfolio.py)
# ============================================================================
# 역할: 여러 종목/자산군이 동시에 잡혔을 때 최적 비중을 산출
# 파이프라인 위치: [6단계] 비중 배분
# 의존성: config.py (무위험 수익률, 종목 리스트)
#
# 두 가지 모드:
#   - Macro (올웨더): 샤프 지수 최대화 (Mean-Variance / Markowitz)
#   - Micro (급등주 스윙): 역변동성 배분 (Risk Parity)
# ============================================================================

import logging

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import config

# --- 로거 설정 ---
logger = logging.getLogger(__name__)


# ============================================================================
# [유틸리티] 포트폴리오 통계 계산
# ============================================================================

def Get_Portfolio_Stats(
    weights: np.ndarray,
    annual_returns: pd.Series,
    annual_cov: pd.DataFrame
) -> tuple:
    """
    주어진 비중으로 포트폴리오의 기대 수익률, 리스크, 샤프 지수를 계산합니다.
    
    Args:
        weights: 각 자산의 비중 배열 (합계 = 1.0)
        annual_returns: 각 자산의 연간 기대수익률
        annual_cov: 자산 간 연간 공분산 행렬
    
    Returns:
        tuple: (기대수익률, 리스크(변동성), 샤프지수)
    
    공식:
        수익률 = Σ(w_i × r_i)
        리스크 = √(w^T × Σ × w)
        샤프 = (수익률 - 무위험수익률) / 리스크
    """
    weights = np.array(weights)
    p_ret = np.dot(weights, annual_returns)
    p_risk = np.sqrt(np.dot(weights.T, np.dot(annual_cov, weights)))
    sharpe = (p_ret - config.RISK_FREE_RATE) / p_risk if p_risk > 0 else 0.0
    return p_ret, p_risk, sharpe


def _neg_sharpe(weights, annual_returns, annual_cov):
    return -Get_Portfolio_Stats(weights, annual_returns, annual_cov)[2]


# ============================================================================
# [핵심 함수] 포트폴리오 비중 최적화
# ============================================================================

def Optimize_Portfolio(
    tickers: list,
    start_date: str = config.START_DATE,
    mode: str = 'macro',
    visualize: bool = False
) -> dict:
    """
    다중 자산/종목의 최적 비중을 수학적으로 산출합니다.
    
    Args:
        tickers: 포트폴리오 구성 종목 리스트 (예: ['SPY', 'TLT', 'GLD'])
        start_date: 수익률 계산 시작일
        mode: 'macro' — 샤프 지수 최대화 (올웨더/장기)
              'micro' — 역변동성 배분 (급등주 스윙)
        visualize: True면 몬테카를로 효율적 전선 차트 출력 (macro 전용)
    
    Returns:
        dict: {
            'weights': {티커: 비중} 딕셔너리,
            'return': 기대 수익률,
            'risk': 리스크 (변동성),
            'sharpe': 샤프 지수,
            'mode': 사용된 모드
        }
        데이터 로드 실패 시 기본 균등 비중 반환
    """
    from data_loader import load_ohlcv

    # --- [1] 데이터 수집 ---
    df_list = []
    valid_tickers = []

    for ticker in tickers:
        try:
            df = load_ohlcv(ticker, start=start_date)['Close']
            df.name = ticker
            df_list.append(df)
            valid_tickers.append(ticker)
        except Exception as e:
            logger.warning("⚠️ %s 데이터 로드 실패: %s", ticker, e)

    # 실패 시 균등 비중 폴백 (빈 리스트 대신 일관된 dict 반환)
    if not df_list:
        logger.error("전체 종목 데이터 로드 실패. 균등 비중 반환.")
        equal_weight = 1.0 / len(tickers)
        return {
            'weights': {t: equal_weight for t in tickers},
            'return': 0.0,
            'risk': 0.0,
            'sharpe': 0.0,
            'mode': mode
        }

    # --- [2] 수익률 및 공분산 계산 ---
    stocks = pd.concat(df_list, axis=1).dropna()
    daily_ret = stocks.pct_change().dropna()
    annual_returns = daily_ret.mean() * 252       # 일간 → 연간 수익률
    annual_cov = daily_ret.cov() * 252             # 일간 → 연간 공분산
    num_assets = len(valid_tickers)

    # --- [3] 비중 최적화 ---
    if mode == 'micro':
        # [Micro] 역변동성(Inverse Volatility) 배분
        # 변동성 높은 종목 = 비중 낮게, 낮은 종목 = 비중 높게
        # → 각 종목이 포트폴리오 전체 리스크에 동등하게 기여
        volatilities = daily_ret.std() * np.sqrt(252)
        inv_vol = 1.0 / volatilities
        optimal_weights = (inv_vol / inv_vol.sum()).values

    else:
        # [Macro] 샤프 지수 최대화 (Mean-Variance Optimization)
        # SciPy SLSQP 알고리즘으로 정확한 수학적 해 도출
        constraints = {'type': 'eq', 'fun': lambda x: np.sum(x) - 1}  # 비중 합 = 1
        bounds = tuple((0.0, 1.0) for _ in range(num_assets))         # 각 비중 0~100%
        initial_guess = [1.0 / num_assets] * num_assets                # 초기값: 균등 배분

        result = minimize(
            _neg_sharpe, initial_guess,
            args=(annual_returns, annual_cov),
            method='SLSQP', bounds=bounds, constraints=constraints
        )
        optimal_weights = result.x

    # --- [4] 최적 포트폴리오 통계 ---
    p_ret, p_risk, sharpe = Get_Portfolio_Stats(
        optimal_weights, annual_returns, annual_cov
    )

    # --- [5] 시각화 (Macro + visualize=True 일 때만) ---
    if visualize and mode == 'macro':
        _plot_efficient_frontier(
            num_assets, annual_returns, annual_cov,
            p_ret, p_risk, optimal_weights
        )

    return {
        'weights': dict(zip(valid_tickers, optimal_weights)),
        'return': p_ret,
        'risk': p_risk,
        'sharpe': sharpe,
        'mode': mode
    }


# ============================================================================
# [유틸리티] 효율적 전선 시각화
# ============================================================================

def _plot_efficient_frontier(
    num_assets: int,
    annual_returns: pd.Series,
    annual_cov: pd.DataFrame,
    opt_ret: float,
    opt_risk: float,
    opt_weights: np.ndarray,
    n_simulations: int = 20000
):
    """
    몬테카를로 시뮬레이션으로 효율적 전선(Efficient Frontier)을 그리고,
    수학적 최적화로 찾은 최적점을 별표로 표시합니다.
    
    Args:
        num_assets: 자산 수
        annual_returns: 연간 기대수익률
        annual_cov: 연간 공분산 행렬
        opt_ret: 최적 포트폴리오 수익률
        opt_risk: 최적 포트폴리오 리스크
        opt_weights: 최적 비중
        n_simulations: 무작위 포트폴리오 생성 수
    """
    import matplotlib.pyplot as plt

    results = np.zeros((3, n_simulations))

    for i in range(n_simulations):
        w = np.random.random(num_assets)
        w /= np.sum(w)
        ret, risk, sr = Get_Portfolio_Stats(w, annual_returns, annual_cov)
        results[0, i] = risk
        results[1, i] = ret
        results[2, i] = sr

    plt.figure(figsize=(10, 6))
    plt.scatter(
        results[0, :], results[1, :],
        c=results[2, :], cmap='viridis',
        marker='o', s=10, alpha=0.3
    )
    plt.colorbar(label='Sharpe Ratio')

    # 수학적 최적화 최적점 표시
    plt.scatter(
        opt_risk, opt_ret,
        marker='*', color='red', s=300,
        label='Optimal (SciPy)'
    )

    plt.title('Efficient Frontier (Monte Carlo vs Mathematical Optimization)')
    plt.xlabel('Risk (Volatility)')
    plt.ylabel('Expected Return')
    plt.legend()
    plt.grid(True)
    plt.show()


# ============================================================================
# [테스트] 단독 실행
# ============================================================================

if __name__ == "__main__":
    # --- [Macro] 올웨더 자산 배분 ---
    print("\n" + "=" * 60)
    print("🌍 [Macro] 올웨더 자산 배분 (샤프 지수 최대화)")
    print("=" * 60)

    macro_tickers = ['SPY', 'TLT', 'GLD']  # S&P500, 미국 장기채, 금
    macro_res = Optimize_Portfolio(macro_tickers, mode='macro', visualize=True)

    for t, w in macro_res['weights'].items():
        print(f"  - {t}: {w:.1%}")
    print(f"  ▶ 기대수익률: {macro_res['return']:.2%} | "
          f"리스크: {macro_res['risk']:.2%} | 샤프: {macro_res['sharpe']:.2f}")

    # --- [Micro] 급등주 스윙 리스크 밸런싱 ---
    print("\n" + "=" * 60)
    print("🔥 [Micro] 급등주 스윙 리스크 밸런싱 (역변동성 배분)")
    print("=" * 60)

    micro_res = Optimize_Portfolio(config.TICKERS, mode='micro', visualize=False)

    for t, w in micro_res['weights'].items():
        print(f"  - {t}: {w:.1%}")
    print(f"  ▶ 기대수익률: {micro_res['return']:.2%} | "
          f"리스크: {micro_res['risk']:.2%} | 샤프: {micro_res['sharpe']:.2f}")

    print("=" * 60)