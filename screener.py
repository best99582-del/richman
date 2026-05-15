# ============================================================================
# 🦅 [퀀트 유니버스] 자동 종목 발굴기 (screener.py)
# ============================================================================
# 역할: 나스닥 전 종목을 빠르게 훑어 급등주 후보를 추출
# 설계: 많은 종목을 가볍게 걸러내는 게 목적 — 깊은 분석은 predict.py에서 수행
#
# Light 모드 이유:
#   ✅ Make_Indicators (26개 지표) — 종목당 ~0.5초
#   ✅ XGBoost 1회 학습 (70/30 split) — 종목당 ~5초
#   ❌ 5-Fold 교차검증 제거 (속도 확보 — predict.py에서 수행)
#
# 소요 시간: 1차 필터 ~2분 + AI 분석 ×5초/종목
# ============================================================================

import logging
import time

import numpy as np
import pandas as pd
import FinanceDataReader as fdr
from xgboost import XGBClassifier

import config
from indicators import Make_Indicators
from kelly import Get_Position_Size, Calculate_Reference_Kelly
from predict import Create_Windowed_Data, holdout_precision
from sector_cache import get_sectors
from data_loader import load_ohlcv
from market_cap_cache import get_screener_data

logger = logging.getLogger(__name__)

FEATURES        = config.AI_FEATURES
WINDOW_SIZE     = config.AI_WINDOW_SIZE
TARGET_PCT      = config.AI_TARGET_PCT
FORECAST_PERIOD = config.AI_FORECAST_PERIOD
AI_FILTER       = config.AI_FILTER

# _tech_summary에서 가능한 최대 매수 신호 개수 (sig_bar 길이 기준)
_MAX_SIGNALS = 7


# ============================================================================
# [유틸] XGBoost 모델 팩토리
# ============================================================================

def _make_model(weight: float) -> XGBClassifier:
    """screener 전용 XGBoost 모델 — predict.py와 동일한 하이퍼파라미터 (v9.1)"""
    return XGBClassifier(
        n_estimators=100, max_depth=2, learning_rate=0.01,
        subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.5, reg_lambda=2.0,
        scale_pos_weight=weight,
        random_state=42, eval_metric='logloss', n_jobs=-1,
    )


# ============================================================================
# [유틸] 기술지표 스냅샷 + 매수 신호 요약
# ============================================================================

def _tech_summary(df: pd.DataFrame) -> dict:
    """최근 지표 스냅샷 + 매수 신호 목록 반환 (최대 _MAX_SIGNALS개)"""
    row = df.iloc[-1]
    rsi             = float(row.get('RSI', 50))
    macd_cross      = int(row.get('MACD_Cross', 0))
    stoch_cross     = int(row.get('Stoch_Cross', 0))
    slow_k          = float(row.get('Slow_K', 50))
    slow_d          = float(row.get('Slow_D', 50))
    bandwidth       = float(row.get('BandWidth', 0))
    bb_width_ma     = float(row.get('BB_Width_MA', 0))
    bw_ratio        = (bandwidth / bb_width_ma) if bb_width_ma > 0 else 0.0
    bb_squeeze      = bool(row.get('BB_Squeeze', False))
    vol_ratio       = float(row.get('Volume_Ratio', 1.0))
    divergence      = int(row.get('Divergence', 0))
    price_above_ma20 = bool(row.get('Price_Above_MA20', False))
    disparity       = float(row.get('Disparity', 100))

    if rsi < 30:
        rsi_tag = "극단 과매도"
    elif rsi < 45:
        rsi_tag = "과매도(반등)"
    elif rsi < 55:
        rsi_tag = "중립"
    elif rsi < 70:
        rsi_tag = "상승모멘텀"
    else:
        rsi_tag = "과매수주의"

    buy_signals = []
    if rsi < 45:
        buy_signals.append("RSI과매도")
    if macd_cross == 1:
        buy_signals.append("MACD골든크로스")
    if stoch_cross == 1 and slow_k < 35:
        buy_signals.append("Stoch골든크로스")
    if bb_squeeze:
        buy_signals.append("BB스퀴즈탈출")
    if vol_ratio > 1.5:
        buy_signals.append(f"거래량×{vol_ratio:.1f}")
    if divergence == 1:
        buy_signals.append("강세다이버전스")
    if price_above_ma20:
        buy_signals.append("MA20위")

    return {
        'RSI':             round(rsi, 1),
        'RSI_Tag':         rsi_tag,
        'MACD_Cross':      macd_cross,
        'Stoch_K':         round(slow_k, 1),
        'Stoch_D':         round(slow_d, 1),
        'BandWidth':       round(bandwidth, 4),
        'BW_Ratio':        round(bw_ratio, 2),     # BandWidth / 20일 평균
        'Stoch_Cross':     stoch_cross,
        'BB_Squeeze':      bb_squeeze,
        'Vol_Ratio':       round(vol_ratio, 2),
        'Divergence':      divergence,
        'Disparity':       round(disparity, 1),
        'Price_Above_MA20': price_above_ma20,
        'Buy_Signals':     buy_signals,
        'Signal_Count':    len(buy_signals),
    }


def _get_market_condition() -> str:
    """QQQ MA20/MA60 위치로 나스닥 시장 현황 판단"""
    try:
        qqq = load_ohlcv('QQQ', start=(pd.Timestamp.now() - pd.Timedelta(days=200)).strftime('%Y-%m-%d'))
        qqq['MA20'] = qqq['Close'].rolling(20).mean()
        qqq['MA60'] = qqq['Close'].rolling(60).mean()
        last = qqq.iloc[-1]
        close, ma20, ma60 = last['Close'], last['MA20'], last['MA60']
        if close > ma60:
            if close > ma20:
                return f"📈 나스닥 상승 추세 (MA20/MA60 모두 위 — QQQ ${close:.1f})"
            else:
                return f"📊 나스닥 단기 조정 중 (MA60 위, MA20 아래 — QQQ ${close:.1f})"
        else:
            return f"⚠️ 나스닥 하락 추세 주의 (MA60 아래 — QQQ ${close:.1f})"
    except Exception:
        return "⚪ 시장 현황 확인 불가"


# ============================================================================
# [1단계] 종목 유니버스 추출 (NASDAQ + NYSE)
# ============================================================================

def _fetch_exchange_listing(exchange: str) -> pd.DataFrame:
    """FinanceDataReader로 거래소 종목 리스트 가져오기 (알파벳 심볼만)."""
    df = fdr.StockListing(exchange)
    # BRK.B 같은 도트 종목 제외 — yfinance 호환성
    df = df[~df['Symbol'].str.contains(r'[^A-Z]', regex=True)].copy()
    df['Exchange'] = exchange
    return df


def _exclude_industries(df: pd.DataFrame, keywords: list) -> pd.DataFrame:
    """Industry 컬럼이 제외 키워드 중 하나라도 포함하면 제거."""
    if 'Industry' not in df.columns or not keywords:
        return df
    pattern = '|'.join(keywords)
    mask = df['Industry'].astype(str).str.contains(pattern, na=False, regex=True)
    return df[~mask]


def get_universe(force_refresh_cache: bool = False) -> list:
    """
    NASDAQ + NYSE 통합 유니버스. 업종 제외 + 시총 캐시 필터 적용.

    Args:
        force_refresh_cache: True면 시총 캐시 강제 갱신 (약 60~70분 소요)

    Returns:
        list[str]: 시총 $1B~$20B 범위 + 업종 제외 통과한 티커 리스트
    """
    print(f"\n📡 [1단계] 종목 유니버스 수집 ({' + '.join(config.SCREENER_EXCHANGES)})")

    # 거래소별 종목 수집
    listings = []
    for ex in config.SCREENER_EXCHANGES:
        try:
            df = _fetch_exchange_listing(ex)
            listings.append(df)
            print(f"   {ex}: {len(df)}개")
        except Exception as e:
            logger.warning("거래소 %s 수집 실패: %s", ex, e)
            print(f"   ⚠️ {ex} 수집 실패: {e}")

    if not listings:
        print("⚠️ 모든 거래소 수집 실패 — config.TICKERS 폴백")
        return config.TICKERS

    df = pd.concat(listings, ignore_index=True).drop_duplicates(subset=['Symbol'])
    print(f"   통합/중복제거: {len(df)}개")

    # 업종 제외
    before = len(df)
    df = _exclude_industries(df, config.SCREENER_EXCLUDE_INDUSTRIES)
    print(f"   업종 제외({len(config.SCREENER_EXCLUDE_INDUSTRIES)}개 키워드): {before}개 → {len(df)}개")

    # screener API 데이터 조회 (시총 + 거래대금, 캐시 우선)
    tickers_all = df['Symbol'].tolist()
    data = get_screener_data(tickers_all, force_refresh=force_refresh_cache)
    print(f"   screener 데이터 확보: {len(data)}/{len(tickers_all)}개")

    # 시총 범위 필터
    in_mc = {
        t: info for t, info in data.items()
        if config.SCREENER_MIN_MARKET_CAP <= info['mc'] <= config.SCREENER_MAX_MARKET_CAP
    }
    print(f"   시총 ${config.SCREENER_MIN_MARKET_CAP/1e9:.0f}B~${config.SCREENER_MAX_MARKET_CAP/1e9:.0f}B: "
          f"{len(in_mc)}개")

    # 거래대금 사전 필터 (screener API 추정값 기반 — 정확한 20일은 filter_hot_stocks에서 재확인)
    in_range = {
        t: info for t, info in in_mc.items()
        if info['turnover'] >= config.SCREENER_MIN_TURNOVER
    }
    print(f"   거래대금 ≥ ${config.SCREENER_MIN_TURNOVER/1e6:.0f}M (3개월 평균): "
          f"{len(in_mc)}개 → {len(in_range)}개")

    # 시총 큰 순서 정렬
    sorted_tickers = sorted(in_range.keys(), key=lambda t: in_range[t]['mc'], reverse=True)
    print(f"✅ 유니버스 {len(sorted_tickers)}개 추출 완료.")
    # in_range도 함께 반환 (Cap_Class/Exchange 표시용 메타)
    return sorted_tickers, in_range


def classify_cap(market_cap_usd: float) -> str:
    """시가총액 기반 분류 (S&P/MSCI 통상 기준).

    Small: < $2B    | Mid: $2B~$10B    | Large: $10B+
    """
    if market_cap_usd < 2e9:
        return "Small"
    elif market_cap_usd < 10e9:
        return "Mid"
    else:
        return "Large"


# ============================================================================
# [2단계] 1차 퀀트 필터링 (가격 / 거래량 / 변동성)
# ============================================================================

def filter_hot_stocks(tickers: list) -> dict:
    """
    순수 OHLCV 기반 빠른 필터링 — AI 없음, Make_Indicators 호출 없음.

    ATR은 단순 True Range SMA로 근사 (속도 우선).
    정확한 ATR(Wilder's RMA)은 _quick_analyze 내부 Make_Indicators에서 사용.
    """
    print(f"\n🔍 [2단계] {len(tickers)}개 종목 1차 필터링")
    hot_candidates = {}

    for i, ticker in enumerate(tickers):
        try:
            print(f"  스캔 ({i + 1}/{len(tickers)}): {ticker:<6}", end='\r')
            df = load_ohlcv(ticker, start=config.START_DATE)
            time.sleep(0.1)

            if len(df) < config.SCREENER_MIN_DATA_DAYS:
                continue

            current_price = df['Close'].iloc[-1]
            avg_turnover  = (df['Volume'] * df['Close']).tail(20).mean()

            if current_price < config.SCREENER_MIN_PRICE:
                continue
            if avg_turnover < config.SCREENER_MIN_TURNOVER:
                continue

            prev_close = df['Close'].shift(1)
            tr = np.maximum(
                df['High'] - df['Low'],
                np.maximum(
                    np.abs(df['High'] - prev_close).fillna(0),
                    np.abs(df['Low']  - prev_close).fillna(0),
                )
            )
            volatility_pct = (tr.tail(config.ATR_PERIOD).mean() / current_price) * 100

            if config.SCREENER_MIN_VOLATILITY <= volatility_pct <= config.SCREENER_MAX_VOLATILITY:
                hot_candidates[ticker] = df

        except Exception as e:
            logger.debug("스킵 (%s): %s", ticker, e)

    print(f"\n✅ 1차 필터 완료: {len(hot_candidates)}개 후보\n")
    return hot_candidates


# ============================================================================
# [내부] 가벼운 AI 분석 (종목 1개, ~5초)
# ============================================================================

def _quick_analyze(ticker: str, df_raw: pd.DataFrame, meta: dict | None = None) -> dict | None:
    """
    screener 전용 Light AI 분석.

    [1] Make_Indicators — 26개 지표 산출
    [2] XGBoost 70/30 split — 정밀도 사전 검증
    [3] 전체 데이터 재학습 — 현재 급등 확률 예측
    [4] Kelly 추천 — 투입 금액 / 손절가
    [5] 거래량 비율 + 기술지표 스냅샷

    정밀도 < SCREENER_MIN_PRECISION이면 None 반환 (predict.py 진입 차단).
    """
    try:
        # --- [1] 지표 산출 ---
        df = Make_Indicators(df_raw.copy())
        df = df.dropna()
        if len(df) < 300:
            return None

        current_price = df['Close'].iloc[-1]

        # --- [2] Light 정밀도 (70/30 holdout) — 공용 헬퍼 호출 ---
        light_precision, light_signals = holdout_precision(df)
        if light_precision < config.SCREENER_MIN_PRECISION:
            return None

        # --- [3] 전체 데이터 재학습 + 현재 확률 예측 ---
        X_all, y_all = Create_Windowed_Data(df, FEATURES, WINDOW_SIZE, TARGET_PCT, FORECAST_PERIOD)
        if len(set(y_all)) < 2 or len(y_all) < 100:
            return None

        n_pos_all  = np.sum(y_all == 1)
        weight_all = float(np.sum(y_all == 0)) / n_pos_all if n_pos_all > 0 else 1.0

        model_full = _make_model(weight_all)
        model_full.fit(X_all, y_all)

        latest = df[FEATURES].iloc[-WINDOW_SIZE:].values.flatten().reshape(1, -1)
        prob   = model_full.predict_proba(latest)[0][1]

        # --- [4] Kelly 추천 ---
        atr_raw = df['ATR'].iloc[-1] if 'ATR' in df.columns else 0
        current_atr = float(atr_raw) if pd.notna(atr_raw) else 0.0
        _, _, kelly_weight = Get_Position_Size(
            config.CAPITAL, current_price, current_atr,
            model_precision=light_precision, ai_prob=prob,
        )
        ref_kelly_weight = round(Calculate_Reference_Kelly(light_precision), 4)
        stop_distance = current_atr * config.ATR_STOP_MULTIPLIER
        stop_price    = round(current_price - stop_distance, 2)
        stop_pct      = round((stop_distance / current_price) * 100, 1) if current_price > 0 else 0

        # --- [5] 거래량 비율 + 기술지표 스냅샷 ---
        vol_ratio = 1.0
        if 'Volume' in df_raw.columns and len(df_raw) >= 20:
            avg_vol   = df_raw['Volume'].tail(20).mean()
            today_vol = df_raw['Volume'].iloc[-1]
            vol_ratio = round(today_vol / avg_vol, 2) if avg_vol > 0 else 1.0

        return {
            'Ticker':        ticker,
            'Prob':          prob,
            'Light_Precision': round(light_precision, 3),     # 70/30 holdout 정밀도 (정식)
            'Hist_Precision': round(light_precision, 3),       # 호환 별칭
            'Eval_Method':   'holdout_70_30',
            'Light_Signals': light_signals,
            'Current_Price': current_price,
            'ATR':           round(current_atr, 4),
            'Stop_Price':    stop_price,
            'Stop_Pct':      stop_pct,
            'Kelly_Weight':     round(kelly_weight, 4),
            'Kelly_Weight_Ref': ref_kelly_weight,
            'Vol_Ratio':        vol_ratio,
            'Tech':          _tech_summary(df),
            # 분류 정보 (시총 규모/거래소/섹터)
            'Market_Cap':     (meta or {}).get('mc', 0),
            'Cap_Class':      classify_cap((meta or {}).get('mc', 0)),
            'Exchange':       (meta or {}).get('exchange', 'UNKNOWN'),
            'Sector':         (meta or {}).get('sector', 'Unknown'),
        }

    except Exception as e:
        logger.debug("Light 분석 실패 (%s): %s", ticker, e)
        return None


# ============================================================================
# [3단계] AI 스캔 + 대시보드
# ============================================================================

def ai_scanner(candidates_data: dict, screener_meta: dict | None = None) -> list:
    """
    1차 필터 통과 종목에 Light AI 분석을 수행하고 대시보드를 출력합니다.

    Args:
        candidates_data: filter_hot_stocks() 반환 {티커: DataFrame}
        screener_meta: get_universe() 반환 메타 {티커: {mc, exchange, turnover, ...}}.
            None이면 분류 정보 없이 표시.

    Returns:
        list: 분석 결과 리스트 (AI 확률 내림차순)
    """
    total      = len(candidates_data)
    start_time = time.time()
    picks      = []
    screener_meta = screener_meta or {}

    print(f"\n🌐 시장 현황: {_get_market_condition()}")
    print(f"🎯 [3단계] Light AI 스캔 ({total}개 종목, 종목당 ~5초)")
    print(f"   모드: 1-Fold XGBoost + 기술지표 스냅샷")

    # 섹터 정보 일괄 조회 (캐시 우선)
    sectors = get_sectors(list(candidates_data.keys()))
    print()

    for i, (ticker, df_raw) in enumerate(candidates_data.items()):
        elapsed   = time.time() - start_time
        avg       = elapsed / (i + 1) if i > 0 else 5
        remaining = avg * (total - i - 1)
        print(f"  ⚡ ({i + 1}/{total}) {ticker}... [잔여 ~{remaining:.0f}초]", end='\r')

        # 메타 합치기
        meta = dict(screener_meta.get(ticker, {}))
        meta['sector'] = sectors.get(ticker, 'Unknown')
        result = _quick_analyze(ticker, df_raw, meta=meta)
        if result:
            picks.append(result)

    picks.sort(key=lambda x: x['Prob'], reverse=True)
    _print_dashboard(picks, total, time.time() - start_time)
    return picks


# ============================================================================
# [내부] 대시보드 출력
# ============================================================================

def _print_dashboard(picks: list, total_scanned: int, elapsed: float):
    if not picks:
        print("\n\n⚠️ AI 기준을 통과한 종목이 없습니다.\n")
        return

    print("\n\n" + "=" * 95)
    print(" " * 15 + "🦅 [ Screener 결과 — Light AI 급등주 후보 ]")
    print(" " * 15 + "💡 정밀 분석은: python predict.py TICKER ...")
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

        tech      = p.get('Tech', {})
        signals   = tech.get('Buy_Signals', [])
        sig_count = tech.get('Signal_Count', 0)
        sig_bar   = "●" * sig_count + "○" * (_MAX_SIGNALS - sig_count)

        # 분류 라벨 (시총 + 거래소 + 섹터)
        mc_b = p.get('Market_Cap', 0) / 1e9
        cap_class = p.get('Cap_Class', '-')
        exchange = p.get('Exchange', '-')
        sector = p.get('Sector', '-')
        class_tag = f"{exchange} · {cap_class}-cap (${mc_b:.1f}B) · {sector}"

        print(f"\n{'─' * 95}")
        print(f"  #{rank}  {p['Ticker']:<6}  |  {verdict}  |  현재가: ${p['Current_Price']:,.2f}")
        print(f"  🏷️ {class_tag}")
        print(f"{'─' * 95}")
        print(f"  📡 AI확률: {p['Prob']:.1%}  |  Light정밀도(70/30): {p['Light_Precision']:.1%}  |  "
              f"거래량: ×{p['Vol_Ratio']:.1f} {vol_status}")
        # BandWidth ratio 마커 (1.5+ 시 스퀴즈 탈출 시그널)
        bw_ratio = tech.get('BW_Ratio', 0)
        bw_marker = " 🔥" if bw_ratio >= config.BB_SQUEEZE_RATIO else ""
        bw_str = f"{tech.get('BandWidth', '-')} (×{bw_ratio:.2f} of 20일평균{bw_marker})"
        print(f"  📊 RSI: {tech.get('RSI', '-')} ({tech.get('RSI_Tag', '')})  |  "
              f"Disparity: {tech.get('Disparity', '-')}%  |  "
              f"BandWidth: {bw_str}")
        print(f"  📊 Stoch_K: {tech.get('Stoch_K', '-')}  |  "
              f"Stoch_D: {tech.get('Stoch_D', '-')}")
        if signals:
            print(f"  🔔 기술신호 [{sig_bar}] {' · '.join(signals)}")
        else:
            print(f"  🔔 기술신호 [{sig_bar}] 없음")
        print(f"  🛡️ 손절가: ${p['Stop_Price']:,.2f} (−{p['Stop_Pct']:.1f}%)")

        if p['Kelly_Weight'] > 0:
            print(f"  💰 켈리 비중: {p['Kelly_Weight']:.1%}")
        else:
            print(f"  💰 켈리: 매수 보류 (참고비중 {p['Kelly_Weight_Ref']:.1%})")

    print(f"\n{'=' * 95}")
    print(f"  📊 {total_scanned}개 스캔 → {len(picks)}개 AI 통과 | ⏱️ {elapsed:.0f}초")
    print(f"  ⚠️ Light 모드 (70/30 split) — 정밀도 {config.SCREENER_MIN_PRECISION:.0%} 이상만 표시")
    print(f"{'=' * 95}\n")

    strong_buys = [p for p in picks if p['Prob'] >= 0.65]
    if strong_buys:
        tickers_str = ' '.join(p['Ticker'] for p in strong_buys)
        print(f"  🔥 강력매수 종목 정밀 분석 명령어:")
        print(f"     python predict.py {tickers_str}\n")


# ============================================================================
# [실행]
# ============================================================================

if __name__ == "__main__":
    start_time = time.time()
    universe, screener_meta = get_universe()
    candidates = filter_hot_stocks(universe)

    if candidates:
        results = ai_scanner(candidates, screener_meta=screener_meta)
    else:
        print("⚠️ 조건에 맞는 종목이 없습니다.")

    print(f"⏱️ 총 소요: {time.time() - start_time:.1f}초")
