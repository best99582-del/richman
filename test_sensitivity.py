# ============================================================================
# 🔬 test_sensitivity.py — 핵심 파라미터 민감도 분석
# ============================================================================
import os
import sys
import numpy as np

from indicators import Make_Indicators
from predict import Add_AI_Signals, Create_Windowed_Data, cv_precision
from backtest import Backtest_Strategy
import config
from data_loader import load_ohlcv

TEST_TICKERS = config.TEST_TICKERS
OUTPUT_FILE = 'results/sensitivity_results.txt'


# ============================================================================
# [공통] 데이터 1회 전처리 (모든 백테스트 테스트에서 공유)
# ============================================================================

def _prepare_all() -> dict:
    """전 종목 지표+AI 신호 산출 — 최초 1회만 실행 (현 config의 AI_FILTER/FP/TP 기준)"""
    print("⏳ 데이터 전처리 중 (1회)...")
    stock_data = {}
    for ticker in TEST_TICKERS:
        try:
            df = load_ohlcv(ticker, start=config.START_DATE, drop_intraday=True)
            df = Make_Indicators(df)
            df = Add_AI_Signals(df)
            df = df.dropna()
            stock_data[ticker] = df
            print(f"  ✅ {ticker}: {len(df)}일")
        except Exception as e:
            print(f"  ⚠️ {ticker} 실패: {e}")
    return stock_data


def _prepare_indicators_only() -> dict:
    """지표만 산출한 데이터 — FP/TP sweep용 (Add_AI_Signals를 sweep마다 다시 호출)"""
    print("⏳ 지표 산출 중 (FP/TP sweep용)...")
    stock_data = {}
    for ticker in TEST_TICKERS:
        try:
            df = load_ohlcv(ticker, start=config.START_DATE, drop_intraday=True)
            df = Make_Indicators(df).dropna()
            stock_data[ticker] = df
            print(f"  ✅ {ticker}: {len(df)}일")
        except Exception as e:
            print(f"  ⚠️ {ticker} 실패: {e}")
    return stock_data


# ============================================================================
# [공통] 단일 파라미터 스윕 + 결과 출력
# ============================================================================

def _sweep(stock_data: dict, param_name: str, values: list) -> list:
    """
    파라미터 값 목록에 대해 백테스트를 반복하고 성과 리스트 반환.
    나머지 파라미터는 config 기본값 유지 (backtest.py params.update 방식).
    """
    rows = []
    for val in values:
        total_trades, total_wins = 0, 0
        all_returns, all_losses = [], []

        for ticker, df in stock_data.items():
            result = Backtest_Strategy(
                ticker=ticker,
                df_input=df.copy(),
                opt_params={param_name: val}
            )
            tc = result['trade_count']
            total_trades += tc
            if tc > 0:
                total_wins += result['win_rate'] * tc
                all_returns.append(result['avg_return'])
                all_losses.append(result['trade_log']['Return'].min())

        rows.append({
            'value': val,
            'trades': total_trades,
            'win_rate': total_wins / total_trades if total_trades > 0 else 0.0,
            'avg_ret': np.mean(all_returns) if all_returns else 0.0,
            'max_loss': min(all_losses) if all_losses else 0.0,
        })
    return rows


def _verdict(r: dict) -> str:
    if r['trades'] < 5:
        return "⚠️ 기회 부족"
    if r['win_rate'] > 0.5 and r['avg_ret'] > 0:
        return "✅ 양호"
    if r['win_rate'] > 0.45:
        return "⚠️ 보통"
    return "❌ 부진"


def _print_sweep(rows: list, param_name: str, current_val, col_label: str):
    print(f"\n  {col_label:>10} | {'매매수':>6} | {'승률':>7} | {'평균수익':>8} | {'최대손실':>8} | 판정")
    print(f"  {'─'*62}")
    for r in rows:
        marker = " ◀현재" if abs(r['value'] - current_val) < 1e-4 else ""
        print(
            f"  {r['value']:>10.3g} | {r['trades']:>6} | "
            f"{r['win_rate']:>6.1%} | {r['avg_ret']:>+7.2%} | "
            f"{r['max_loss']:>+7.2%} | {_verdict(r)}{marker}"
        )
    print(f"\n  현재: {param_name} = {current_val}")


# ============================================================================
# [검증 1] AI_TARGET_PCT — 모델 양성 비율 캘리브레이션
# ============================================================================

def test_target_calibration(stock_data: dict):
    """
    AI_TARGET_PCT 별 양성 비율 확인 (백테스트가 아닌 모델 설정 진단).
    Close 기준 15~45%가 AI가 실질적으로 구별할 수 있는 적정 범위.
    """
    print("\n" + "="*70)
    print("🔬 [검증 1] AI_TARGET_PCT 캘리브레이션 — 양성 비율 확인")
    print(f"   피처: {config.AI_FEATURES}")
    print("="*70)

    targets = [3, 5, 7, 10, 15, 20]

    print(f"\n  {'목표(%)':>8} |", end='')
    for t in TEST_TICKERS:
        print(f" {t:>8} |", end='')
    print(f" {'평균':>8} | 판정")
    print(f"  {'─'*80}")

    for target in targets:
        rates = []
        row = f"  {target:>6}% |"
        for _, df in stock_data.items():
            try:
                _, y = Create_Windowed_Data(
                    df, config.AI_FEATURES, config.AI_WINDOW_SIZE,
                    target, config.AI_FORECAST_PERIOD
                )
                pos_rate = np.mean(y) * 100
                rates.append(pos_rate)
                row += f" {pos_rate:>6.1f}% |"
            except Exception:
                row += f"     ERR |"

        avg = np.mean(rates) if rates else 0
        if avg < 8:
            verdict = "❌ 너무 희귀 (AI 학습 불가)"
        elif avg > 55:
            verdict = "❌ 변별력 없음 (기저 너무 높음)"
        elif 15 <= avg <= 45:
            verdict = "✅ 최적"
        else:
            verdict = "⚠️ 보통"
        print(row + f" {avg:>6.1f}% | {verdict}")

    print(f"\n  현재: AI_TARGET_PCT={config.AI_TARGET_PCT}% / {config.AI_FORECAST_PERIOD}일 (Close 기준)")
    print(f"  ℹ️ 15~45%가 최적 — 이 범위 벗어나면 AI_TARGET_PCT 조정 후 재실행")


# ============================================================================
# [검증 2] BB_SQUEEZE_RATIO — 발동 빈도 + 백테스트 성과
# ============================================================================

def test_bb_squeeze(stock_data: dict):
    """
    BB_SQUEEZE_RATIO 별 연간 발동 빈도와 실제 백테스트 성과를 함께 확인.
    발동이 너무 잦으면 노이즈, 너무 드물면 신호 없음 — 연 5~20회가 적정.
    """
    print("\n" + "="*70)
    print("🔬 [검증 2] BB_SQUEEZE_RATIO — 발동 빈도 + 백테스트 성과")
    print("="*70)

    ratios = [1.2, 1.5, 1.8, 2.0, 2.5, 3.0]

    print("\n  [발동 빈도]")
    for ticker in list(stock_data.keys())[:3]:
        df = stock_data[ticker]
        print(f"\n  📊 {ticker} ({len(df)}일):")
        for ratio in ratios:
            squeeze = df['BandWidth'] > (df['BB_Width_MA'] * ratio)
            count = squeeze.sum()
            yearly = count / (len(df) / 252)
            marker = " ◀현재" if abs(ratio - config.BB_SQUEEZE_RATIO) < 0.05 else ""
            print(f"    ratio={ratio:.1f}: {count:>4}회 (연 {yearly:.0f}회){marker}")

    print(f"\n  ℹ️ 연 5~20회가 적정 (0회=비활성, 100+회=노이즈)")

    print("\n  [백테스트 성과]")
    rows = _sweep(stock_data, 'bb_squeeze_ratio', ratios)
    _print_sweep(rows, 'BB_SQUEEZE_RATIO', config.BB_SQUEEZE_RATIO, 'ratio')


# ============================================================================
# [검증 3] AI_FILTER — 매수 확신도 임계값
# ============================================================================

def test_ai_filter(stock_data: dict):
    """
    AI_FILTER 임계값 별 매매 횟수·승률·수익률 비교.
    너무 낮으면 노이즈 매수, 너무 높으면 기회 부족.
    """
    print("\n" + "="*70)
    print("🔬 [검증 3] AI_FILTER — 매수 확신도 임계값별 성과")
    print("="*70)

    thresholds = [0.50, 0.52, 0.55, 0.58, 0.60, 0.63, 0.65, 0.70]
    rows = _sweep(stock_data, 'ai_filter', thresholds)
    _print_sweep(rows, 'AI_FILTER', config.AI_FILTER, 'AI필터')
    print(f"  ℹ️ 승률 50%+ & 평균수익 양수인 가장 낮은 값이 최적 (기회 최대화)")


# ============================================================================
# [검증 4] RSI_BUY / RSI_SELL — 매수·매도 기준 (신규)
# ============================================================================

def test_rsi_thresholds(stock_data: dict):
    """
    RSI_BUY (과매도 반등 진입 기준)와 RSI_SELL (과매수 이탈 매도 기준) 비교.
    각각 독립 스윕 — 한쪽 변경 시 나머지는 config 기본값 유지.
    """
    print("\n" + "="*70)
    print("🔬 [검증 4] RSI_BUY / RSI_SELL — 매수·매도 기준별 성과")
    print("="*70)

    print("\n  --- RSI_BUY (과매도 반등 진입 기준) ---")
    rows = _sweep(stock_data, 'rsi_buy', [30, 35, 40, 45, 50, 55])
    _print_sweep(rows, 'RSI_BUY', config.RSI_BUY, 'RSI_BUY')
    print(f"  ℹ️ 낮을수록 진입 조건 엄격 (신호 줄고 정밀도 상승)")

    print("\n  --- RSI_SELL (과매수 이탈 매도 기준) ---")
    rows = _sweep(stock_data, 'rsi_sell', [65, 68, 70, 72, 75, 78, 80])
    _print_sweep(rows, 'RSI_SELL', config.RSI_SELL, 'RSI_SELL')
    print(f"  ℹ️ 높을수록 수익 극대화 시도 — 단, 급락 시 대응 늦어짐")


# ============================================================================
# [검증 5] TRAILING_ATR_MULT — 트레일링 스탑 배수
# ============================================================================

def test_trailing_stop(stock_data: dict):
    """
    TRAILING_ATR_MULT 별 승률·수익·최대손실 비교.
    고변동성 종목(ATR 3~10%)은 넓은 스탑(3.5~5.0x)이 조기 청산을 방지.
    """
    print("\n" + "="*70)
    print("🔬 [검증 5] TRAILING_ATR_MULT — 트레일링 스탑 배수별 성과")
    print("="*70)

    mults = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
    rows = _sweep(stock_data, 'trailing_atr_mult', mults)
    _print_sweep(rows, 'TRAILING_ATR_MULT', config.TRAILING_ATR_MULT, 'ATR배수')
    print(f"  ℹ️ 승률↑ + 최대손실↑ 사이의 균형점 선택 (감내 가능한 최대손실 먼저 결정)")


# ============================================================================
# [검증 6] AI_FORECAST_PERIOD — 보유기간 (분류 정밀도 + 매매 성과)
# ============================================================================

def _fp_tp_sweep(indicators_dict: dict, kind: str, values: list) -> list:
    """FP 또는 TP를 sweep — 각 값마다 Add_AI_Signals 재호출 + 매매 시뮬.

    Args:
        indicators_dict: {ticker: indicators-only df}
        kind: 'fp' 또는 'tp'
        values: sweep 값 리스트
    """
    rows = []
    for val in values:
        # 각 종목에 새 라벨 정의로 Walk-Forward AI 신호 부착
        cv_precs, total_trades, total_wins = [], 0, 0
        all_returns, all_losses = [], []
        for ticker, df_ind in indicators_dict.items():
            if kind == 'fp':
                kwargs_signal = {'forecast_period': val}
                kwargs_cv = {'forecast_period': val}
            else:  # tp
                kwargs_signal = {'target_pct': val}
                kwargs_cv = {'target_pct': val}

            # 분류 정밀도 (5-Fold CV) — 신호 자체 품질
            prec, _ = cv_precision(df_ind, **kwargs_cv)
            cv_precs.append(prec)

            # 매매 시뮬 (Walk-Forward 신호 부착 후 backtest)
            df_sig = Add_AI_Signals(df_ind.copy(), **kwargs_signal).dropna()
            result = Backtest_Strategy(ticker=ticker, df_input=df_sig)
            tc = result['trade_count']
            total_trades += tc
            if tc > 0:
                total_wins += result['win_rate'] * tc
                all_returns.append(result['avg_return'])
                all_losses.append(result['trade_log']['Return'].min())

        rows.append({
            'value': val,
            'cv_precision': float(np.mean(cv_precs)) if cv_precs else 0.0,
            'trades': total_trades,
            'win_rate': total_wins / total_trades if total_trades > 0 else 0.0,
            'avg_ret': float(np.mean(all_returns)) if all_returns else 0.0,
            'max_loss': float(min(all_losses)) if all_losses else 0.0,
        })
    return rows


def _print_fp_tp_sweep(rows: list, param_name: str, current_val, col_label: str):
    print(f"\n  {col_label:>8} | {'CV정밀도':>8} | {'매매수':>6} | {'승률':>7} | {'평균수익':>8} | {'최대손실':>8} | 판정")
    print(f"  {'─'*78}")
    for r in rows:
        marker = " ◀현재" if abs(r['value'] - current_val) < 1e-4 else ""
        # 판정: 매매수 부족 / CV 정밀도 / 승률·평균 종합
        if r['trades'] < 10:
            verdict = "⚠️ 기회 부족"
        elif r['win_rate'] > 0.50 and r['avg_ret'] > 0 and r['cv_precision'] >= 0.50:
            verdict = "✅ 양호"
        elif r['win_rate'] > 0.45:
            verdict = "⚠️ 보통"
        else:
            verdict = "❌ 부진"
        print(
            f"  {r['value']:>8.3g} | {r['cv_precision']:>7.3f} | "
            f"{r['trades']:>6} | {r['win_rate']:>6.1%} | "
            f"{r['avg_ret']:>+7.2%} | {r['max_loss']:>+7.2%} | {verdict}{marker}"
        )
    print(f"\n  현재: {param_name} = {current_val}")


def test_forecast_period(indicators_dict: dict):
    """AI_FORECAST_PERIOD 별 분류 정밀도 + 매매 성과.

    값마다 Add_AI_Signals를 다시 호출 (신호 정의 자체가 바뀌므로).
    """
    print("\n" + "="*84)
    print("🔬 [검증 6] AI_FORECAST_PERIOD — 보유기간 (분류 정밀도 + 매매 성과)")
    print("="*84)
    fps = [3, 5, 7, 10, 14]
    rows = _fp_tp_sweep(indicators_dict, 'fp', fps)
    _print_fp_tp_sweep(rows, 'AI_FORECAST_PERIOD', config.AI_FORECAST_PERIOD, 'FP(일)')
    print(f"  ℹ️ 짧을수록 신호 빈도↑ 정밀도↓ — 단기 스윙은 7~10일이 합리적")


def test_target_pct(indicators_dict: dict):
    """AI_TARGET_PCT 별 분류 정밀도 + 매매 성과."""
    print("\n" + "="*84)
    print("🔬 [검증 7] AI_TARGET_PCT — 목표수익률 (분류 정밀도 + 매매 성과)")
    print("="*84)
    tps = [5, 7, 10, 15, 20]
    rows = _fp_tp_sweep(indicators_dict, 'tp', tps)
    _print_fp_tp_sweep(rows, 'AI_TARGET_PCT', config.AI_TARGET_PCT, 'TP(%)')
    print(f"  ℹ️ 낮을수록 양성비↑ 정밀도↑ — 단 너무 낮으면 변별력 상실 (양성비 55%+ 경계)")


# ============================================================================
# [실행]
# ============================================================================

if __name__ == "__main__":
    os.makedirs('results', exist_ok=True)

    class Tee:
        def __init__(self, *files): self.files = files
        def write(self, s):
            for f in self.files: f.write(s)
        def flush(self):
            for f in self.files: f.flush()

    log_f = open(OUTPUT_FILE, 'w', encoding='utf-8')
    sys.stdout = Tee(sys.__stdout__, log_f)

    print("🔬 [Richman] 핵심 파라미터 민감도 분석")
    print(f"   대상: {TEST_TICKERS}")
    print(f"   피처: {config.AI_FEATURES}")
    print(f"   타겟: {config.AI_TARGET_PCT}% / {config.AI_FORECAST_PERIOD}일 (Close 기준)")
    print(f"   평가 방식:")
    print(f"     - AI 신호 부착: Add_AI_Signals (Walk-Forward, holdout=20%)")
    print(f"     - 성과 측정: Backtest_Strategy (trade-by-trade, 미래누수 없음)")
    print(f"     - precision/recall 등 분류 메트릭은 test_predict.py 의 CV/holdout 비교 참조")
    print(f"   ⏳ 약 20~30분 소요\n")

    stock_data = _prepare_all()

    test_target_calibration(stock_data)   # [1] 모델 설정 진단 (양성비)
    test_bb_squeeze(stock_data)           # [2] BB 스퀴즈 발동 빈도 + 성과
    test_ai_filter(stock_data)            # [3] AI 필터 임계값
    test_rsi_thresholds(stock_data)       # [4] RSI 매수/매도 기준
    test_trailing_stop(stock_data)        # [5] 트레일링 스탑 배수

    # [6, 7] FP/TP — 각 값마다 Add_AI_Signals 재호출 필요 → indicators-only 데이터
    indicators_dict = _prepare_indicators_only()
    test_forecast_period(indicators_dict) # [6] 보유기간 (신규)
    test_target_pct(indicators_dict)      # [7] 목표수익률 (신규, 양성비뿐 아니라 매매까지)

    sys.stdout = sys.__stdout__
    log_f.close()

    print("\n" + "="*70)
    print(f"📋 결과 저장: {OUTPUT_FILE}")
    print("   다음 단계: 결과 확인 → config.py 반영 → optimize.py 실행")
    print("="*70)
