"""
Layer 2 최적값 vs 현재 config 값 — 5종목 backtest 비교
"""

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import json

import config
from indicators import Make_Indicators
from predict import Add_AI_Signals
from backtest import Backtest_Strategy
from data_loader import load_ohlcv


CURRENT = {
    'rsi_buy': config.RSI_BUY,
    'rsi_sell': config.RSI_SELL,
    'bb_squeeze_ratio': config.BB_SQUEEZE_RATIO,
    'ai_filter': config.AI_FILTER,
    'trailing_atr_mult': config.TRAILING_ATR_MULT,
}

LAYER2 = {
    'rsi_buy': 42,
    'rsi_sell': 84,
    'bb_squeeze_ratio': 1.6769821748093836,
    'ai_filter': 0.503685973049218,
    'trailing_atr_mult': 3.1676333212914605,
}


def summarize(result):
    tlog = result.get('trade_log')
    if tlog is None or len(tlog) == 0:
        cum = 0.0
    elif 'Return' in tlog.columns:
        # backtest.py의 trade_log['Return']은 비율(0.05=5%)
        cum = ((1 + tlog['Return']).prod() - 1) * 100
    else:
        cum = 0.0
    return {
        'trades': result['trade_count'],
        'win_rate': result['win_rate'] * 100,
        'avg_return': result['avg_return'] * 100,
        'sharpe': result['sharpe'],
        'cumulative': cum,
    }


def main():
    out = {}

    for ticker in config.TEST_TICKERS:
        print(f"\n{'=' * 70}")
        print(f"▶ {ticker}")
        print('=' * 70)
        raw = load_ohlcv(ticker, start=config.START_DATE, drop_intraday=True)
        df = Make_Indicators(raw)
        df = Add_AI_Signals(df)
        df = df.dropna()

        r_cur = Backtest_Strategy(ticker=ticker, df_input=df.copy(), opt_params=CURRENT)
        r_new = Backtest_Strategy(ticker=ticker, df_input=df.copy(), opt_params=LAYER2)

        cur = summarize(r_cur)
        new = summarize(r_new)

        out[ticker] = {'current': cur, 'layer2': new}

        print(f"  현재값       : 매매 {cur['trades']:>2} | 승률 {cur['win_rate']:>5.1f}% | 평균 {cur['avg_return']:>6.2f}% | 누적 {cur['cumulative']:>8.2f}% | sharpe {cur['sharpe']:>6.3f}")
        print(f"  Layer 2 최적 : 매매 {new['trades']:>2} | 승률 {new['win_rate']:>5.1f}% | 평균 {new['avg_return']:>6.2f}% | 누적 {new['cumulative']:>8.2f}% | sharpe {new['sharpe']:>6.3f}")

    print(f"\n{'=' * 70}")
    print("종합 비교 (5종목)")
    print('=' * 70)
    print(f"{'Ticker':<8} {'현재 누적':>12} {'L2 누적':>12} {'Δ누적':>10} {'현재 승률':>10} {'L2 승률':>10} {'현재 매매':>10} {'L2 매매':>10}")
    for t, v in out.items():
        d = v['layer2']['cumulative'] - v['current']['cumulative']
        print(f"{t:<8} {v['current']['cumulative']:>11.2f}% {v['layer2']['cumulative']:>11.2f}% {d:>+9.2f}% {v['current']['win_rate']:>9.1f}% {v['layer2']['win_rate']:>9.1f}% {v['current']['trades']:>10} {v['layer2']['trades']:>10}")

    result_path = ROOT / "phase" / "verify_layer2_result.json"
    result_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n결과 저장: {result_path}")


if __name__ == "__main__":
    main()
