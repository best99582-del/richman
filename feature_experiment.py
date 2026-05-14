# ============================================================================
# 🔬 [퀀트 유니버스] AI 피처 비교 실험 (feature_experiment.py)
# ============================================================================
# 역할: 여러 피처 세트로 predict + backtest를 돌려 어떤 조합이 최적인지 비교
# 사용법: python feature_experiment.py
#
# 실험 설계:
#   - 동일 종목, 동일 기간, 동일 하이퍼파라미터
#   - 피처 세트만 변경하여 정밀도/승률/수익률 비교
#   - 과적합 위험도 = (train 정밀도 - test 정밀도) 격차로 측정
# ============================================================================

import time
import numpy as np
from sklearn.model_selection import TimeSeriesSplit
import pandas as pd

import config
from data_loader import load_ohlcv
from indicators import Make_Indicators
from predict import Create_Windowed_Data, _create_model, _calc_pos_weight, _laplace_precision
from xgboost import XGBClassifier

# ============================================================================
# [설정] 실험할 피처 세트들
# ============================================================================

FEATURE_SETS = {
    # A: 현재 운용 중 (config.AI_FEATURES와 동일, 6개)
    'A_현재6개': [
        'RSI', 'Disparity', 'BandWidth', 'Volume_Ratio', 'Slow_K', 'Slow_D',
    ],
    # B: 현재 + ADX (7개) — 스토캐스틱 유지 + 추세 강도 추가
    'B_현재+ADX_7개': [
        'RSI', 'Disparity', 'BandWidth', 'Volume_Ratio', 'Slow_K', 'Slow_D', 'ADX',
    ],
    # C: 스토캐스틱 제외 + ADX (5개) — 타점 신호를 추세 신호로 교체
    'C_ADX대체_5개': [
        'RSI', 'Disparity', 'BandWidth', 'Volume_Ratio', 'ADX',
    ],
}

# 실험 대상 종목 — config.TEST_TICKERS 참조
TEST_TICKERS = config.TEST_TICKERS

WINDOW_SIZE = config.AI_WINDOW_SIZE
TARGET_PCT = config.AI_TARGET_PCT
FORECAST_PERIOD = config.AI_FORECAST_PERIOD
AI_FILTER = config.AI_FILTER


# ============================================================================
# [핵심] 단일 종목 × 단일 피처세트 평가
# ============================================================================

def evaluate_feature_set(
    ticker: str,
    df: pd.DataFrame,
    features: list,
    n_splits: int = 5
) -> dict:
    """
    5-Fold CV로 피처 세트의 성능을 측정합니다.

    Returns:
        dict: {
            'precision': 평균 라플라스 정밀도,
            'train_precision': 학습 정밀도 (과적합 측정용),
            'overfit_gap': train - test 정밀도 격차,
            'signal_count': 총 매수 신호 수,
            'pos_ratio': 양성 비율 (클래스 균형),
            'fold_details': 각 Fold 결과 리스트,
        }
    """
    tscv = TimeSeriesSplit(n_splits=n_splits)
    test_precisions = []
    train_precisions = []
    total_signals = 0

    X_all, y_all = Create_Windowed_Data(
        df, features, WINDOW_SIZE, TARGET_PCT, FORECAST_PERIOD
    )

    if len(X_all) < 200:
        return None

    pos_ratio = np.mean(y_all)
    indices = np.arange(len(X_all))

    for train_idx, test_idx in tscv.split(indices):
        if len(train_idx) <= FORECAST_PERIOD + WINDOW_SIZE:
            continue

        # Gap 적용 (데이터 누수 차단)
        safe_train_idx = train_idx[:-FORECAST_PERIOD]

        X_train = X_all[safe_train_idx]
        y_train = y_all[safe_train_idx]
        X_test = X_all[test_idx]
        y_test = y_all[test_idx]

        if len(set(y_train)) < 2 or len(y_test) == 0:
            continue

        model = _create_model(_calc_pos_weight(y_train))
        model.fit(X_train, y_train)

        # Test 정밀도
        test_probs = model.predict_proba(X_test)[:, 1]
        test_preds = (test_probs >= AI_FILTER).astype(int)
        if np.sum(test_preds) > 0:
            test_precisions.append(_laplace_precision(test_preds, y_test))
            total_signals += int(np.sum(test_preds))

        # Train 정밀도 (과적합 측정용)
        train_probs = model.predict_proba(X_train)[:, 1]
        train_preds = (train_probs >= AI_FILTER).astype(int)
        if np.sum(train_preds) > 0:
            train_precisions.append(_laplace_precision(train_preds, y_train))

    if not test_precisions:
        return None

    test_avg = np.mean(test_precisions)
    train_avg = np.mean(train_precisions) if train_precisions else test_avg

    return {
        'precision': round(test_avg, 4),
        'train_precision': round(train_avg, 4),
        'overfit_gap': round(train_avg - test_avg, 4),
        'signal_count': total_signals,
        'pos_ratio': round(pos_ratio, 4),
        'n_features': len(features),
        'n_dimensions': len(features) * WINDOW_SIZE,
    }


# ============================================================================
# [메인] 전체 실험 실행
# ============================================================================

def run_experiment():
    print("=" * 85)
    print("🔬 [ AI 피처 비교 실험 ]")
    print(f"   종목: {TEST_TICKERS}")
    print(f"   윈도우: {WINDOW_SIZE}일 | 목표: {TARGET_PCT}% | 예측기간: {FORECAST_PERIOD}일")
    print(f"   AI필터: {AI_FILTER}")
    print("=" * 85)

    # --- [1] 데이터 전처리 (1회) ---
    stock_data = {}
    for ticker in TEST_TICKERS:
        try:
            print(f"  ⏳ {ticker} 데이터 로드 + 지표 산출...")
            df = load_ohlcv(ticker, start=config.START_DATE, drop_intraday=True)
            df = Make_Indicators(df)
            df = df.dropna()
            if len(df) >= 300:
                stock_data[ticker] = df
                print(f"     ✅ {len(df)}일 데이터")
            else:
                print(f"     ⚠️ 데이터 부족 ({len(df)}일), 스킵")
        except Exception as e:
            print(f"     ❌ 실패: {e}")

    if not stock_data:
        print("❌ 분석 가능한 종목이 없습니다.")
        return

    # --- [2] 실험 실행 ---
    results = []

    for set_name, features in FEATURE_SETS.items():
        print(f"\n{'─' * 85}")
        print(f"  📊 {set_name}: {features}")
        print(f"     차원: {len(features)} 피처 × {WINDOW_SIZE}일 = {len(features) * WINDOW_SIZE}D")

        set_precisions = []
        set_overfit = []
        set_signals = 0

        for ticker, df in stock_data.items():
            # 피처 존재 여부 확인
            missing = [f for f in features if f not in df.columns]
            if missing:
                print(f"     ⚠️ {ticker}: 피처 누락 {missing}")
                continue

            result = evaluate_feature_set(ticker, df, features)
            if result is None:
                print(f"     ⚠️ {ticker}: 데이터 부족")
                continue

            set_precisions.append(result['precision'])
            set_overfit.append(result['overfit_gap'])
            set_signals += result['signal_count']

            emoji = '✅' if result['precision'] >= 0.55 else '⚠️'
            gap_emoji = '🟢' if result['overfit_gap'] < 0.1 else '🔴'
            print(f"     {emoji} {ticker}: 정밀도 {result['precision']:.3f} | "
                  f"과적합갭 {result['overfit_gap']:+.3f} {gap_emoji} | "
                  f"신호 {result['signal_count']}회")

        if set_precisions:
            avg_prec = np.mean(set_precisions)
            avg_gap = np.mean(set_overfit)
            results.append({
                'Set': set_name,
                'Features': len(features),
                'Dims': len(features) * WINDOW_SIZE,
                'Avg_Precision': round(avg_prec, 4),
                'Avg_Overfit_Gap': round(avg_gap, 4),
                'Total_Signals': set_signals,
                'Score': round(avg_prec - abs(avg_gap) * 0.5, 4),
            })

    # --- [3] 최종 비교 ---
    if not results:
        print("\n❌ 비교 가능한 결과가 없습니다.")
        return

    results.sort(key=lambda x: x['Score'], reverse=True)

    print("\n\n" + "=" * 85)
    print("🏆 [ 피처 세트 비교 결과 — 종합 순위 ]")
    print("=" * 85)
    print(f"  {'순위':>4} | {'세트':<16} | {'피처':>4} | {'차원':>4} | "
          f"{'정밀도':>7} | {'과적합갭':>8} | {'신호수':>6} | {'종합점수':>8}")
    print(f"{'─' * 85}")

    for rank, r in enumerate(results, 1):
        medal = {1: '🥇', 2: '🥈', 3: '🥉'}.get(rank, '  ')
        gap_color = '🟢' if abs(r['Avg_Overfit_Gap']) < 0.08 else '🔴'
        print(f"  {medal}{rank:>2} | {r['Set']:<16} | {r['Features']:>4} | "
              f"{r['Dims']:>4}D | {r['Avg_Precision']:>6.3f} | "
              f"{r['Avg_Overfit_Gap']:>+7.3f} {gap_color} | "
              f"{r['Total_Signals']:>6} | {r['Score']:>7.4f}")

    print(f"{'─' * 85}")
    print(f"\n  📐 종합점수 = 정밀도 - |과적합갭| × 0.5")
    print(f"  💡 과적합갭이 낮을수록(🟢), 실전에서도 비슷한 성능 기대")
    print(f"  💡 신호수가 너무 적으면 매매 기회 부족, 너무 많으면 과매매")

    winner = results[0]
    print(f"\n  🏆 추천: {winner['Set']}")
    print(f"     → config.py AI_FEATURES를 이 세트로 확정 후 optimize.py 재실행")
    print("=" * 85)


# ============================================================================
# [실험 2] 과적합 완화 실험 — 정규화 + 윈도우 축소
# ============================================================================
# 피처는 A_현재6개 고정. 모델 정규화/윈도우 크기를 바꿔 과적합갭을 완화.
# 4가지 조합:
#   Baseline      : depth=3, window=5, reg_alpha=0,   reg_lambda=1
#   Reg           : depth=2, window=5, reg_alpha=0.5, reg_lambda=2
#   Window        : depth=3, window=3, reg_alpha=0,   reg_lambda=1
#   Reg+Window    : depth=2, window=3, reg_alpha=0.5, reg_lambda=2
# ============================================================================

OVERFIT_FEATURES = ['RSI', 'Disparity', 'BandWidth', 'Volume_Ratio', 'Slow_K', 'Slow_D']

OVERFIT_CONFIGS = {
    'Baseline':   {'max_depth': 3, 'window': 5, 'reg_alpha': 0.0, 'reg_lambda': 1.0},
    'Reg':        {'max_depth': 2, 'window': 5, 'reg_alpha': 0.5, 'reg_lambda': 2.0},
    'Window':     {'max_depth': 3, 'window': 3, 'reg_alpha': 0.0, 'reg_lambda': 1.0},
    'Reg+Window': {'max_depth': 2, 'window': 3, 'reg_alpha': 0.5, 'reg_lambda': 2.0},
}


def _make_tuned_model(weight: float, max_depth: int, reg_alpha: float, reg_lambda: float):
    """과적합 완화 실험용 모델 팩토리 — depth, reg_alpha, reg_lambda 조정"""
    return XGBClassifier(
        n_estimators=100, max_depth=max_depth, learning_rate=0.01,
        subsample=0.8, colsample_bytree=0.8,
        reg_alpha=reg_alpha, reg_lambda=reg_lambda,
        scale_pos_weight=weight,
        random_state=42, eval_metric='logloss', n_jobs=-1,
    )


def evaluate_overfit_config(
    df: pd.DataFrame,
    features: list,
    window: int,
    max_depth: int,
    reg_alpha: float,
    reg_lambda: float,
    n_splits: int = 5,
) -> dict:
    """단일 종목 × 단일 설정으로 5-Fold CV 평가"""
    X_all, y_all = Create_Windowed_Data(
        df, features, window, TARGET_PCT, FORECAST_PERIOD
    )
    if len(X_all) < 200:
        return None

    tscv = TimeSeriesSplit(n_splits=n_splits)
    test_precisions, train_precisions = [], []
    total_signals = 0

    for train_idx, test_idx in tscv.split(np.arange(len(X_all))):
        if len(train_idx) <= FORECAST_PERIOD + window:
            continue
        safe_train_idx = train_idx[:-FORECAST_PERIOD]

        X_train, y_train = X_all[safe_train_idx], y_all[safe_train_idx]
        X_test, y_test = X_all[test_idx], y_all[test_idx]

        if len(set(y_train)) < 2 or len(y_test) == 0:
            continue

        model = _make_tuned_model(
            _calc_pos_weight(y_train), max_depth, reg_alpha, reg_lambda
        )
        model.fit(X_train, y_train)

        test_preds = (model.predict_proba(X_test)[:, 1] >= AI_FILTER).astype(int)
        if np.sum(test_preds) > 0:
            test_precisions.append(_laplace_precision(test_preds, y_test))
            total_signals += int(np.sum(test_preds))

        train_preds = (model.predict_proba(X_train)[:, 1] >= AI_FILTER).astype(int)
        if np.sum(train_preds) > 0:
            train_precisions.append(_laplace_precision(train_preds, y_train))

    if not test_precisions:
        return None

    test_avg = float(np.mean(test_precisions))
    train_avg = float(np.mean(train_precisions)) if train_precisions else test_avg

    return {
        'precision': round(test_avg, 4),
        'train_precision': round(train_avg, 4),
        'overfit_gap': round(train_avg - test_avg, 4),
        'signal_count': total_signals,
        'n_dimensions': len(features) * window,
    }


def run_overfit_experiment():
    print("=" * 85)
    print("🔬 [ 과적합 완화 실험 — 정규화 + 윈도우 축소 ]")
    print(f"   피처: A_현재6개 고정 — {OVERFIT_FEATURES}")
    print(f"   종목: {TEST_TICKERS}")
    print(f"   목표: {TARGET_PCT}% | 예측기간: {FORECAST_PERIOD}일 | AI필터: {AI_FILTER}")
    print("=" * 85)

    # --- [1] 데이터 전처리 (1회) ---
    stock_data = {}
    for ticker in TEST_TICKERS:
        try:
            print(f"  ⏳ {ticker} 데이터 로드 + 지표 산출...")
            df = load_ohlcv(ticker, start=config.START_DATE, drop_intraday=True)
            df = Make_Indicators(df)
            df = df.dropna()
            if len(df) >= 300:
                stock_data[ticker] = df
                print(f"     ✅ {len(df)}일 데이터")
            else:
                print(f"     ⚠️ 데이터 부족 ({len(df)}일), 스킵")
        except Exception as e:
            print(f"     ❌ 실패: {e}")

    if not stock_data:
        print("❌ 분석 가능한 종목이 없습니다.")
        return

    # --- [2] 4개 설정 × 5종목 = 20회 CV ---
    results = []
    for cfg_name, cfg in OVERFIT_CONFIGS.items():
        print(f"\n{'─' * 85}")
        print(f"  ⚙️ {cfg_name}: depth={cfg['max_depth']}, window={cfg['window']}, "
              f"reg_alpha={cfg['reg_alpha']}, reg_lambda={cfg['reg_lambda']}")
        print(f"     차원: {len(OVERFIT_FEATURES)} × {cfg['window']} = "
              f"{len(OVERFIT_FEATURES) * cfg['window']}D")

        precs, gaps, signals = [], [], 0
        for ticker, df in stock_data.items():
            r = evaluate_overfit_config(
                df, OVERFIT_FEATURES,
                window=cfg['window'],
                max_depth=cfg['max_depth'],
                reg_alpha=cfg['reg_alpha'],
                reg_lambda=cfg['reg_lambda'],
            )
            if r is None:
                print(f"     ⚠️ {ticker}: 데이터 부족")
                continue

            precs.append(r['precision'])
            gaps.append(r['overfit_gap'])
            signals += r['signal_count']

            emoji = '✅' if r['precision'] >= 0.55 else '⚠️'
            gap_emoji = '🟢' if r['overfit_gap'] < 0.2 else ('🟡' if r['overfit_gap'] < 0.3 else '🔴')
            print(f"     {emoji} {ticker}: 정밀도 {r['precision']:.3f} "
                  f"(train {r['train_precision']:.3f}) | "
                  f"갭 {r['overfit_gap']:+.3f} {gap_emoji} | "
                  f"신호 {r['signal_count']}회")

        if precs:
            avg_prec = float(np.mean(precs))
            avg_gap = float(np.mean(gaps))
            results.append({
                'Config': cfg_name,
                'Dims': len(OVERFIT_FEATURES) * cfg['window'],
                'Avg_Precision': round(avg_prec, 4),
                'Avg_Overfit_Gap': round(avg_gap, 4),
                'Total_Signals': signals,
                'Score': round(avg_prec - abs(avg_gap) * 0.5, 4),
            })

    # --- [3] 최종 비교 ---
    if not results:
        print("\n❌ 비교 가능한 결과가 없습니다.")
        return

    results.sort(key=lambda x: x['Score'], reverse=True)

    print("\n\n" + "=" * 85)
    print("🏆 [ 과적합 완화 실험 — 종합 순위 ]")
    print("=" * 85)
    print(f"  {'순위':>4} | {'설정':<14} | {'차원':>4} | "
          f"{'정밀도':>7} | {'과적합갭':>8} | {'신호수':>6} | {'종합점수':>8}")
    print(f"{'─' * 85}")

    for rank, r in enumerate(results, 1):
        medal = {1: '🥇', 2: '🥈', 3: '🥉'}.get(rank, '  ')
        gap_color = '🟢' if abs(r['Avg_Overfit_Gap']) < 0.2 else ('🟡' if abs(r['Avg_Overfit_Gap']) < 0.3 else '🔴')
        print(f"  {medal}{rank:>2} | {r['Config']:<14} | {r['Dims']:>3}D | "
              f"{r['Avg_Precision']:>6.3f} | "
              f"{r['Avg_Overfit_Gap']:>+7.3f} {gap_color} | "
              f"{r['Total_Signals']:>6} | {r['Score']:>7.4f}")

    print(f"{'─' * 85}")
    print(f"\n  📐 종합점수 = 정밀도 - |과적합갭| × 0.5")
    print(f"  💡 갭 < 0.2 🟢 / 0.2~0.3 🟡 / > 0.3 🔴")
    print(f"  💡 Baseline 대비 갭이 줄면서 정밀도 유지 → 채택 신호")

    winner = results[0]
    baseline = next((r for r in results if r['Config'] == 'Baseline'), None)
    if baseline and winner['Config'] != 'Baseline':
        gap_drop = baseline['Avg_Overfit_Gap'] - winner['Avg_Overfit_Gap']
        prec_change = winner['Avg_Precision'] - baseline['Avg_Precision']
        print(f"\n  🏆 추천: {winner['Config']}")
        print(f"     → Baseline 대비 갭 {gap_drop:+.3f}, 정밀도 {prec_change:+.3f}")
        print(f"     → predict.py _create_model + config.AI_WINDOW_SIZE 반영 검토")
    else:
        print(f"\n  🏆 추천: {winner['Config']} (현재 설정 유지)")
    print("=" * 85)


# ============================================================================
# [실행]
# ============================================================================


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
    mode = sys.argv[1] if len(sys.argv) > 1 else 'features'

    if mode == 'overfit':
        sys.stdout = Logger('results/overfit_experiment_results.txt')
        start = time.time()
        run_overfit_experiment()
        print(f"\n⏱️ 총 소요: {time.time() - start:.0f}초")
    else:
        sys.stdout = Logger('results/feature_experiment_results.txt')
        start = time.time()
        run_experiment()
        print(f"\n⏱️ 총 소요: {time.time() - start:.0f}초")