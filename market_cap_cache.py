# ============================================================================
# 💰 [퀀트 유니버스] 시가총액 캐싱 시스템 (market_cap_cache.py)
# ============================================================================
# 역할: yfinance fast_info로 종목 시가총액을 일괄 조회하고 JSON 캐싱
# 갱신: config.MARKET_CAP_CACHE_DAYS(7일)마다 자동 갱신
#
# fdr.StockListing은 MarketCap 컬럼을 제공하지 않아 직접 조회 필요.
# yfinance .info는 느리고(.5~1초/종목), fast_info는 약 0.3~0.6초/종목.
#
# 사용법:
#   from market_cap_cache import get_market_caps
#   caps = get_market_caps(['IONQ', 'PLTR', 'AAPL'])
#   # {'IONQ': 20850000000.0, 'PLTR': 326030000000.0, 'AAPL': 4329830000000.0}
# ============================================================================

import json
import os
import time
from datetime import datetime, timedelta

import yfinance as yf
from yfinance import EquityQuery

import config


# ============================================================================
# [내부 헬퍼] 캐시 파일 입출력
# ============================================================================

def _load_cache(path: str) -> dict:
    """JSON 캐시 로드. 파일 없거나 파싱 실패 시 빈 dict."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(path: str, data: dict) -> None:
    """캐시를 JSON으로 저장 (updated_at 자동 갱신)."""
    payload = {
        'updated_at': datetime.now().isoformat(timespec='seconds'),
        'data': data,
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _is_fresh(cache: dict, days: int) -> bool:
    """캐시의 updated_at이 days일 이내인지."""
    ts = cache.get('updated_at')
    if not ts:
        return False
    try:
        updated = datetime.fromisoformat(ts)
    except ValueError:
        return False
    return (datetime.now() - updated) < timedelta(days=days)


# ============================================================================
# [내부 헬퍼] yfinance 일괄 조회
# ============================================================================

def _fetch_one(ticker: str) -> float:
    """단일 종목 시총 조회. 실패 시 0.0 반환."""
    try:
        info = yf.Ticker(ticker).fast_info
        mc = info.get('marketCap', None)
        return float(mc) if mc else 0.0
    except Exception:
        return 0.0


def _fetch_market_caps_per_ticker(tickers: list) -> dict:
    """
    [FALLBACK] 종목별 fast_info 조회 (구버전, 약 0.6초/종목).
    screener API 실패 시 폴백용. 200~300개 이하 부분 갱신에만 사용 권장.
    """
    total = len(tickers)
    print(f"📡 yfinance 시총 조회 시작 ({total}개, 종목별 모드)")
    start = time.time()

    result = {}
    failed = 0
    for i, ticker in enumerate(tickers, 1):
        mc = _fetch_one(ticker)
        if mc > 0:
            result[ticker] = mc
        else:
            failed += 1

        if i % 100 == 0 or i == total:
            elapsed = time.time() - start
            rate = i / elapsed if elapsed > 0 else 0
            remaining = (total - i) / rate if rate > 0 else 0
            print(f"  진행 {i}/{total} ({i/total:.0%}) | "
                  f"성공 {len(result)} 실패 {failed} | "
                  f"경과 {elapsed:.0f}s 남은시간 {remaining:.0f}s")

    elapsed = time.time() - start
    print(f"✅ 완료: 성공 {len(result)}개 실패 {failed}개 (소요 {elapsed:.0f}s)")
    return result


def _fetch_market_caps_via_screener() -> dict:
    """
    [기본] yfinance screener API로 NASDAQ+NYSE 시총 일괄 조회 (약 20초).
    사전 필터: 거래소(NASDAQ, NYSE) + 가격 ≥ config.SCREENER_MIN_PRICE.
    페이지네이션(250개/회)으로 전체 결과 수집.

    Returns:
        {ticker: market_cap_usd}. screener API 실패 시 빈 dict.
    """
    print(f"📡 yfinance screener API 시총 일괄 조회 시작")
    start = time.time()

    # 거래소 코드:
    #   NMS = NASDAQ Global Select Market (대형)
    #   NGM = NASDAQ Global Market (중형)
    #   NCM = NASDAQ Capital Market (소형) — RKLB 같은 종목이 여기
    #   NYQ = NYSE
    query = EquityQuery('and', [
        EquityQuery('is-in', ['exchange', 'NMS', 'NGM', 'NCM', 'NYQ']),
        EquityQuery('gte', ['intradayprice', config.SCREENER_MIN_PRICE]),
    ])

    result = {}
    page = 0
    while True:
        try:
            res = yf.screen(query, size=250, offset=page * 250)
        except Exception as e:
            print(f"⚠️ screener 페이지 {page} 실패: {e}")
            break

        quotes = res.get('quotes', [])
        if not quotes:
            break

        for q in quotes:
            symbol = q.get('symbol')
            mc = q.get('marketCap')
            if symbol and mc:
                result[symbol] = float(mc)

        elapsed = time.time() - start
        total_hint = res.get('total', '?')
        print(f"  페이지 {page + 1}: {len(quotes)}개 누적 {len(result)}개 "
              f"(전체 {total_hint}) | 경과 {elapsed:.0f}s")

        page += 1
        if len(quotes) < 250:
            break

    elapsed = time.time() - start
    print(f"✅ 완료: {len(result)}개 시총 확보 (소요 {elapsed:.0f}s)")
    return result


# ============================================================================
# [핵심] 시총 조회 — 캐시 우선
# ============================================================================

def get_market_caps(tickers: list, force_refresh: bool = False) -> dict:
    """
    종목 리스트의 시가총액을 반환합니다 (USD).

    - 캐시가 config.MARKET_CAP_CACHE_DAYS일 이내면 캐시에서 반환
    - 캐시 만료 또는 force_refresh=True면 yfinance 재조회 후 캐시 갱신
    - 조회 실패 종목은 결과 dict에서 제외 (KeyError로 호출자가 인지)

    Args:
        tickers: 조회할 티커 리스트
        force_refresh: True면 캐시 무시하고 재조회

    Returns:
        dict: {ticker: market_cap_usd}
    """
    path = config.MARKET_CAP_CACHE_PATH
    cache = _load_cache(path)
    cached_data = cache.get('data', {})

    if not force_refresh and _is_fresh(cache, config.MARKET_CAP_CACHE_DAYS):
        # 캐시가 신선하면 요청 티커 중 캐시에 있는 것만 반환
        # 누락된 종목은 screener API의 사전 필터(가격/거래소)에 안 잡힌 종목일
        # 가능성이 높으므로 부분 보충 없이 그대로 둠 (불필요한 API 호출 회피)
        hits = {t: cached_data[t] for t in tickers if t in cached_data}
        print(f"💾 캐시 사용 ({cache.get('updated_at', '?')}, "
              f"요청 {len(tickers)} 적중 {len(hits)})")
        return hits

    # 캐시 만료 또는 force_refresh — screener API로 전체 재조회
    fresh = _fetch_market_caps_via_screener()
    if not fresh:
        # screener 실패 — 폴백: 종목별 조회 (느림, 약 60분)
        print("⚠️ screener API 실패 — 종목별 조회로 폴백")
        fresh = _fetch_market_caps_per_ticker(tickers)

    _save_cache(path, fresh)
    print(f"💾 캐시 저장: {path}")
    # 요청 티커 중 fresh에 있는 것만 반환
    return {t: fresh[t] for t in tickers if t in fresh}


# ============================================================================
# [단독 실행] 수동 캐시 빌드
# ============================================================================

if __name__ == "__main__":
    """
    수동 캐시 빌드:
      python market_cap_cache.py             # screener API로 전체 갱신 (약 20초)
      python market_cap_cache.py IONQ PLTR   # 지정 종목만 종목별 조회
    """
    import sys

    if len(sys.argv) > 1:
        # 지정 종목 — 종목별 fast_info 조회 (폴백 함수 직접 호출)
        tickers = [t.upper() for t in sys.argv[1:]]
        print(f"📋 지정 종목 {len(tickers)}개 — 종목별 조회 모드")
        fresh = _fetch_market_caps_per_ticker(tickers)
        # 기존 캐시와 병합 저장
        cache = _load_cache(config.MARKET_CAP_CACHE_PATH)
        merged = {**cache.get('data', {}), **fresh}
        _save_cache(config.MARKET_CAP_CACHE_PATH, merged)
        result = fresh
    else:
        # 전체 — screener API로 일괄 갱신
        result = _fetch_market_caps_via_screener()
        _save_cache(config.MARKET_CAP_CACHE_PATH, result)

    print(f"\n📊 결과 요약: {len(result)}개 시총 확보")
    if result:
        sample = list(result.items())[:5]
        print("   샘플 5건:")
        for t, mc in sample:
            print(f"     {t}: ${mc/1e9:.2f}B")
