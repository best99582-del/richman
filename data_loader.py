# ============================================================================
# 📥 [퀀트 유니버스] 데이터 로딩 단일 진입점 (data_loader.py)
# ============================================================================
# 역할: fdr.DataReader 호출을 감싸 장중 미확정 봉을 자동 제거
# 파이프라인 위치: [0단계] 데이터 수집 — 모든 OHLCV 로딩의 단일 출구
# 의존성: config.py
#
# 핵심 문제:
#   fdr.DataReader는 미국 정규장 개장 후 호출 시 마지막 행에
#   "오늘 장중 미확정 봉"을 끼워 넣음. 이걸 그대로 쓰면 RSI/지표 왜곡.
#
# 해결:
#   미국 동부시간(ET) 기준으로 정규장 종료 + 여유시간 경과 여부를 체크.
#   미경과면 마지막 행 제거.
# ============================================================================

import atexit
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import FinanceDataReader as fdr

import config

logger = logging.getLogger(__name__)

# 세션 단위 통계 (개별 종목 로그 대신 종료 시 요약)
_dropped_count = 0
_dropped_dates: set[str] = set()


def _print_summary():
    if _dropped_count > 0:
        dates = ", ".join(sorted(_dropped_dates))
        print(f"ℹ️  장중 미확정 봉 {_dropped_count}건 제거됨 (대상 날짜: {dates})")


atexit.register(_print_summary)


# ============================================================================
# [핵심] 단일 진입점 — load_ohlcv
# ============================================================================

def load_ohlcv(
    ticker: str,
    start: str | None = None,
    end: str | None = None,
    *,
    drop_intraday: bool = True,
    require_settled: bool = False,
) -> pd.DataFrame:
    """
    fdr.DataReader 호출 + 장중 미확정 봉 자동 제거.

    Args:
        ticker: 종목 티커 (예: 'AAPL', 'IONQ', 'QQQ')
        start: 시작일 (예: '2018-01-01'). None이면 fdr 기본값.
        end:   종료일. None이면 최신.
        drop_intraday: True면 미확정 마지막 봉 자동 제거 (라이브 추론용 기본)
        require_settled: True면 미확정 봉 발견 시 ValueError (백테스트/학습 보호)

    Returns:
        OHLCV DataFrame. 미확정 봉이 제거된 상태.

    Raises:
        ValueError: require_settled=True인데 마지막 봉이 미확정인 경우.
    """
    if start is not None and end is not None:
        df = fdr.DataReader(ticker, start, end)
    elif start is not None:
        df = fdr.DataReader(ticker, start)
    else:
        df = fdr.DataReader(ticker)

    if df is None or df.empty:
        return df

    if not drop_intraday and not require_settled:
        return df

    if not _is_last_bar_unsettled(df):
        return df

    if require_settled:
        last_date = df.index[-1].date()
        raise ValueError(
            f"[{ticker}] 마지막 봉이 미확정 (날짜 {last_date}). "
            f"백테스트/학습 데이터 오염 방지를 위해 중단."
        )

    last_date = df.index[-1].date()
    global _dropped_count
    _dropped_count += 1
    _dropped_dates.add(str(last_date))
    logger.info("intraday bar dropped: %s @ %s", ticker, last_date)
    return df.iloc[:-1]


# ============================================================================
# [내부] 마지막 봉이 미확정인지 판정
# ============================================================================

def _is_last_bar_unsettled(df: pd.DataFrame) -> bool:
    """
    마지막 봉이 미확정 장중 봉인지 판정.

    판정 기준:
      1. 봉 날짜가 ET 기준 과거 → 확정
      2. 봉 날짜가 ET 기준 미래 → 비정상, 보수적으로 미확정
      3. 봉 날짜가 ET 기준 오늘 → 정규장 마감 + 여유시간 경과 여부 체크
      4. 보조: Volume == 0 또는 High == Low == Close → 강제 미확정
    """
    last_idx = df.index[-1]
    if not isinstance(last_idx, pd.Timestamp):
        last_idx = pd.Timestamp(last_idx)
    last_date = last_idx.date()

    last_row = df.iloc[-1]
    if 'Volume' in df.columns and last_row.get('Volume', 1) == 0:
        return True
    if {'High', 'Low', 'Close'}.issubset(df.columns):
        if last_row['High'] == last_row['Low'] == last_row['Close']:
            return True

    now_et = datetime.now(ZoneInfo(config.MARKET_TZ))

    if last_date < now_et.date():
        return False
    if last_date > now_et.date():
        return True

    close_h, close_m = config.MARKET_CLOSE
    settled_dt = datetime.combine(last_date, time(close_h, close_m)) + timedelta(
        minutes=config.INTRADAY_SAFE_MARGIN_MIN
    )
    return now_et.time() < settled_dt.time()
