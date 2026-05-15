# ============================================================================
# 🏷️ [퀀트 유니버스] 섹터 정보 캐싱 시스템 (sector_cache.py)
# ============================================================================
# 역할: yfinance Ticker.info에서 sector를 조회하고 JSON 캐싱.
# 갱신: config.SECTOR_CACHE_DAYS(기본 30일)마다 자동 갱신 — 섹터는 거의 안 바뀜.
#
# screener API가 sector를 제공하지 않아 종목별 .info 호출 필요.
# 1차 필터 통과한 200~500개 종목에만 호출 → 비용 적당.
#
# 사용법:
#   from sector_cache import get_sectors
#   sectors = get_sectors(['IONQ', 'PLTR', 'AAPL'])
#   # {'IONQ': 'Technology', 'PLTR': 'Technology', 'AAPL': 'Technology'}
# ============================================================================

import json
import os
import time
from datetime import datetime, timedelta

import yfinance as yf

import config


CACHE_PATH = getattr(config, 'SECTOR_CACHE_PATH', 'data/sector_cache.json')
CACHE_DAYS = getattr(config, 'SECTOR_CACHE_DAYS', 30)


# ============================================================================
# [내부 헬퍼] 캐시 파일 입출력 (market_cap_cache와 동일 패턴)
# ============================================================================

def _load_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(data: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH) or '.', exist_ok=True)
    payload = {
        'updated_at': datetime.now().isoformat(timespec='seconds'),
        'data': data,
    }
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _entry_fresh(entry_ts: str, days: int) -> bool:
    """단일 엔트리의 fetched_at 신선도 확인."""
    if not entry_ts:
        return False
    try:
        updated = datetime.fromisoformat(entry_ts)
    except ValueError:
        return False
    return (datetime.now() - updated) < timedelta(days=days)


# ============================================================================
# [내부 헬퍼] yfinance 단일 조회
# ============================================================================

def _fetch_sector(ticker: str) -> str:
    """단일 종목 sector 조회. 실패 시 'Unknown' 반환."""
    try:
        info = yf.Ticker(ticker).info
        return info.get('sector') or 'Unknown'
    except Exception:
        return 'Unknown'


# ============================================================================
# [핵심] 섹터 조회 — 캐시 우선
# ============================================================================

def get_sectors(tickers: list, force_refresh: bool = False) -> dict:
    """
    종목 리스트의 섹터 정보를 반환. 캐시 우선, 만료/누락 종목만 yfinance 호출.

    Args:
        tickers: 조회할 티커 리스트
        force_refresh: True면 캐시 무시하고 전부 재조회

    Returns:
        dict: {ticker: sector_name}
    """
    cache = _load_cache()
    data = cache.get('data', {}) if not force_refresh else {}

    # 만료/누락 종목 식별
    to_fetch = []
    result = {}
    for t in tickers:
        entry = data.get(t)
        if entry and _entry_fresh(entry.get('fetched_at', ''), CACHE_DAYS):
            result[t] = entry.get('sector', 'Unknown')
        else:
            to_fetch.append(t)

    if not to_fetch:
        print(f"🏷️ 섹터 캐시 사용 (요청 {len(tickers)} 적중 {len(result)})")
        return result

    print(f"🏷️ 섹터 조회: 캐시 적중 {len(result)} / 신규 {len(to_fetch)}")
    start = time.time()
    now_iso = datetime.now().isoformat(timespec='seconds')

    for i, t in enumerate(to_fetch, 1):
        sector = _fetch_sector(t)
        data[t] = {'sector': sector, 'fetched_at': now_iso}
        result[t] = sector

        if i % 50 == 0 or i == len(to_fetch):
            elapsed = time.time() - start
            rate = i / elapsed if elapsed > 0 else 0
            remaining = (len(to_fetch) - i) / rate if rate > 0 else 0
            print(f"  진행 {i}/{len(to_fetch)} | "
                  f"경과 {elapsed:.0f}s 남은시간 {remaining:.0f}s")

    _save_cache(data)
    print(f"✅ 섹터 캐시 저장: {CACHE_PATH}")
    return result


# ============================================================================
# [단독 실행] 수동 캐시 빌드
# ============================================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        tickers = [t.upper() for t in sys.argv[1:]]
    else:
        tickers = config.TEST_TICKERS

    print(f"📋 섹터 조회 대상: {tickers}")
    result = get_sectors(tickers)
    print()
    for t, s in result.items():
        print(f"  {t}: {s}")
