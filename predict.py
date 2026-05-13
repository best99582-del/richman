# ============================================================================
# 🧠 [퀀트 유니버스] AI 급등 예측 엔진 (predict.py)
# ============================================================================
# 역할: 사용자가 지정한 종목에 대해 최대한 많은 정보를 동원하여 정밀 분석
#
# 사용법:
#   python predict.py IONQ PLTR SOFI    → 지정 종목 정밀 분석
#   python predict.py                   → config.TICKERS 분석
#
# 분석 항목:
#   ✅ Make_Indicators (26개 기술지표)
#   ✅ XGBoost 5-Fold 교차검증 (정밀도 측정)
#   ✅ 기술지표 스냅샷 + Kelly + 거래량 분석
#
# screener가 빠르게 후보를 추리고, 이 파일이 깊게 파는 구조
# ============================================================================

import logging
import sys
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier

import config
from ta import Make_Indicators
from kelly import Get_Position_Size, Calculate_Reference_Kelly
from data_loader import load_ohlcv

logger = logging.getLogger(__name__)

# --- config 매핑 ---
FEATURES = config.AI_FEATURES
WINDOW_SIZE = config.AI_WINDOW_SIZE
TARGET_PCT = config.AI_TARGET_PCT
FORECAST_PERIOD = config.AI_FORECAST_PERIOD
AI_FILTER = config.AI_FILTER


# ============================================================================
# [유틸리티] 공통 함수들
# ============================================================================

def _create_model(scale_pos_weight=1.0):
    """XGBoost 표준 모델 팩토리

    v9.1 과적합 완화 실험 결과:
      depth 3→2, reg_alpha 0→0.5, reg_lambda 1→2 채택.
      Baseline 대비 과적합갭 −0.135, 정밀도 +0.020 동시 개선.
    """
    return XGBClassifier(
        n_estimators=100, max_depth=2, learning_rate=0.01,
        subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.5, reg_lambda=2.0,
        scale_pos_weight=scale_pos_weight,
        random_state=42, eval_metric='logloss', n_jobs=-1
    )

def _calc_pos_weight(y):
    """클래스 불균형 보정 비율"""
    n_pos = np.sum(y == 1)
    return float(np.sum(y == 0)) / n_pos if n_pos > 0 else 1.0

def _laplace_precision(preds, y_true):
    """라플라스 스무딩 정밀도"""
    total = np.sum(preds)
    if total == 0:
        return 0.5
    hits = np.sum((preds == 1) & (y_true == 1))
    return (hits + 1) / (total + 2)

def Create_Windowed_Data(data, features, window, target_pct, forecast_period):
    """
    XGBoost용 슬라이딩 윈도우 학습 데이터 생성.

    타겟(y=1): entry 이후 forecast_period일 중 최대 종가가 target_pct% 이상 상승.
    High 기준 대신 Close 기준 사용 — 실제 체결 가능한 종가로 평가해야 기저 양성비가
    현실적(30~50%)이 되고, AI가 진짜 패턴을 학습할 여지가 생김.
    """
    X, y = [], []
    values = data[features].values
    close_prices = data['Close'].values

    for i in range(window, len(data) - forecast_period):
        X.append(values[i - window: i].flatten())
        # 진입가: 오늘 시가에 매수 가정 (어제 종가 대신 오늘 종가를 entry로)
        # 단, 오늘 시가 데이터가 없을 수 있어 Close[i]를 실질 진입가로 근사
        entry = close_prices[i]
        future_closes = close_prices[i + 1: i + 1 + forecast_period]
        best_close = np.max(future_closes) if len(future_closes) > 0 else entry
        y.append(int((best_close - entry) / entry * 100 >= target_pct))

    return np.array(X), np.array(y)


# ============================================================================
# [핵심] 종목별 풀 정밀 분석
# ============================================================================

def Analyze_Full(ticker: str, df_input: pd.DataFrame = None) -> dict:
    """
    단일 종목에 대해 모든 분석을 수행합니다.
    
    수행 항목:
      [1] 데이터 로드
      [2] Make_Indicators — 26개 지표 산출
      [3] 5-Fold 교차검증 — 과거 정밀도(Hist_Precision) 측정
      [4] 최종 모델 학습 — 오늘의 급등 확률 예측
      [5] Kelly 추천 — 매수 수량/투입 금액/손절가
      [6] 거래량 분석
      [7] 지표 스냅샷
    
    Args:
        ticker: 종목 티커
        df_input: 이미 다운로드된 OHLCV (없으면 자동 다운로드)
    
    Returns:
        dict: 전체 분석 결과 또는 None
    """
    try:
        # --- [1] 데이터 로드 ---
        if df_input is None:
            df_raw = load_ohlcv(ticker, start=config.START_DATE)
        else:
            df_raw = df_input.copy()

        # --- [2] 지표 산출 (12개 피처 포함) ---
        df = Make_Indicators(df_raw.copy())
        df = df.dropna()

        if len(df) < 300:
            print(f"  ⚠️ {ticker}: 데이터 부족 ({len(df)}일)")
            return None

        # --- [3] 5-Fold 교차검증 (풀 — 정밀도 측정) ---
        tscv = TimeSeriesSplit(n_splits=5)
        precision_box = []
        signal_counts = 0

        df_indices = np.arange(len(df))
        for train_idx, test_idx in tscv.split(df_indices):
            # 🔧 train 마지막 FORECAST_PERIOD일 제거 (gap)
            if len(train_idx) <= FORECAST_PERIOD + WINDOW_SIZE:
                continue
            safe_train_idx = train_idx[:-FORECAST_PERIOD]

            X_train, y_train = Create_Windowed_Data(
                df.iloc[safe_train_idx], FEATURES, WINDOW_SIZE, TARGET_PCT, FORECAST_PERIOD
            )
            X_test, y_test = Create_Windowed_Data(
                df.iloc[test_idx], FEATURES, WINDOW_SIZE, TARGET_PCT, FORECAST_PERIOD
            )

            if len(set(y_train)) < 2 or len(y_train) == 0 or len(y_test) == 0:
                continue

            model = _create_model(_calc_pos_weight(y_train))
            model.fit(X_train, y_train)
            probs = model.predict_proba(X_test)[:, 1]
            preds = (probs >= AI_FILTER).astype(int)

            if np.sum(preds) > 0:
                precision_box.append(_laplace_precision(preds, y_test))
                signal_counts += int(np.sum(preds))

        hist_precision = round(np.mean(precision_box), 3) if precision_box else 0.5

        # --- [4] 최종 모델 + 오늘 예측 ---
        X_all, y_all = Create_Windowed_Data(
            df, FEATURES, WINDOW_SIZE, TARGET_PCT, FORECAST_PERIOD
        )
        if len(set(y_all)) < 2 or len(y_all) < 100:
            return None

        final_model = _create_model(_calc_pos_weight(y_all))
        final_model.fit(X_all, y_all)
        latest = df[FEATURES].iloc[-WINDOW_SIZE:].values.flatten().reshape(1, -1)
        final_prob = final_model.predict_proba(latest)[0][1]

        # --- [5] Kelly 추천 ---
        current_price = df['Close'].iloc[-1]
        atr_raw = df['ATR'].iloc[-1] if 'ATR' in df.columns else 0
        current_atr = float(atr_raw) if pd.notna(atr_raw) else 0.0

        _, _, kelly_weight = Get_Position_Size(
            config.CAPITAL, current_price, current_atr,
            hist_precision, final_prob
        )
        # 관망 종목용 참고비중 (AI_FILTER 무관, 정밀도 단독 기준)
        ref_kelly_weight = round(Calculate_Reference_Kelly(hist_precision), 4)

        # --- [6] 손절 정보 ---
        stop_distance = current_atr * config.ATR_STOP_MULTIPLIER
        stop_price = round(current_price - stop_distance, 2)
        stop_pct = round((stop_distance / current_price) * 100, 1) if current_price > 0 else 0

        # --- [6] 거래량 비율 ---
        vol_ratio = 1.0
        if 'Volume' in df_raw.columns and len(df_raw) >= 20:
            avg_vol = df_raw['Volume'].tail(20).mean()
            today_vol = df_raw['Volume'].iloc[-1]
            vol_ratio = round(today_vol / avg_vol, 2) if avg_vol > 0 else 1.0

        # --- [7] 지표 스냅샷 ---
        snapshot = {
            'RSI': round(df['RSI'].iloc[-1], 1),
            'MACD': round(df['MACD'].iloc[-1], 4),
            'MACD_Cross': int(df['MACD_Cross'].iloc[-1]),
            'Stoch_K': round(df['Slow_K'].iloc[-1], 1),
            'Stoch_Cross': int(df['Stoch_Cross'].iloc[-1]),
            'Divergence': int(df['Divergence'].iloc[-1]),
            'BB_Squeeze': bool(df['BB_Squeeze'].iloc[-1]),
            'Price_Above_MA20': bool(df['Price_Above_MA20'].iloc[-1]),
            'Disparity': round(df['Disparity'].iloc[-1], 2),
        }

        return {
            'Ticker': ticker,
            'Prob': final_prob,
            'Hist_Precision': hist_precision,
            'Signals': signal_counts,
            'Current_Price': current_price,
            'Last_Bar_Date': df.index[-1].strftime('%Y-%m-%d') if hasattr(df.index[-1], 'strftime') else str(df.index[-1]),
            'ATR': round(current_atr, 4),
            'Stop_Price': stop_price,
            'Stop_Pct': stop_pct,
            'Kelly_Weight': round(kelly_weight, 4),
            'Kelly_Weight_Ref': ref_kelly_weight,
            'Vol_Ratio': vol_ratio,
            'Snapshot': snapshot,
            'df': df,
        }

    except Exception as e:
        logger.warning("⚠️ %s 분석 실패: %s", ticker, e)
        return None


# ============================================================================
# [핵심] 복수 종목 정밀 분석 + 대시보드
# ============================================================================

def Deep_Scan(tickers: list) -> list:
    """
    지정된 종목들에 대해 풀 정밀 분석을 수행하고 대시보드를 출력합니다.
    
    Args:
        tickers: 분석할 종목 리스트 (예: ['IONQ', 'PLTR'])
    
    Returns:
        list: 정밀 분석 결과 리스트 (확률 내림차순)
    """
    print(f"\n🧠 [ Deep Scan — 정밀 분석 모드 ]")
    print(f"   대상: {tickers}")
    print(f"   5-Fold 교차검증 + Kelly + 기술지표 스냅샷")
    print(f"   피처 {len(FEATURES)}개: {FEATURES}\n")

    results = []
    start_time = time.time()

    for i, ticker in enumerate(tickers):
        elapsed = time.time() - start_time
        avg = elapsed / (i + 1) if i > 0 else 30
        remaining = avg * (len(tickers) - i - 1)
        print(f"  🧠 ({i + 1}/{len(tickers)}) {ticker} 정밀 분석 중... "
              f"[잔여 ~{remaining:.0f}초]")

        result = Analyze_Full(ticker)
        if result:
            results.append(result)

    results.sort(key=lambda x: x['Prob'], reverse=True)

    elapsed_total = time.time() - start_time
    _print_deep_dashboard(results, elapsed_total)

    return results


# ============================================================================
# [내부] 정밀 분석 대시보드 출력
# ============================================================================

def _print_deep_dashboard(picks: list, elapsed: float):
    """predict.py 정밀 분석 전용 상세 대시보드"""
    if not picks:
        print("\n⚠️ 분석 가능한 종목이 없습니다.\n")
        return

    print("\n" + "=" * 95)
    print(" " * 15 + "🧠 [ Deep Scan 정밀 분석 결과 ]")
    print(" " * 15 + "5-Fold 검증 + 기술지표 스냅샷")
    print("=" * 95)

    for rank, p in enumerate(picks, 1):
        if p['Prob'] >= 0.65:
            verdict = "🔥 강력매수"
        elif p['Prob'] >= AI_FILTER:
            verdict = "✅ 매수사정권"
        else:
            verdict = "❌ 관망"

        if p['Vol_Ratio'] >= 3.0:
            vol_status = "🔥🔥 폭발"
        elif p['Vol_Ratio'] >= 2.0:
            vol_status = "🔥 급증"
        elif p['Vol_Ratio'] >= 1.5:
            vol_status = "📈 증가"
        else:
            vol_status = "— 보통"

        s = p['Snapshot']

        print(f"\n{'─' * 95}")
        print(f"  #{rank}  {p['Ticker']:<6}  |  {verdict}")
        print(f"{'─' * 95}")

        # [상단] AI + 신뢰도
        print(f"  📡 AI확률: {p['Prob']:.1%}  |  "
              f"모델정밀도: {p['Hist_Precision']:.1%}  |  "
              f"과거신호: {p['Signals']}회")

        # [중단] 가격 + 리스크
        print(f"  현재가: ${p['Current_Price']:,.2f}  |  "
              f"ATR: ${p['ATR']:,.2f}  |  "
              f"거래량: ×{p['Vol_Ratio']:.1f} {vol_status}")
        print(f"  🛡️ 손절가: ${p['Stop_Price']:,.2f} (−{p['Stop_Pct']:.1f}%)")

        # [하단] 자금 관리
        if p['Kelly_Weight'] > 0:
            print(f"  💰 켈리 비중: {p['Kelly_Weight']:.1%}")
        else:
            print(f"  💰 켈리: 관망 (참고비중 {p['Kelly_Weight_Ref']:.1%})")

        # [상세] 지표 스냅샷
        print(f"  ┌─ 📊 지표 상세 ─────────────────────────────────────────")
        print(f"  │ RSI: {s['RSI']:>5.1f}  |  "
              f"Stoch_K: {s['Stoch_K']:>5.1f}  |  "
              f"이격도: {s['Disparity']:>6.2f}%  |  "
              f"MA20 위: {'✅' if s['Price_Above_MA20'] else '❌'}")

        macd_cross_str = {1: '🔼 골든', -1: '🔽 데드', 0: '— 없음'}.get(s['MACD_Cross'], '—')
        stoch_cross_str = {1: '🔼 골든', -1: '🔽 데드', 0: '— 없음'}.get(s['Stoch_Cross'], '—')
        div_str = {1: '💚 강세', -1: '💔 약세', 0: '— 없음'}.get(s['Divergence'], '—')

        print(f"  │ MACD교차: {macd_cross_str}  |  "
              f"Stoch교차: {stoch_cross_str}  |  "
              f"다이버전스: {div_str}")
        print(f"  │ BB스퀴즈: {'🔥 탈출!' if s['BB_Squeeze'] else '— 대기'}  |  "
              f"MACD: {s['MACD']:+.4f}")
        print(f"  └───────────────────────────────────────────────────────")

    print(f"\n{'=' * 95}")
    print(f"  ⏱️ 소요: {elapsed:.0f}초 | 피처: {len(FEATURES)}개")
    print(f"{'=' * 95}\n")


# ============================================================================
# Walk-Forward AI 신호 부착 (backtest.py 연동)
# ============================================================================

def Add_AI_Signals(df, train_window=500):
    """backtest.py용 Walk-Forward AI_Prob 부착"""
    df = df.copy()
    df['AI_Prob'] = 0.5
    df['Model_Precision'] = 0.5

    X_all, y_all = Create_Windowed_Data(
        df, FEATURES, WINDOW_SIZE, TARGET_PCT, FORECAST_PERIOD
    )

    if len(X_all) < train_window + FORECAST_PERIOD:
        return df

    update_step = 20
    start_idx = WINDOW_SIZE

    holdout_size = max(20, train_window // 5)  # 학습 데이터의 20%를 정밀도 측정용

    for i in range(train_window, len(X_all), update_step):
        train_end = i - FORECAST_PERIOD
        if train_end <= holdout_size:
            continue

        # 학습 구간을 fit 부분과 holdout 부분으로 분리 (정밀도 부풀림 방지)
        # holdout만큼 fit 시작 시점을 앞으로 당겨서 train_window 학습량 보존
        fit_end = train_end - holdout_size
        fit_start = max(0, fit_end - train_window)
        X_fit, y_fit = X_all[fit_start:fit_end], y_all[fit_start:fit_end]
        X_holdout, y_holdout = X_all[fit_end:train_end], y_all[fit_end:train_end]

        if len(set(y_fit)) < 2:
            continue

        model = _create_model(_calc_pos_weight(y_fit))
        model.fit(X_fit, y_fit)

        # 학습에 안 쓴 holdout으로 정밀도 측정 → backtest의 Kelly에 더 정직한 값 전달
        holdout_probs = model.predict_proba(X_holdout)[:, 1]
        holdout_preds = (holdout_probs >= AI_FILTER).astype(int)
        precision = _laplace_precision(holdout_preds, y_holdout)

        pred_end = min(i + update_step, len(X_all))
        X_test = X_all[i: pred_end]

        if len(X_test) > 0:
            probs = model.predict_proba(X_test)[:, 1]
            t_start = start_idx + i
            t_end = start_idx + pred_end
            df.iloc[t_start:t_end, df.columns.get_loc('AI_Prob')] = probs
            df.iloc[t_start:t_end, df.columns.get_loc('Model_Precision')] = precision

    return df


# ============================================================================
# [테스트] 단독 실행
# ============================================================================

if __name__ == "__main__":
    # 커맨드라인 인자로 종목 지정 가능
    # python predict.py IONQ PLTR SOFI
    # python predict.py  (→ config.TICKERS 사용)

    if len(sys.argv) > 1:
        target_tickers = [t.upper() for t in sys.argv[1:]]
    else:
        target_tickers = config.TICKERS

    results = Deep_Scan(target_tickers)

    # trade_journal 자동 기록 (import 가능할 때만)
    if results:
        try:
            from trade_journal import log_ai_recommendations
            log_ai_recommendations(results)
            print("📝 trade_journal에 자동 기록 완료")
        except ImportError:
            pass