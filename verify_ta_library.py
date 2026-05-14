# ============================================================================
# 🔬 [검증] 우리 ta.py 구현 vs 외부 ta 라이브러리 수치 비교
# ============================================================================
# 목적: 우리가 직접 구현한 RSI, MACD, BB, ATR, Stochastic, ADX 가
#       표준 ta 라이브러리와 얼마나 일치하는지 검증
# 결과: 차이가 작으면 → 향후 ta 라이브러리로 간소화 가능 판단 자료
#       차이가 크면 → 우리 구현 유지 + 원인 분석
# ============================================================================

import sys
import os

# 외부 ta 라이브러리 로드 (로컬 ta.py와 충돌 우회)
_cwd = os.getcwd()
sys.path = [p for p in sys.path if os.path.abspath(p) != _cwd]
import ta as ta_lib                    # noqa: E402  ← 외부 ta 라이브러리
import ta.momentum                     # noqa: E402
import ta.trend                        # noqa: E402
import ta.volatility                   # noqa: E402
# 로컬 ta.py 다시 import 가능하게 cwd 복원
sys.path.insert(0, _cwd)

import importlib                        # noqa: E402
import numpy as np                      # noqa: E402
import pandas as pd                     # noqa: E402

# 로컬 모듈
import config                           # noqa: E402
# 'ta'라는 이름은 외부 라이브러리에 빼앗겼으니 로컬은 모듈 경로로 직접 로드
_local_ta_spec = importlib.util.spec_from_file_location(
    'local_ta', os.path.join(_cwd, 'ta.py')
)
local_ta = importlib.util.module_from_spec(_local_ta_spec)
_local_ta_spec.loader.exec_module(local_ta)

from data_loader import load_ohlcv     # noqa: E402


# ============================================================================
# [핵심] 두 구현 비교 — 한 종목, 6지표
# ============================================================================

def compare_indicators(ticker: str) -> dict:
    """한 종목에 대해 우리 구현 vs ta 라이브러리 비교."""
    df = load_ohlcv(ticker, start=config.START_DATE)
    if df is None or len(df) < 250:
        return None

    # 우리 구현
    df_ours = local_ta.Make_Indicators(df.copy())

    close = df['Close']
    high = df['High']
    low = df['Low']

    # 외부 라이브러리 구현
    rsi_lib = ta_lib.momentum.RSIIndicator(close, window=14).rsi()

    macd_obj = ta_lib.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    macd_lib = macd_obj.macd()
    macd_signal_lib = macd_obj.macd_signal()
    macd_hist_lib = macd_obj.macd_diff()

    bb_obj = ta_lib.volatility.BollingerBands(close, window=20, window_dev=2)
    bb_high_lib = bb_obj.bollinger_hband()
    bb_low_lib = bb_obj.bollinger_lband()
    # BandWidth는 우리 정의에 맞춰 직접 계산: (Upper-Lower)/MA20 * 100
    bb_ma_lib = close.rolling(20).mean()
    bandwidth_lib = (bb_high_lib - bb_low_lib) / bb_ma_lib * 100

    atr_lib = ta_lib.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()

    stoch_obj = ta_lib.momentum.StochasticOscillator(high, low, close, window=14, smooth_window=3)
    # ta lib의 stoch()는 우리의 Slow_K(=K의 3일 SMA)에 해당
    slow_k_lib = stoch_obj.stoch()
    slow_d_lib = stoch_obj.stoch_signal()

    adx_lib = ta_lib.trend.ADXIndicator(high, low, close, window=14).adx()

    # 비교 대상 쌍
    pairs = {
        'RSI':         (df_ours['RSI'],         rsi_lib),
        'MACD':        (df_ours['MACD'],        macd_lib),
        'MACD_Signal': (df_ours['MACD_Signal'], macd_signal_lib),
        'MACD_Hist':   (df_ours['MACD_Hist'],   macd_hist_lib),
        'BB_Upper':    (df_ours['Upper'],       bb_high_lib),
        'BB_Lower':    (df_ours['Lower'],       bb_low_lib),
        'BandWidth':   (df_ours['BandWidth'],   bandwidth_lib),
        'ATR':         (df_ours['ATR'],         atr_lib),
        'Slow_K':      (df_ours['Slow_K'],      slow_k_lib),
        'Slow_D':      (df_ours['Slow_D'],      slow_d_lib),
        'ADX':         (df_ours['ADX'],         adx_lib),
    }

    # 각 지표별 비교 메트릭 산출
    metrics = {}
    for name, (ours, lib) in pairs.items():
        # 두 시리즈 모두 NaN이 아닌 구간만 비교
        merged = pd.DataFrame({'ours': ours, 'lib': lib}).dropna()
        if len(merged) < 30:
            metrics[name] = None
            continue

        diff = merged['ours'] - merged['lib']
        abs_diff = diff.abs()
        scale = merged['lib'].abs().mean() or 1.0  # 상대 오차 계산용

        metrics[name] = {
            'n': len(merged),
            'mae': abs_diff.mean(),
            'max_diff': abs_diff.max(),
            'rel_mae_pct': (abs_diff.mean() / scale) * 100,
            'corr': merged['ours'].corr(merged['lib']),
            'last30_mae': abs_diff.tail(30).mean(),
        }

    return metrics


# ============================================================================
# [출력] 비교 결과 표 형식
# ============================================================================

def print_table(ticker: str, metrics: dict):
    print(f"\n{'='*78}")
    print(f"  {ticker}  지표 비교")
    print('='*78)
    print(f"  {'지표':<12} | {'n':>4} | {'MAE':>10} | {'Max':>10} | "
          f"{'rel%':>6} | {'corr':>7} | 판정")
    print(f"  {'-'*12} | {'-'*4} | {'-'*10} | {'-'*10} | "
          f"{'-'*6} | {'-'*7} | ----")

    for name, m in metrics.items():
        if m is None:
            print(f"  {name:<12} | (데이터 부족)")
            continue
        judge = _judge(m)
        print(f"  {name:<12} | {m['n']:>4} | "
              f"{m['mae']:>10.4f} | {m['max_diff']:>10.4f} | "
              f"{m['rel_mae_pct']:>5.2f}% | {m['corr']:>7.4f} | {judge}")


def _judge(m: dict) -> str:
    """판정: 사실상 동일 / 유사 / 차이 큼."""
    if m['corr'] >= 0.99 and m['rel_mae_pct'] < 1.0:
        return "✅ 사실상 동일"
    if m['corr'] >= 0.95:
        return "🟡 유사 (미세 차이)"
    return "🔴 차이 큼"


# ============================================================================
# [메인]
# ============================================================================

def main():
    print("🔬 [ ta.py 검증 — 우리 구현 vs ta 라이브러리 ]")
    print(f"   외부 ta: {ta_lib.__file__}")
    print(f"   로컬 ta: {local_ta.__file__}")

    tickers = ['APLD', 'SOFI', 'IREN', 'AAPL']
    all_results = {}

    for t in tickers:
        try:
            metrics = compare_indicators(t)
            if metrics is None:
                print(f"\n⚠️ {t}: 데이터 부족, 건너뜀")
                continue
            all_results[t] = metrics
            print_table(t, metrics)
        except Exception as e:
            print(f"\n❌ {t} 실패: {e}")
            import traceback
            traceback.print_exc()

    # 종합 요약
    print(f"\n{'='*78}")
    print("📊 종합 요약")
    print('='*78)
    indicator_names = ['RSI', 'MACD', 'MACD_Signal', 'MACD_Hist', 'BB_Upper',
                       'BB_Lower', 'BandWidth', 'ATR', 'Slow_K', 'Slow_D', 'ADX']
    for ind in indicator_names:
        rels = []
        corrs = []
        for t, ms in all_results.items():
            m = ms.get(ind)
            if m:
                rels.append(m['rel_mae_pct'])
                corrs.append(m['corr'])
        if rels:
            avg_rel = sum(rels) / len(rels)
            avg_corr = sum(corrs) / len(corrs)
            verdict = (
                "✅ 동일" if avg_corr >= 0.99 and avg_rel < 1.0
                else "🟡 유사" if avg_corr >= 0.95
                else "🔴 차이 큼"
            )
            print(f"  {ind:<12} | 평균 rel% {avg_rel:>5.2f} | "
                  f"평균 corr {avg_corr:>6.4f} | {verdict}")


if __name__ == "__main__":
    main()
