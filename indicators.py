# ============================================================================
# 📊 [퀀트 유니버스] 기술적 지표 엔진 (indicators.py)
# ============================================================================
# 역할: 원시 OHLCV 데이터를 분석용 지표로 가공 + GMM 시장 국면 판별
# 파이프라인 위치: [3단계] 데이터 전처리
# 의존성: config.py, ta (외부 라이브러리 — RSI/MACD/BB/ATR/ADX)
#
# 변경 이력:
#   v10: ta 라이브러리로 5개 표준 지표 교체 (검증 결과 corr ≥ 0.9993)
#        - RSI, MACD, Bollinger Bands, ATR, ADX
#        - Stochastic은 정의 차이로 우리 구현 유지
#        - 파생 신호(Divergence, BB_Squeeze 등)는 자체 구현 유지
# ============================================================================

import warnings

import numpy as np
import pandas as pd
import ta as ta_lib
import ta.momentum
import ta.trend
import ta.volatility
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler
from sklearn.exceptions import ConvergenceWarning

import config


# ============================================================================
# [참고] get_rma() 함수는 v10에서 제거됨 — ta 라이브러리 사용으로 불필요해짐
# 필요 시 ta_backup.py에서 복원 가능 (Wilder's RMA 직접 구현체)
# ============================================================================


# ============================================================================
# [내부] 파라미터 로딩 헬퍼 — Make_Indicators 전용
# ============================================================================

def _load_params(params: dict = None) -> dict:
    """
    optimize.py 튜닝 파라미터가 있으면 우선 적용, 없으면 config 기본값 사용.
    MACD 버전 번호 → (Short, Long, Signal) 튜플 변환 포함.
    """
    if params is None:
        params = {}

    macd_ver = params.get('macd_version', config.MACD_VERSION)
    macd_short, macd_long, macd_signal = config.MACD_VERSIONS[macd_ver]

    return {
        'rsi_period':      params.get('rsi_period',      config.RSI_PERIOD),
        'macd_short':      params.get('macd_short',      macd_short),
        'macd_long':       params.get('macd_long',       macd_long),
        'macd_signal':     params.get('macd_signal',     macd_signal),
        'stoch_period':    params.get('stoch_period',    config.STOCH_PERIOD),
        'stoch_slow_k':    params.get('stoch_slow_k',    config.STOCH_SLOW_K),
        'stoch_slow_d':    params.get('stoch_slow_d',    config.STOCH_SLOW_D),
        'bb_squeeze_ratio': params.get('bb_squeeze_ratio', config.BB_SQUEEZE_RATIO),
    }


# ============================================================================
# [핵심 함수 1] 기술적 지표 산출 — Make_Indicators
# ============================================================================

def Make_Indicators(df: pd.DataFrame, params: dict = None) -> pd.DataFrame:
    """
    OHLCV DataFrame에 기술적 지표 26개를 추가합니다.

    Args:
        df: Open/High/Low/Close/Volume 컬럼을 가진 DataFrame
        params: optimize.py 튜닝 오버라이드 딕셔너리 (None이면 config 기본값)

    Returns:
        DataFrame: 원본 + 지표/파생신호 컬럼 추가본
    """
    df = df.copy()
    p = _load_params(params)

    # ===== [1] MACD (ta 라이브러리) =====
    macd_obj = ta_lib.trend.MACD(
        close=df['Close'],
        window_slow=p['macd_long'],
        window_fast=p['macd_short'],
        window_sign=p['macd_signal'],
    )
    df['MACD']        = macd_obj.macd()
    df['MACD_Signal'] = macd_obj.macd_signal()
    df['MACD_Hist']   = macd_obj.macd_diff()

    # ===== [2] RSI (ta 라이브러리, Wilder's RMA 방식) =====
    df['RSI'] = ta_lib.momentum.RSIIndicator(
        close=df['Close'], window=p['rsi_period']
    ).rsi()

    # ===== [3] 이동평균 + 볼린저밴드 =====
    df['MA5']   = df['Close'].rolling(5).mean()
    df['MA10']  = df['Close'].rolling(10).mean()
    df['MA20']  = df['Close'].rolling(config.BB_PERIOD).mean()
    df['MA60']  = df['Close'].rolling(60).mean()
    df['MA120'] = df['Close'].rolling(120).mean()

    bb_obj = ta_lib.volatility.BollingerBands(
        close=df['Close'], window=config.BB_PERIOD, window_dev=config.BB_STD
    )
    df['Upper'] = bb_obj.bollinger_hband()
    df['Lower'] = bb_obj.bollinger_lband()
    # MA20 대비 비율(%)로 표준화 — 종목 간 비교 가능 (ta 라이브러리 기본은 절대값)
    df['BandWidth'] = (df['Upper'] - df['Lower']) / df['MA20'] * 100

    # ===== [4] ATR (ta 라이브러리, Wilder's RMA on True Range) =====
    df['ATR'] = ta_lib.volatility.AverageTrueRange(
        high=df['High'], low=df['Low'], close=df['Close'],
        window=config.ATR_PERIOD,
    ).average_true_range()

    # ===== [5] 이격도 (Disparity) — EMA20 대비 현재가 위치 =====
    # 100 기준: 이상이면 EMA 위, 이하면 EMA 아래
    ema20 = df['Close'].ewm(span=config.BB_PERIOD, min_periods=config.BB_PERIOD, adjust=False).mean()
    df['Disparity'] = (df['Close'] / ema20) * 100

    # ===== [6] 스토캐스틱 (Slow K/D) =====
    low_min  = df['Low'].rolling(p['stoch_period']).min()
    high_max = df['High'].rolling(p['stoch_period']).max()
    df['K']      = ((df['Close'] - low_min) / (high_max - low_min)) * 100
    df['Slow_K'] = df['K'].rolling(p['stoch_slow_k']).mean()
    df['Slow_D'] = df['Slow_K'].rolling(p['stoch_slow_d']).mean()

    # ===== [7] ADX (ta 라이브러리) =====
    df['ADX'] = ta_lib.trend.ADXIndicator(
        high=df['High'], low=df['Low'], close=df['Close'],
        window=config.ATR_PERIOD,
    ).adx()

    # ===== [파생 8~17] =====

    # [8] RSI 기울기 — 최소자승법(Least Squares) 5일 기울기
    df['RSI_Slope'] = (
        -2 * df['RSI'].shift(4) - df['RSI'].shift(3)
        + df['RSI'].shift(1) + 2 * df['RSI']
    ) / 10

    # [9] 주가 기울기 — 수익률(%) 기반으로 스케일 독립성 확보
    pct = df['Close'].pct_change(fill_method=None) * 100
    df['Price_Slope'] = (
        -2 * pct.shift(4) - pct.shift(3) + pct.shift(1) + 2 * pct
    ) / 10

    # [10] 다이버전스: 주가↑+RSI↓ = 약세(-1), 주가↓+RSI↑ = 강세(+1)
    df['Divergence'] = 0
    df.loc[(df['Price_Slope'] > 0) & (df['RSI_Slope'] < 0), 'Divergence'] = -1
    df.loc[(df['Price_Slope'] < 0) & (df['RSI_Slope'] > 0), 'Divergence'] = 1

    # [11] BB 스퀴즈 탈출 — BandWidth > 20일 평균 × N배 (횡보 탈출 신호)
    df['BB_Width_MA'] = df['BandWidth'].rolling(20).mean()
    df['BB_Squeeze']  = df['BandWidth'] > (df['BB_Width_MA'] * p['bb_squeeze_ratio'])

    # [12] BandWidth 변화율 (%)
    df['BB_Width_Pct'] = df['BandWidth'].pct_change(fill_method=None) * 100
    df['BB_Width_Pct'] = df['BB_Width_Pct'].replace([np.inf, -np.inf], 0)

    # [13] 스토캐스틱 교차 — 골든크로스(+1) / 데드크로스(-1)
    stoch_diff      = df['Slow_K'] - df['Slow_D']
    stoch_diff_prev = stoch_diff.shift(1)
    df['Stoch_Cross'] = 0
    df.loc[(stoch_diff > 0) & (stoch_diff_prev <= 0), 'Stoch_Cross'] =  1
    df.loc[(stoch_diff < 0) & (stoch_diff_prev >= 0), 'Stoch_Cross'] = -1

    # [14] MACD 교차 — 골든크로스(+1) / 데드크로스(-1)
    macd_diff      = df['MACD'] - df['MACD_Signal']
    macd_diff_prev = macd_diff.shift(1)
    df['MACD_Cross'] = 0
    df.loc[(macd_diff > 0) & (macd_diff_prev <= 0), 'MACD_Cross'] =  1
    df.loc[(macd_diff < 0) & (macd_diff_prev >= 0), 'MACD_Cross'] = -1

    # [15] MACD 제로선 돌파 — 상승 추세 확정(+1) / 하락 추세 확정(-1)
    macd_prev = df['MACD'].shift(1)
    df['MACD_Zero_Cross'] = 0
    df.loc[(df['MACD'] > 0) & (macd_prev <= 0), 'MACD_Zero_Cross'] =  1
    df.loc[(df['MACD'] < 0) & (macd_prev >= 0), 'MACD_Zero_Cross'] = -1

    # [16] MA20 위치 판단
    df['Price_Above_MA20'] = df['Close'] > df['MA20']

    # [17] 거래량 비율 — 20일 평균 대비 배율 (스케일 독립)
    if 'Volume' in df.columns:
        avg_vol = df['Volume'].rolling(20).mean()
        df['Volume_Ratio'] = df['Volume'] / avg_vol.replace(0, np.nan)
    else:
        df['Volume_Ratio'] = 1.0

    # [18] 거래량 폭증 플래그 (v10: AI 피처용 — 극단값 노이즈 제거)
    # Volume_Ratio 원본은 분포가 매우 한쪽으로 치우쳐(max 17×) 모델에 노이즈로 작용.
    # >2 이진화하면 강한 신호만 남고 노이즈 제거 → 실험 결과 +0.85%p 정밀도 개선.
    df['Volume_Spike'] = (df['Volume_Ratio'] > 2).astype(int)

    return df


# ============================================================================
# [핵심 함수 2] 시장 국면 판별 — Detect_Regime
# ============================================================================
# ⚠️ 파이프라인 미사용 — 수동 분석 전용 보존 함수
# 파이프라인(screener/predict/backtest)에서는 호출하지 않음
# 국면 전략 참고: docs/regime_strategy_guide.md
# ============================================================================

_regime_proxy_cache: dict = {}


def Detect_Regime(df: pd.DataFrame, window_size: int = 252) -> pd.DataFrame:
    """
    GMM 롤링 윈도우로 시장 국면을 Bull/Sideways/Bear로 분류합니다.

    개별 소형주에 GMM을 직접 적용하면 정확도가 낮아 QQQ 기반 국면을
    날짜 매핑 방식으로 사용합니다 (config.REGIME_PROXY = 'QQQ').
    config.REGIME_PROXY = '' 이면 입력 df 자체로 GMM.

    Look-ahead Bias 차단: 매 시점마다 해당 날짜 이전 데이터로만 GMM 학습.
    """
    source_df = _load_proxy_df(df, window_size) if config.REGIME_PROXY else df

    source = source_df.copy()
    source['Trend'] = (source['Close'] - source['MA60']) / source['MA60']
    source['Vol']   = source['ATR'] / source['Close']
    features = ['Trend', 'Vol']

    data = df.copy()
    data['Regime_Name'] = 'Sideways'

    scaler = StandardScaler()
    gmm = GaussianMixture(
        n_components=config.GMM_COMPONENTS,
        covariance_type='full',
        random_state=config.GMM_RANDOM_STATE,
        warm_start=False,
    )

    source_index = source.index

    with warnings.catch_warnings():
        warnings.simplefilter('ignore', ConvergenceWarning)

        for i in range(window_size, len(data)):
            today = data.index[i]
            try:
                mask      = source_index < today
                available = source.loc[mask]
                if len(available) < window_size:
                    continue

                train_data = available.iloc[-window_size:][features].dropna()
                if len(train_data) < window_size * 0.8:
                    continue

                scaled_train = scaler.fit_transform(train_data)
                gmm.fit(scaled_train)

                # Trend 평균 기준 → Bull(최대) / Sideways(중간) / Bear(최소)
                labels = gmm.predict(scaled_train)
                means = [
                    (j, train_data[labels == j]['Trend'].mean() if (labels == j).any() else 0)
                    for j in range(config.GMM_COMPONENTS)
                ]
                means.sort(key=lambda x: x[1], reverse=True)
                regime_map = {
                    means[0][0]: 'Bull',
                    means[1][0]: 'Sideways',
                    means[2][0]: 'Bear',
                }

                src_candidates = source_index[source_index <= today]
                if len(src_candidates) == 0:
                    continue
                ref_date   = src_candidates[-1]
                today_feat = source.loc[[ref_date]][features].fillna(0)
                data.loc[today, 'Regime_Name'] = regime_map[gmm.predict(scaler.transform(today_feat))[0]]

            except Exception:
                pass

    if 'ADX' in data.columns and config.ADX_THRESHOLD > 0:
        data.loc[data['ADX'] < config.ADX_THRESHOLD, 'Regime_Name'] = 'Sideways'

    return data


def _load_proxy_df(df: pd.DataFrame, window_size: int) -> pd.DataFrame:
    """
    config.REGIME_PROXY(QQQ) 데이터를 로드·캐싱합니다.
    같은 프로세스 내 중복 다운로드를 방지하며, 실패 시 원본 df 반환.
    """
    from data_loader import load_ohlcv

    start_str = df.index[0].strftime('%Y-%m-%d')
    cache_key = (config.REGIME_PROXY, start_str, window_size)

    if cache_key in _regime_proxy_cache:
        return _regime_proxy_cache[cache_key]

    try:
        load_start = df.index[0] - pd.Timedelta(days=int(window_size * 1.5))
        proxy_raw  = load_ohlcv(config.REGIME_PROXY, start=load_start.strftime('%Y-%m-%d'))
        proxy_df   = Make_Indicators(proxy_raw)
        _regime_proxy_cache[cache_key] = proxy_df
        return proxy_df
    except Exception:
        print(f"  ⚠️ REGIME_PROXY({config.REGIME_PROXY}) 로드 실패 → 개별 종목 GMM 사용")
        _regime_proxy_cache[cache_key] = df
        return df


# ============================================================================
# [테스트] 단독 실행 — Make_Indicators + Detect_Regime 수동 검증
# ============================================================================

if __name__ == "__main__":
    import matplotlib.pyplot as plt
    from data_loader import load_ohlcv

    ticker = config.TICKERS[0]
    df = load_ohlcv(ticker, start=config.START_DATE)
    df['Ticker'] = ticker

    df = Make_Indicators(df)

    # --- [검증 1] 기본 지표 ---
    print(f"\n--- [{ticker}] 최근 5일 기본 지표 ---")
    cols_basic = [
        'Ticker', 'Close', 'RSI', 'MACD',
        'Disparity', 'Upper', 'Lower', 'MA20', 'MA60', 'BandWidth',
        'Slow_K', 'Slow_D', 'ATR',
    ]
    print(df[cols_basic].tail().T)

    # --- [검증 2] 파생 신호 ---
    print(f"\n--- [{ticker}] 최근 5일 파생 신호 ---")
    cols_derived = [
        'ADX', 'RSI_Slope', 'Price_Slope', 'Divergence',
        'BB_Squeeze', 'BB_Width_Pct', 'Stoch_Cross',
        'MACD_Cross', 'MACD_Zero_Cross', 'Price_Above_MA20', 'Volume_Ratio',
    ]
    print(df[cols_derived].tail().T)

    # --- [검증 3] 국면 판별 (수동 — 시간 소요 큼) ---
    run_regime = input("\n국면 판별(Detect_Regime) 실행할까요? 시간 소요 큼 (y/n): ").strip().lower()
    if run_regime == 'y':
        df = Detect_Regime(df, window_size=252)

        print("\n[국면 분포]")
        print(df['Regime_Name'].value_counts())

        print("\n[2020년 3월 코로나 폭락장]")
        print(df.loc['2020-02-01':'2020-04-15', ['Close', 'Regime_Name']].iloc[::5])

        plt.figure(figsize=(14, 7))
        plt.plot(df.index, df['Close'], color='black', linewidth=1, label='Close Price')
        for regime, color in config.REGIME_COLORS.items():
            for date in df[df['Regime_Name'] == regime].index:
                plt.axvspan(date, date + pd.Timedelta(days=1), color=color, alpha=0.3, lw=0)
        plt.title(f"{ticker} Regime Detection (Rolling GMM)")
        plt.legend()
        plt.show()
