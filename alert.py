# ============================================================================
# 🚨 [퀀트 유니버스] 실시간 알림 시스템 (alert.py)
# ============================================================================
# 역할: 보유 종목 모니터링 → 익절/손절 조건 도달 시 알림 발송
#
# 사용법:
#   python alert.py                    → 보유 종목 모니터링 시작
#   python alert.py --once             → 1회만 체크 후 종료
#   python alert.py --add IONQ 30.00   → 수동 감시 종목 추가
#   python alert.py --list             → 감시 중인 종목 확인
#   python alert.py --clear            → 수동 감시 종목 초기화
#
# 알림 채널:
#   1순위: 텔레그램 봇 (TELEGRAM_BOT_TOKEN 설정 시)
#   2순위: 콘솔 출력 + 비프음 (기본)
#
# 핵심 흐름:
#   trade_journal.py 보유종목 로드
#   → 매 5분마다 현재가 체크
#   → 익절/손절/급등/급락 조건 판단
#   → 텔레그램 or 콘솔 알림
# ============================================================================

import os
import sys
import time
import json
import logging
from datetime import datetime

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)

# --- 설정 ---
WATCHLIST_FILE = 'alert_watchlist.json'
ALERT_HISTORY_FILE = 'alert_history.json'


# ============================================================================
# [1] 감시 대상 관리
# ============================================================================

def _load_watchlist() -> list:
    """
    감시 대상 종목 로드.
    
    소스 2개를 합침:
      1. trade_journal.py 보유 종목 (자동)
      2. 수동 추가 종목 (alert_watchlist.json)
    
    Returns:
        list of dict: [{'ticker': 'IONQ', 'entry_price': 30.0, 
                        'stop_price': 27.5, 'source': 'journal'}, ...]
    """
    watchlist = []

    # --- 소스 1: trade_journal 보유 종목 ---
    try:
        from trade_journal import _load_sheet, SHEET_TRADES
        trades_df = _load_sheet(SHEET_TRADES)

        if not trades_df.empty and 'Result' in trades_df.columns:
            holdings = trades_df[trades_df['Result'] == '⏳ 보유중']

            for _, row in holdings.iterrows():
                entry_price = float(row['Entry_Price'])
                atr = float(row['ATR']) if row.get('ATR', '') != '' else 0

                # 손절가: 저장된 값 우선, 없으면 ATR 기반 계산
                if row.get('Stop_Price', '') != '' and not pd.isna(row.get('Stop_Price', '')):
                    stop_price = float(row['Stop_Price'])
                elif atr > 0:
                    stop_price = entry_price - (atr * config.ATR_STOP_MULTIPLIER)
                else:
                    stop_price = entry_price * (1 - config.STOP_LOSS_FIXED_PCT)

                # 익절가: 기본 10%
                take_profit_price = entry_price * (1 + config.TAKE_PROFIT_PCT)

                watchlist.append({
                    'ticker': row['Ticker'],
                    'entry_price': entry_price,
                    'shares': int(row['Shares']),
                    'stop_price': round(stop_price, 2),
                    'take_profit': round(take_profit_price, 2),
                    'trade_id': int(row['Trade_ID']),
                    'source': 'journal',
                })
    except Exception as e:
        logger.debug("trade_journal 로드 실패: %s", e)

    # --- 소스 2: 수동 감시 종목 ---
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, 'r') as f:
                manual = json.load(f)
            watchlist.extend(manual)
        except Exception:
            pass

    return watchlist


def add_manual_watch(ticker: str, entry_price: float):
    """수동 감시 종목 추가"""
    manual = []
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, 'r') as f:
                manual = json.load(f)
        except Exception:
            manual = []

    # ATR 기반 손절가 계산 시도
    stop_price = entry_price * (1 - config.STOP_LOSS_FIXED_PCT)
    take_profit = entry_price * (1 + config.TAKE_PROFIT_PCT)

    try:
        from indicators import Make_Indicators
        from data_loader import load_ohlcv
        df = load_ohlcv(ticker.upper(), start=config.START_DATE)
        df = Make_Indicators(df)
        if 'ATR' in df.columns and len(df) > 0:
            atr = float(df['ATR'].iloc[-1])
            if atr > 0 and config.STOP_LOSS_USE_ATR:
                stop_price = round(entry_price - atr * config.ATR_STOP_MULTIPLIER, 2)
    except Exception:
        pass

    ticker = ticker.upper()

    # 중복 제거
    manual = [m for m in manual if m['ticker'] != ticker]

    manual.append({
        'ticker': ticker,
        'entry_price': entry_price,
        'shares': 0,
        'stop_price': round(stop_price, 2),
        'take_profit': round(take_profit, 2),
        'trade_id': None,
        'source': 'manual',
    })

    with open(WATCHLIST_FILE, 'w') as f:
        json.dump(manual, f, indent=2)

    print(f"✅ 감시 추가: {ticker} @ ${entry_price:.2f}")
    print(f"   🛡️ 손절: ${stop_price:.2f} | 🎯 익절: ${take_profit:.2f}")


def clear_manual_watch():
    """수동 감시 종목 초기화"""
    if os.path.exists(WATCHLIST_FILE):
        os.remove(WATCHLIST_FILE)
    print("🗑️ 수동 감시 목록 초기화 완료")


def show_watchlist():
    """감시 중인 종목 출력"""
    watchlist = _load_watchlist()
    if not watchlist:
        print("\n📋 감시 중인 종목이 없습니다.")
        print("   - trade_journal.py에 보유 종목을 추가하거나")
        print("   - python alert.py --add IONQ 30.00 으로 수동 추가")
        return

    print(f"\n👁️ 감시 중인 종목 ({len(watchlist)}건)")
    print(f"{'─' * 75}")
    print(f"  {'종목':<6} | {'매수가':>10} | {'손절가':>10} | "
          f"{'익절가':>10} | {'소스':^10} | {'ID':>4}")
    print(f"{'─' * 75}")

    for w in watchlist:
        src = '📓일지' if w['source'] == 'journal' else '✋수동'
        tid = f"#{w['trade_id']}" if w.get('trade_id') else '—'
        print(f"  {w['ticker']:<6} | ${w['entry_price']:>8,.2f} | "
              f"${w['stop_price']:>8,.2f} | ${w['take_profit']:>8,.2f} | "
              f"{src:^10} | {tid:>4}")

    print(f"{'─' * 75}")


# ============================================================================
# [2] 현재가 조회
# ============================================================================

def _get_current_prices(tickers: list) -> dict:
    """
    복수 종목의 현재가를 한번에 조회합니다.
    
    Args:
        tickers: ['IONQ', 'PLTR', ...]
    
    Returns:
        dict: {'IONQ': 32.5, 'PLTR': 25.1, ...}
    """
    # 의도적으로 장중 미확정 봉을 사용 (실시간 폴링) — drop_intraday=False
    from data_loader import load_ohlcv

    prices = {}
    for ticker in tickers:
        try:
            df = load_ohlcv(ticker, start=datetime.now().strftime('%Y-%m-%d'), drop_intraday=False)
            if not df.empty:
                prices[ticker] = float(df['Close'].iloc[-1])
            else:
                df = load_ohlcv(ticker, drop_intraday=False)
                if not df.empty:
                    prices[ticker] = float(df['Close'].iloc[-1])
        except Exception as e:
            logger.debug("가격 조회 실패 (%s): %s", ticker, e)

    return prices


# ============================================================================
# [3] 알림 발송
# ============================================================================

def _send_alert(message: str, level: str = 'INFO'):
    """
    알림을 발송합니다.
    
    텔레그램 설정이 있으면 텔레그램으로, 없으면 콘솔에 출력합니다.
    
    Args:
        message: 알림 메시지
        level: 'INFO', 'WARNING', 'CRITICAL'
    """
    timestamp = datetime.now().strftime('%H:%M:%S')
    full_message = f"[{timestamp}] {message}"

    # 콘솔 출력 (항상)
    if level == 'CRITICAL':
        print(f"\n🚨🚨🚨 {full_message}")
        _beep()
    elif level == 'WARNING':
        print(f"\n⚠️ {full_message}")
        _beep()
    else:
        print(f"\n📱 {full_message}")

    # 텔레그램 발송 시도
    _send_telegram(full_message)

    # 알림 이력 저장
    _save_alert_history(message, level)


def _send_telegram(message: str):
    """텔레그램 봇으로 메시지 발송"""
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        return  # 설정 안 되어있으면 스킵

    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.warning("텔레그램 발송 실패: %s", resp.text)
    except ImportError:
        logger.debug("requests 미설치 — pip install requests")
    except Exception as e:
        logger.debug("텔레그램 에러: %s", e)


def _beep():
    """시스템 비프음"""
    try:
        import platform
        if platform.system() == 'Windows':
            import winsound
            winsound.Beep(1000, 500)
        else:
            print('\a', end='')  # 유닉스 벨
    except Exception:
        pass


def _save_alert_history(message: str, level: str):
    """알림 이력을 JSON 파일에 저장"""
    history = []
    if os.path.exists(ALERT_HISTORY_FILE):
        try:
            with open(ALERT_HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except Exception:
            history = []

    history.append({
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'level': level,
        'message': message,
    })

    # 최근 500건만 유지
    history = history[-500:]

    try:
        with open(ALERT_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ============================================================================
# [4] 조건 판단 + 모니터링 루프
# ============================================================================

def check_alerts(watchlist: list, prices: dict) -> list:
    """
    현재가와 감시 조건을 비교하여 알림 목록을 생성합니다.
    
    조건:
      🚨 CRITICAL: 손절가 이탈
      ⚠️ WARNING:  손절가 접근 (3% 이내)
      🎯 INFO:     익절 구간 진입
      🔥 INFO:     +15% 이상 급등
      📉 WARNING:  -5% 이상 하락 (손절가 전)
    
    Args:
        watchlist: _load_watchlist() 반환값
        prices: _get_current_prices() 반환값
    
    Returns:
        list of dict: 발생한 알림 목록
    """
    alerts = []

    for w in watchlist:
        ticker = w['ticker']
        if ticker not in prices:
            continue

        current = prices[ticker]
        entry = w['entry_price']
        stop = w['stop_price']
        target = w['take_profit']

        pnl_pct = ((current - entry) / entry) * 100
        stop_distance_pct = ((current - stop) / current) * 100

        src_tag = f"(#{w['trade_id']})" if w.get('trade_id') else "(수동)"

        # --- 🚨 손절가 이탈 ---
        if current <= stop:
            alerts.append({
                'ticker': ticker,
                'level': 'CRITICAL',
                'message': (
                    f"🚨 {ticker} 손절선 도달! 즉시 확인!\n"
                    f"   현재가: ${current:,.2f} | 손절가: ${stop:,.2f}\n"
                    f"   손익: {pnl_pct:+.1f}% {src_tag}"
                )
            })

        # --- ⚠️ 손절가 접근 (3% 이내) ---
        elif 0 < stop_distance_pct <= 3.0:
            alerts.append({
                'ticker': ticker,
                'level': 'WARNING',
                'message': (
                    f"⚠️ {ticker} 손절가 접근 중! (잔여 {stop_distance_pct:.1f}%)\n"
                    f"   현재가: ${current:,.2f} | 손절가: ${stop:,.2f}\n"
                    f"   손익: {pnl_pct:+.1f}% {src_tag}"
                )
            })

        # --- 🎯 익절 구간 ---
        if current >= target:
            extra = ""
            if pnl_pct >= 15:
                extra = "\n   🔥🔥 +15% 돌파! 분할 익절 고려"
            alerts.append({
                'ticker': ticker,
                'level': 'INFO',
                'message': (
                    f"🎯 {ticker} 익절 구간 진입! +{pnl_pct:.1f}%\n"
                    f"   현재가: ${current:,.2f} | 매수가: ${entry:,.2f}\n"
                    f"   목표가: ${target:,.2f} {src_tag}{extra}"
                )
            })

        # --- 📈 중간 상태 (양호) ---
        elif pnl_pct >= 5 and current < target:
            # 5% 이상 수익이지만 아직 익절 전 → 조용히 로그만
            logger.info("%s +%.1f%% (익절 전)", ticker, pnl_pct)

    return alerts


def run_monitor(once: bool = False):
    """
    메인 모니터링 루프.
    
    Args:
        once: True면 1회 체크 후 종료, False면 무한 루프
    """
    interval = config.ALERT_INTERVAL

    print("=" * 60)
    print("🚨 [ Richman Alert System ] 실시간 모니터링")
    print("=" * 60)
    print(f"  체크 주기: {interval}초 ({interval // 60}분)")
    print(f"  익절 기준: +{config.TAKE_PROFIT_PCT:.0%}")
    print(f"  손절 방식: {'ATR 기반' if config.STOP_LOSS_USE_ATR else '고정 %'}")

    tg_status = "✅ 연결됨" if config.TELEGRAM_BOT_TOKEN else "❌ 미설정"
    print(f"  텔레그램: {tg_status}")
    print(f"  종료: Ctrl+C")
    print("=" * 60)

    # 중복 알림 방지용 (같은 알림 10분 내 재발송 안 함)
    recent_alerts = {}

    cycle = 0
    while True:
        cycle += 1
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # --- 감시 대상 로드 (매 사이클마다 갱신) ---
        watchlist = _load_watchlist()
        if not watchlist:
            print(f"\n[{now}] 📋 감시 종목 없음. 대기 중...")
            if once:
                return
            time.sleep(interval)
            continue

        tickers = list(set(w['ticker'] for w in watchlist))
        print(f"\n[{now}] 🔍 체크 #{cycle}: {', '.join(tickers)}")

        # --- 현재가 조회 ---
        prices = _get_current_prices(tickers)
        if not prices:
            print(f"  ⚠️ 가격 조회 실패. {interval}초 후 재시도...")
            if once:
                return
            time.sleep(interval)
            continue

        # 현재 상태 간략 출력
        for w in watchlist:
            t = w['ticker']
            if t in prices:
                pnl = ((prices[t] - w['entry_price']) / w['entry_price']) * 100
                emoji = '🟢' if pnl >= 0 else '🔴'
                print(f"  {emoji} {t}: ${prices[t]:,.2f} ({pnl:+.1f}%)")

        # --- 조건 판단 ---
        alerts = check_alerts(watchlist, prices)

        # --- 알림 발송 (중복 방지) ---
        for alert in alerts:
            key = f"{alert['ticker']}_{alert['level']}"
            last_sent = recent_alerts.get(key, 0)

            # 같은 종목+레벨은 10분 이내 재발송 안 함 (CRITICAL은 5분)
            cooldown = 300 if alert['level'] == 'CRITICAL' else 600

            if time.time() - last_sent > cooldown:
                _send_alert(alert['message'], alert['level'])
                recent_alerts[key] = time.time()

        if not alerts:
            print(f"  ✅ 이상 없음")

        if once:
            return

        # --- 대기 ---
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n\n👋 모니터링 종료.")
            return


# ============================================================================
# [CLI] 명령줄 인터페이스
# ============================================================================

def main():
    if len(sys.argv) >= 2:
        arg = sys.argv[1].lower().replace('-', '')

        # --once: 1회 체크
        if arg == 'once':
            run_monitor(once=True)
            return

        # --add TICKER PRICE: 수동 감시 추가
        if arg == 'add':
            if len(sys.argv) < 4:
                print("사용법: python alert.py --add IONQ 30.00")
                return
            ticker = sys.argv[2]
            price = float(sys.argv[3])
            add_manual_watch(ticker, price)
            return

        # --list: 감시 목록 확인
        if arg == 'list':
            show_watchlist()
            return

        # --clear: 수동 감시 초기화
        if arg == 'clear':
            clear_manual_watch()
            return

        # --help
        if arg in ('help', 'h'):
            _print_help()
            return

    # 기본: 모니터링 시작
    run_monitor(once=False)


def _print_help():
    print("""
🚨 alert.py — 실시간 익절/손절 알림 시스템

사용법:
  python alert.py                    모니터링 시작 (무한 루프)
  python alert.py --once             1회 체크 후 종료
  python alert.py --add IONQ 30.00   수동 감시 종목 추가
  python alert.py --list             감시 목록 확인
  python alert.py --clear            수동 감시 목록 초기화

알림 조건:
  🚨 CRITICAL  손절가 이탈 → 즉시 확인
  ⚠️ WARNING   손절가 접근 (3% 이내)
  🎯 INFO      익절 구간 진입 (+10%)
  🔥 INFO      +15% 돌파 → 분할 익절 고려

텔레그램 설정 (선택):
  환경변수에 TG_BOT_TOKEN, TG_CHAT_ID 설정
  미설정 시 콘솔 출력 + 비프음으로 동작

연동:
  trade_journal.py 보유 종목을 자동으로 감시합니다.
  수동 추가 종목은 alert_watchlist.json에 저장됩니다.
    """)


if __name__ == "__main__":
    main()