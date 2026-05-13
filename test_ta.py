# ============================================================================
# 🔬 test_ta.py — 기술적 지표 정확도 검증 (v8.1)
# ============================================================================
import numpy as np
import pandas as pd
import config
from ta import Make_Indicators
from data_loader import load_ohlcv

def _load(ticker, start):
    return load_ohlcv(ticker, start=start, drop_intraday=True)

# v9.0: 진단용 표준 유니버스 사용
TEST_TICKERS = config.TEST_TICKERS


def test_rsi_range():
    print("\n" + "="*60)
    print("🔬 [테스트 1] RSI 범위 검증")
    print("="*60)

    for ticker in TEST_TICKERS:
        try:
            df = _load(ticker, '2020-01-01')
            df = Make_Indicators(df)
            rsi = df['RSI'].dropna()

            out_of_range = ((rsi < 0) | (rsi > 100)).sum()
            nan_count = df['RSI'].isna().sum()

            status = "✅ PASS" if out_of_range == 0 else "❌ FAIL"
            print(f"  {ticker:<6} | RSI범위: {rsi.min():.1f}~{rsi.max():.1f} | "
                  f"이상값: {out_of_range}개 | NaN: {nan_count}개 | {status}")
        except Exception as e:
            print(f"  {ticker:<6} | ⚠️ 에러: {e}")


def test_rsi_vs_reference():
    print("\n" + "="*60)
    print("🔬 [테스트 2] RSI 실제값 대조 (TradingView에서 직접 확인)")
    print("="*60)

    ticker = TEST_TICKERS[0]
    df = _load(ticker, '2023-01-01')
    df = Make_Indicators(df)

    print(f"\n  📌 {ticker} 최근 5일 RSI(14) — TradingView와 비교:")
    print(f"  {'날짜':^12} | {'종가':>10} | {'RSI':>8}")
    print(f"  {'-'*40}")
    for _, row in df[['Close', 'RSI']].tail(5).iterrows():
        print(f"  {str(_.date()):^12} | ${row['Close']:>8,.2f} | {row['RSI']:>7.2f}")

    print(f"\n  👉 TradingView에서 {ticker} RSI(14, close) 확인")
    print(f"  👉 오차 ±0.5 이내면 정상")


def test_macd_versions():
    print("\n" + "="*60)
    print("🔬 [테스트 3] MACD 3버전 비교")
    print("="*60)

    df = _load(TEST_TICKERS[0], '2023-01-01')

    for ver in [1, 2, 3]:
        params = {'macd_version': ver}
        df_v = Make_Indicators(df.copy(), params=params)
        macd_last = df_v['MACD'].iloc[-1]
        signal_last = df_v['MACD_Signal'].iloc[-1]
        hist_last = df_v['MACD_Hist'].iloc[-1]

        short, long, sig = config.MACD_VERSIONS[ver]
        print(f"  v{ver} ({short}/{long}/{sig}): "
              f"MACD={macd_last:+.4f} | Signal={signal_last:+.4f} | "
              f"Hist={hist_last:+.4f}")

    print(f"\n  ✅ 3개 버전이 서로 다른 값이면 정상")


def test_bollinger_band():
    print("\n" + "="*60)
    print("🔬 [테스트 4] 볼린저밴드 범위 검증")
    print("="*60)

    for ticker in TEST_TICKERS[:3]:
        df = _load(ticker, '2020-01-01')
        df = Make_Indicators(df)
        df = df.dropna()

        inside = ((df['Close'] >= df['Lower']) & (df['Close'] <= df['Upper'])).mean()
        above = (df['Close'] > df['Upper']).mean()
        below = (df['Close'] < df['Lower']).mean()

        status = "✅ PASS" if inside > 0.85 else "⚠️ CHECK"
        print(f"  {ticker:<6}: 밴드 내 {inside:.1%} | 상단돌파 {above:.1%} | "
              f"하단이탈 {below:.1%} | {status}")

    print(f"\n  ⚠️ 고변동성 종목은 밴드 밖 비율이 대형주보다 높을 수 있음")


def test_atr_sanity():
    print("\n" + "="*60)
    print("🔬 [테스트 5] ATR 합리성 검증")
    print("="*60)

    for ticker in TEST_TICKERS:
        df = _load(ticker, '2023-01-01')
        df = Make_Indicators(df)
        df = df.dropna()

        atr_pct = (df['ATR'] / df['Close'] * 100)
        neg_count = (df['ATR'] < 0).sum()

        # 고변동성 종목은 ATR 15%까지도 정상
        status = "✅ PASS" if neg_count == 0 and atr_pct.mean() < 20 else "❌ FAIL"
        print(f"  {ticker:<6}: ATR평균 ${df['ATR'].mean():.2f} "
              f"({atr_pct.mean():.1f}% of price) | "
              f"음수: {neg_count}개 | {status}")

    print(f"\n  ℹ️ screener 기준: ATR ≥ {config.SCREENER_MIN_VOLATILITY}%")


def test_adx_range():
    print("\n" + "="*60)
    print("🔬 [테스트 6] ADX 범위 및 분포")
    print("="*60)

    for ticker in TEST_TICKERS[:3]:
        df = _load(ticker, '2020-01-01')
        df = Make_Indicators(df)
        adx = df['ADX'].dropna()

        out_of_range = ((adx < 0) | (adx > 100)).sum()
        status = "✅ PASS" if out_of_range == 0 else "❌ FAIL"

        print(f"  {ticker:<6}: ADX 범위 {adx.min():.1f}~{adx.max():.1f} | "
              f"평균 {adx.mean():.1f} | 이상값: {out_of_range}개 | {status}")

        # v8.1: ADX_THRESHOLD=0 이므로 참고용
        low_adx = (adx < 20).mean()
        print(f"         ADX<20: {low_adx:.1%} (참고 — Override 비활성)")


def test_stochastic():
    print("\n" + "="*60)
    print("🔬 [테스트 7] 스토캐스틱 범위 검증")
    print("="*60)

    df = _load(TEST_TICKERS[0], '2023-01-01')
    df = Make_Indicators(df)

    for col in ['Slow_K', 'Slow_D']:
        vals = df[col].dropna()
        out = ((vals < 0) | (vals > 100)).sum()
        status = "✅ PASS" if out == 0 else "❌ FAIL"
        print(f"  {col}: {vals.min():.1f}~{vals.max():.1f} | 이상값: {out}개 | {status}")


def test_derived_signals():
    print("\n" + "="*60)
    print("🔬 [테스트 8] 파생 신호 발생 빈도")
    print("="*60)

    for ticker in TEST_TICKERS[:2]:
        df = _load(ticker, '2020-01-01')
        df = Make_Indicators(df)
        df = df.dropna()
        total = len(df)

        signals = {
            'MACD_Cross(+1)': (df['MACD_Cross'] == 1).sum(),
            'MACD_Cross(-1)': (df['MACD_Cross'] == -1).sum(),
            'Stoch_Cross(+1)': (df['Stoch_Cross'] == 1).sum(),
            'Stoch_Cross(-1)': (df['Stoch_Cross'] == -1).sum(),
            'BB_Squeeze(True)': df['BB_Squeeze'].sum(),
            'Divergence(+1)': (df['Divergence'] == 1).sum(),
            'Divergence(-1)': (df['Divergence'] == -1).sum(),
            'Volume_Ratio>2': (df['Volume_Ratio'] > 2).sum(),
            'Volume_Ratio>3': (df['Volume_Ratio'] > 3).sum(),
        }

        print(f"\n  📊 {ticker} ({total}일):")
        for name, count in signals.items():
            freq = count / total * 100
            status = "✅" if 0 < count < total * 0.3 else "⚠️ CHECK"
            print(f"    {name:<22}: {count:>4}회 ({freq:.1f}%) {status}")


def test_disparity():
    print("\n" + "="*60)
    print("🔬 [테스트 9] 이격도 분포")
    print("="*60)

    for ticker in TEST_TICKERS:
        df = _load(ticker, '2020-01-01')
        df = Make_Indicators(df)
        disp = df['Disparity'].dropna()

        normal = ((disp >= 80) & (disp <= 120)).mean()
        print(f"  {ticker:<6}: 범위 {disp.min():.1f}~{disp.max():.1f} | "
              f"평균 {disp.mean():.1f} | 80~120 내: {normal:.1%}")

    print(f"  ℹ️ 이격도 100 기준 ± 범위 확인 — 고변동성 종목은 범위가 더 넓음")
    print(f"  ⚠️ 고변동성 종목은 이격도 범위가 넓을 수 있음")


def test_volume_ratio():
    """v8.1 신규: Volume_Ratio 분포 확인 (AI 피처로 승격)"""
    print("\n" + "="*60)
    print("🔬 [테스트 10] Volume_Ratio 분포 (v8.1 신규 피처)")
    print("="*60)

    for ticker in TEST_TICKERS:
        df = _load(ticker, '2020-01-01')
        df = Make_Indicators(df)
        vr = df['Volume_Ratio'].dropna()

        print(f"  {ticker:<6}: 평균 {vr.mean():.2f} | 중앙값 {vr.median():.2f} | "
              f"최대 {vr.max():.1f}x")
        print(f"         >1.5x: {(vr>1.5).mean():.1%} | "
              f">2x: {(vr>2).mean():.1%} | "
              f">3x: {(vr>3).mean():.1%}")

    print(f"\n  ℹ️ 급등 직전 거래량 2~3배 폭증 → Volume_Ratio>2 빈도가 핵심")



import sys
import os

class Logger(object):
    def __init__(self, filename="results/default.txt"):
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        self.terminal = sys.stdout
        self.log = open(filename, "w", encoding='utf-8')

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        self.terminal.flush()
        self.log.flush()

if __name__ == "__main__":
    sys.stdout = Logger('results/test_ta_results.txt')
    print("🔬 [Richman] ta.py 기술적 지표 종합 검증 (v8.1)")
    print(f"   대상: {TEST_TICKERS}")
    print("="*60)

    test_rsi_range()
    test_rsi_vs_reference()
    test_macd_versions()
    test_bollinger_band()
    test_atr_sanity()
    test_adx_range()
    test_stochastic()
    test_derived_signals()
    test_disparity()
    test_volume_ratio()

    print("\n" + "="*60)
    print("✅ ta.py 검증 완료!")
    print("="*60)