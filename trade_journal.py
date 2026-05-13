# ============================================================================
# 📓 [퀀트 유니버스] 매매 일지 시스템 (trade_journal.py)
# ============================================================================
# 역할: 실전 매매 기록 + AI 추천 로그 + 월간 성과 통계 자동 산출
# 저장: Excel 파일 (3개 시트: 매매일지, AI추천로그, 월간통계)
#
# 사용법:
#
#   [분석 + 기록]
#   python trade_journal.py log IONQ PLTR
#     → predict.py 5-Fold 정밀 분석 실행 후 AI추천로그에 자동 저장
#     → 매수하지 않아도 기록됨 (Acted='N')
#
#   python trade_journal.py log scan
#     → screener.py 전수조사 → 후보 추출 → predict.py 정밀 분석 → AI추천로그 저장
#
#   [매수 기록]
#   python trade_journal.py add IONQ 35.20 12 "BB 스퀴즈 돌파"
#     → 매매일지에 매수 기록 추가 (티커 / 단가 / 수량 / 메모)
#     → 동일 날짜 AI추천로그 Acted='N' → 'Y' 자동 동기화
#     → 손절가·AI확률·정밀도는 당일 AI추천로그에서 자동 참조
#
#   [매도 기록]
#   python trade_journal.py close 1 38.50 익절
#     → Trade_ID=1 거래 청산 (단가 / 사유)
#     → 수익률·순손익·보유일·수수료 자동 계산 → 엑셀 저장
#
#   [사후 검증]
#   python trade_journal.py update
#     → AI추천로그에서 추천일로부터 10일 경과된 미검증 건 자동 처리
#     → 5일/10일 후 종가, 10일 내 최고가, 가상수익률, AI적중 여부(✅/❌) 기록
#
#   [통계]
#   python trade_journal.py stats
#     → 월별 승률·손익·AI 적중률·놓친 수익 리포트 출력 + 엑셀 저장
#
#   [열기]
#   python trade_journal.py open
#     → trade_journal.xlsx 파일 직접 열기
#
# 핵심 흐름:
#   log 실행 → AI추천로그 자동 기록 (Acted='N')
#   add 실행 → 매매일지 기록 + 동일 날짜 AI추천로그 Acted='Y' 동기화
#   close 실행 → 수익률 자동 계산 + 매매일지 청산 처리
#   10일 후 update 실행 → AI 적중 여부 + 놓친 수익 자동 추적
#   stats 실행 → 월간 성과 리포트 산출
# ============================================================================

import os
import sys
import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)

# --- 설정 (config.py에서 로드) ---
JOURNAL_FILE = config.JOURNAL_PATH

SHEET_TRADES = config.JOURNAL_SHEETS[1]
SHEET_AI_LOG = config.JOURNAL_SHEETS[0]
SHEET_MONTHLY = config.JOURNAL_SHEETS[2]


# ============================================================================
# [유틸리티] 엑셀 파일 로드/저장
# ============================================================================

def _load_sheet(sheet_name: str) -> pd.DataFrame:
    """
    엑셀 파일에서 특정 시트를 DataFrame으로 로드합니다.
    파일이 없거나 시트가 없으면 빈 DataFrame 반환.
    사용자가 엑셀에서 데이터를 지운 빈 행은 자동 제거 — ID 컬럼만 남고
    핵심 컬럼(Ticker)이 비어 있으면 유령 행으로 간주.
    """
    if not os.path.exists(JOURNAL_FILE):
        return pd.DataFrame()
    try:
        df = pd.read_excel(JOURNAL_FILE, sheet_name=sheet_name)
    except (ValueError, KeyError):
        return pd.DataFrame()
    # 전 컬럼 NaN 또는 Ticker가 비어있는 행 제거
    df = df.dropna(how='all')
    if 'Ticker' in df.columns:
        df = df[df['Ticker'].notna() & (df['Ticker'].astype(str).str.strip() != '')]
    return df.reset_index(drop=True)


def _reindex_ids(df: pd.DataFrame, id_col: str) -> pd.DataFrame:
    """ID 컬럼을 1부터 순차 재부여 — 사용자가 중간 행을 지운 경우 갭 메움."""
    if df.empty or id_col not in df.columns:
        return df
    df = df.copy()
    df[id_col] = range(1, len(df) + 1)
    return df


def _load_all() -> tuple:
    """3개 시트를 한번에 로드. 매매일지/AI추천로그는 ID 자동 재부여."""
    trades = _reindex_ids(_load_sheet(SHEET_TRADES), 'Trade_ID')
    ai_log = _reindex_ids(_load_sheet(SHEET_AI_LOG), 'Rec_ID')
    monthly = _load_sheet(SHEET_MONTHLY)
    return trades, ai_log, monthly


def _save_all(trades_df, ai_log_df, monthly_df):
    try:
        with pd.ExcelWriter(JOURNAL_FILE, engine='openpyxl') as writer:
            for df, sheet in [
                (trades_df, SHEET_TRADES),
                (ai_log_df, SHEET_AI_LOG),
                (monthly_df, SHEET_MONTHLY),
            ]:
                (df if not df.empty else pd.DataFrame()).to_excel(writer, sheet_name=sheet, index=False)
        print(f"💾 저장 완료: {JOURNAL_FILE}")
    except PermissionError:
        print(f"⚠️ {JOURNAL_FILE}이 열려있습니다. 닫고 다시 시도하세요.")


# ============================================================================
# [핵심 1] 매수 기록 (add)
# ============================================================================

def add_trade(
    ticker: str,
    entry_price: float,
    shares: int,
    reason: str = '',
    predict_data: dict = None
):
    """
    매수 거래를 매매일지에 기록합니다.
    
    predict.py의 분석 결과(predict_data)가 있으면 AI 정보를 자동 입력.
    없으면 AI추천로그에서 같은 날짜/종목을 찾아 자동 매칭.
    
    동시에 AI추천로그에서 해당 건의 Acted를 'Y'로 동기화.
    
    Args:
        ticker: 종목 티커
        entry_price: 매수 단가 ($)
        shares: 매수 수량
        reason: 매수 근거 메모
        predict_data: predict.py Analyze_Full 반환 dict (선택)
    """
    trades_df, ai_log_df, monthly_df = _load_all()

    # _load_all에서 ID 재부여되어 항상 연속. 다음 ID는 len+1
    next_id = len(trades_df) + 1

    today = datetime.now().strftime('%Y-%m-%d')
    ticker = ticker.upper()

    # --- AI 정보 자동 매칭 ---
    # 우선순위: predict_data 직접 전달 > AI추천로그에서 검색
    ai_prob = ''
    hist_precision = ''
    atr = ''
    kelly_weight = ''
    stop_price = ''

    if predict_data:
        # predict.py 결과에서 직접 가져옴
        ai_prob = predict_data.get('Prob', '')
        hist_precision = predict_data.get('Hist_Precision', '')
        atr = predict_data.get('ATR', '')
        kelly_weight = predict_data.get('Kelly_Weight', '')
        stop_price = predict_data.get('Stop_Price', '')
    elif not ai_log_df.empty:
        # AI추천로그에서 같은 날짜 + 같은 종목 검색
        match = ai_log_df[
            (ai_log_df['Ticker'] == ticker) &
            (ai_log_df['Rec_Date'] == today)
        ]
        if not match.empty:
            latest = match.iloc[-1]
            ai_prob = latest.get('AI_Prob', '')
            hist_precision = latest.get('Hist_Precision', '')
            atr = latest.get('ATR', '')
            kelly_weight = latest.get('Kelly_Weight', '')

    # 손절가 자동 계산
    if not stop_price and atr and isinstance(atr, (int, float)) and atr > 0:
        stop_price = round(entry_price - (atr * config.ATR_STOP_MULTIPLIER), 2)

    # 투입금액
    invest_amount = round(entry_price * shares, 2)

    # --- 매매일지에 추가 ---
    new_row = {
        'Trade_ID': next_id,
        'Ticker': ticker,
        'Entry_Date': today,
        'Entry_Price': entry_price,
        'Shares': shares,
        'Entry_Reason': reason,
        'Exit_Date': '',
        'Exit_Price': '',
        'Exit_Reason': '',
        'Invest_Amount': invest_amount,
        'Exit_Amount': '',
        'Fee': '',
        'Net_PnL': '',
        'Return_Pct': '',
        'Holding_Days': '',
        'Result': '⏳ 보유중',
        'AI_Prob': ai_prob,
        'Hist_Precision': hist_precision,
        'ATR': atr,
        'Stop_Price': stop_price,
        'Kelly_Weight': kelly_weight,
    }

    trades_df = pd.concat([trades_df, pd.DataFrame([new_row])], ignore_index=True)

    # --- AI추천로그 Acted 동기화 ---
    if not ai_log_df.empty and 'Acted' in ai_log_df.columns:
        match_mask = (
            (ai_log_df['Ticker'] == ticker) &
            (ai_log_df['Rec_Date'] == today)
        )
        ai_log_df.loc[match_mask, 'Acted'] = 'Y'

    _save_all(trades_df, ai_log_df, monthly_df)

    print(f"\n✅ 매수 기록 완료!")
    print(f"  📌 #{next_id} {ticker} | {shares}주 × ${entry_price} = ${invest_amount:,.2f}")
    if stop_price:
        print(f"  🛡️ 손절가: ${stop_price}")
    if ai_prob:
        print(f"  🤖 AI확률: {float(ai_prob):.1%} | 정밀도: {float(hist_precision):.1%}")


# ============================================================================
# [핵심 2] 매도 기록 (close)
# ============================================================================

def close_trade(trade_id: int, exit_price: float, reason: str = ''):
    """
    보유 중인 거래를 청산(매도) 처리합니다.
    수익률, 순손익, 보유일수를 자동 계산합니다.
    
    Args:
        trade_id: 청산할 Trade_ID
        exit_price: 매도 단가 ($)
        reason: 매도 사유 (익절/손절/기타)
    """
    trades_df, ai_log_df, monthly_df = _load_all()

    if trades_df.empty or 'Trade_ID' not in trades_df.columns:
        print("⚠️ 매매일지가 비어있습니다.")
        return

    mask = trades_df['Trade_ID'] == trade_id
    if not mask.any():
        print(f"⚠️ Trade_ID #{trade_id}를 찾을 수 없습니다.")
        return

    idx = trades_df[mask].index[0]
    row = trades_df.loc[idx]

    if row.get('Result', '') != '⏳ 보유중':
        print(f"⚠️ #{trade_id}는 이미 청산된 거래입니다.")
        return

    # --- 자동 계산 ---
    entry_price = float(row['Entry_Price'])
    shares = int(row['Shares'])
    entry_date = pd.to_datetime(row['Entry_Date'])
    exit_date = datetime.now()

    invest_amount = entry_price * shares
    exit_amount = exit_price * shares
    fee = (invest_amount + exit_amount) * config.FEE_RATE
    net_pnl = exit_amount - invest_amount - fee
    return_pct = (net_pnl / invest_amount) * 100
    holding_days = (exit_date - entry_date).days
    result = '✅ 익절' if net_pnl > 0 else '❌ 손절'

    # --- 업데이트 ---
    trades_df.loc[idx, 'Exit_Date'] = exit_date.strftime('%Y-%m-%d')
    trades_df.loc[idx, 'Exit_Price'] = exit_price
    trades_df.loc[idx, 'Exit_Reason'] = reason
    trades_df.loc[idx, 'Exit_Amount'] = round(exit_amount, 2)
    trades_df.loc[idx, 'Fee'] = round(fee, 2)
    trades_df.loc[idx, 'Net_PnL'] = round(net_pnl, 2)
    trades_df.loc[idx, 'Return_Pct'] = round(return_pct, 2)
    trades_df.loc[idx, 'Holding_Days'] = holding_days
    trades_df.loc[idx, 'Result'] = result

    _save_all(trades_df, ai_log_df, monthly_df)

    emoji = '🎉' if net_pnl > 0 else '😢'
    print(f"\n{emoji} 매도 기록 완료!")
    print(f"  📌 #{trade_id} {row['Ticker']} | {result}")
    print(f"  💰 손익: ${net_pnl:+,.2f} ({return_pct:+.2f}%)")
    print(f"  📅 보유: {holding_days}일 | 수수료: ${fee:,.2f}")


# ============================================================================
# [핵심 3] AI 추천 일괄 저장 (predict.py에서 호출)
# ============================================================================

def log_ai_recommendations(picks: list):
    """
    predict.py Deep_Scan 결과를 AI추천로그에 일괄 저장합니다.
    매수 여부(Acted)는 기본 'N'. 실제 매수 시 add_trade에서 'Y'로 동기화.
    
    Args:
        picks: Deep_Scan 또는 ai_scanner 반환 리스트
    """
    trades_df, ai_log_df, monthly_df = _load_all()

    # _load_all에서 ID 재부여되어 항상 연속. 다음 ID는 len+1
    next_id = len(ai_log_df) + 1
    today = datetime.now().strftime('%Y-%m-%d')

    new_rows = []
    for p in picks:
        kelly_w = p.get('Kelly_Weight', 0)

        new_rows.append({
            'Rec_ID': next_id,
            'Rec_Date': today,
            'Ticker': p.get('Ticker', ''),
            'AI_Prob': round(p.get('Prob', 0), 4),
            'Hist_Precision': round(p.get('Hist_Precision', 0.5), 4),
            'Rec_Price': p.get('Current_Price', 0),
            'ATR': round(p.get('ATR', 0), 4),
            'Stop_Price': p.get('Stop_Price', ''),
            'Stop_Pct': p.get('Stop_Pct', ''),
            'Vol_Ratio': round(p.get('Vol_Ratio', 1.0), 2),
            'Kelly_Weight': round(kelly_w, 4),
            'Acted': 'N',
            'Price_After_5D': '',
            'Price_After_10D': '',
            'High_After_10D': '',
            'Virtual_Return': '',
            'AI_Correct': '',
        })
        next_id += 1

    ai_log_df = pd.concat([ai_log_df, pd.DataFrame(new_rows)], ignore_index=True)
    _save_all(trades_df, ai_log_df, monthly_df)

    print(f"\n📝 AI 추천 {len(new_rows)}건 기록 완료 ({today})")
    for p in picks:
        prob = p.get('Prob', 0)
        prec = p.get('Hist_Precision', 0)
        print(f"  - {p.get('Ticker', '?')}: AI {prob:.1%} | 정밀도 {prec:.1%}")


# ============================================================================
# [핵심 4] AI 추천 사후 검증 (update)
# ============================================================================

def update_ai_results():
    """
    AI추천로그에서 추천일로부터 10일 이상 지난 미검증 건을 찾아
    실제 가격을 수집하고 AI 적중 여부를 자동 판정합니다.
    
    적중 기준: 10일 내 최고가가 추천가 대비 config.AI_TARGET_PCT% 이상
    
    동시에 매매일지와 대조하여 Acted 컬럼을 자동 동기화합니다.
    """
    from data_loader import load_ohlcv

    trades_df, ai_log_df, monthly_df = _load_all()

    if ai_log_df.empty:
        print("⚠️ AI추천로그가 비어있습니다.")
        return

    today = datetime.now()
    updated = 0

    for idx, row in ai_log_df.iterrows():
        # 이미 검증된 건 스킵
        if row.get('AI_Correct', '') in ['✅', '❌']:
            continue

        rec_date = pd.to_datetime(row['Rec_Date'])
        days_elapsed = (today - rec_date).days

        # 10일 이상 지나야 검증 가능
        if days_elapsed < config.AI_FORECAST_PERIOD:
            continue

        try:
            ticker = row['Ticker']
            rec_price = float(row['Rec_Price'])

            # 추천일 이후 데이터 수집
            start = (rec_date + timedelta(days=1)).strftime('%Y-%m-%d')
            end = (rec_date + timedelta(days=config.AI_FORECAST_PERIOD + 5)).strftime('%Y-%m-%d')
            df_after = load_ohlcv(ticker, start=start, end=end)

            if len(df_after) == 0:
                continue

            # 5일 후 종가
            if len(df_after) >= 5:
                ai_log_df.loc[idx, 'Price_After_5D'] = round(df_after['Close'].iloc[4], 2)

            # 10일 범위 데이터
            period = df_after.head(config.AI_FORECAST_PERIOD)

            # 10일 후 종가
            if len(period) >= config.AI_FORECAST_PERIOD:
                ai_log_df.loc[idx, 'Price_After_10D'] = round(period['Close'].iloc[-1], 2)

            # 10일 내 최고가
            high_max = period['High'].max()
            ai_log_df.loc[idx, 'High_After_10D'] = round(high_max, 2)

            # 가상 수익률 = (최고가 / 추천가 - 1) × 100
            virtual_return = ((high_max / rec_price) - 1) * 100
            ai_log_df.loc[idx, 'Virtual_Return'] = round(virtual_return, 2)

            # AI 적중 여부
            hit = virtual_return >= config.AI_TARGET_PCT
            ai_log_df.loc[idx, 'AI_Correct'] = '✅' if hit else '❌'

            updated += 1

        except Exception as e:
            logger.debug("검증 실패 (%s): %s", row.get('Ticker', '?'), e)

    # --- 매매일지와 Acted 동기화 ---
    if not trades_df.empty and 'Ticker' in trades_df.columns:
        for idx, row in ai_log_df.iterrows():
            if row.get('Acted', 'N') == 'Y':
                continue
            match = trades_df[
                (trades_df['Ticker'] == row['Ticker']) &
                (trades_df['Entry_Date'] == row['Rec_Date'])
            ]
            if not match.empty:
                ai_log_df.loc[idx, 'Acted'] = 'Y'

    _save_all(trades_df, ai_log_df, monthly_df)
    print(f"\n🔄 AI 추천 검증 완료: {updated}건 업데이트")

    # 미검증 건수 안내
    pending = ai_log_df[~ai_log_df['AI_Correct'].isin(['✅', '❌'])]
    if not pending.empty:
        print(f"  ⏳ 아직 검증 대기 중: {len(pending)}건 (10일 미경과)")


# ============================================================================
# [핵심 5] 월간 통계 산출 (stats)
# ============================================================================

def generate_stats():
    """매매일지 + AI추천로그를 분석하여 월간통계 산출 + 콘솔 리포트"""
    trades_df, ai_log_df, _ = _load_all()

    # --- 실매매 통계 ---
    closed = pd.DataFrame()
    if not trades_df.empty and 'Result' in trades_df.columns:
        closed = trades_df[trades_df['Result'].isin(['✅ 익절', '❌ 손절'])].copy()

    if closed.empty:
        print("\n⚠️ 청산된 거래가 없어 매매 통계 산출 불가.")
        _print_ai_stats(ai_log_df)
        # 빈 월간통계라도 저장
        _save_all(trades_df, ai_log_df, pd.DataFrame())
        return

    # 숫자 변환
    for col in ['Return_Pct', 'Net_PnL', 'Holding_Days', 'AI_Prob', 'Hist_Precision']:
        if col in closed.columns:
            closed[col] = pd.to_numeric(closed[col], errors='coerce')

    closed['Month'] = pd.to_datetime(closed['Exit_Date']).dt.to_period('M').astype(str)
    closed['Is_Win'] = (closed['Result'] == '✅ 익절').astype(int)

    # --- 월별 집계 ---
    monthly_rows = []
    for month, grp in closed.groupby('Month'):
        wins = grp[grp['Is_Win'] == 1]
        loses = grp[grp['Is_Win'] == 0]

        monthly_rows.append({
            'Month': month,
            'Total_Trades': len(grp),
            'Win_Rate': round(grp['Is_Win'].mean() * 100, 1),
            'Total_PnL': round(grp['Net_PnL'].sum(), 2),
            'Avg_Return': round(grp['Return_Pct'].mean(), 2),
            'Avg_Holding_Days': round(grp['Holding_Days'].mean(), 1),
            'AI_Rec_Count': '',
            'AI_Hit_Rate': '',
            'Missed_Profit': '',
            'Avg_AI_Prob_Win': round(wins['AI_Prob'].mean(), 3) if not wins.empty else '',
            'Avg_AI_Prob_Lose': round(loses['AI_Prob'].mean(), 3) if not loses.empty else '',
            'Avg_Precision_Win': round(wins['Hist_Precision'].mean(), 3) if not wins.empty else '',
            'Avg_Precision_Lose': round(loses['Hist_Precision'].mean(), 3) if not loses.empty else '',
        })

    monthly_df = pd.DataFrame(monthly_rows)

    # --- AI 추천 통계 병합 ---
    if not ai_log_df.empty and 'AI_Correct' in ai_log_df.columns:
        verified = ai_log_df[ai_log_df['AI_Correct'].isin(['✅', '❌'])].copy()
        if not verified.empty:
            verified['Month'] = pd.to_datetime(verified['Rec_Date']).dt.to_period('M').astype(str)
            verified['Virtual_Return'] = pd.to_numeric(verified['Virtual_Return'], errors='coerce')
            verified['Is_Hit'] = (verified['AI_Correct'] == '✅').astype(int)

            for idx, row in monthly_df.iterrows():
                m = row['Month']
                m_ai = verified[verified['Month'] == m]
                if m_ai.empty:
                    continue

                monthly_df.loc[idx, 'AI_Rec_Count'] = len(m_ai)
                monthly_df.loc[idx, 'AI_Hit_Rate'] = round(m_ai['Is_Hit'].mean() * 100, 1)

                # 놓친 수익
                missed = m_ai[(m_ai['Acted'] == 'N') & (m_ai['Is_Hit'] == 1)]
                monthly_df.loc[idx, 'Missed_Profit'] = round(missed['Virtual_Return'].sum(), 2)

    # --- 저장 ---
    _save_all(trades_df, ai_log_df, monthly_df)

    # --- 콘솔 출력 ---
    _print_trade_stats(closed, monthly_df)
    _print_ai_stats(ai_log_df)


# ============================================================================
# [유틸리티] 콘솔 출력
# ============================================================================

def _print_trade_stats(closed: pd.DataFrame, monthly_df: pd.DataFrame):
    """실매매 통계 콘솔 출력"""
    print("\n" + "=" * 70)
    print("📊 [ 실전 매매 성과 리포트 ]")
    print("=" * 70)
    print(f"  총 매매: {len(closed)}회")
    print(f"  승률: {closed['Is_Win'].mean():.1%}")
    print(f"  총 손익: ${closed['Net_PnL'].sum():+,.2f}")
    print(f"  평균 수익률: {closed['Return_Pct'].mean():+.2f}%")
    print(f"  평균 보유일: {closed['Holding_Days'].mean():.1f}일")

    if not monthly_df.empty:
        print(f"\n{'─' * 70}")
        print(f"  {'월':^10} | {'매매':^6} | {'승률':^8} | {'손익($)':^12} | {'평균수익':^8}")
        print(f"{'─' * 70}")
        for _, m in monthly_df.iterrows():
            print(f"  {m['Month']:^10} | {m['Total_Trades']:^6} | "
                  f"{m['Win_Rate']:>5.1f}%  | "
                  f"${m['Total_PnL']:>+10,.2f} | {m['Avg_Return']:>+6.2f}%")
    print("=" * 70)


def _print_ai_stats(ai_log_df: pd.DataFrame):
    """AI 추천 성과 콘솔 출력"""
    if ai_log_df.empty or 'AI_Correct' not in ai_log_df.columns:
        return

    verified = ai_log_df[ai_log_df['AI_Correct'].isin(['✅', '❌'])]
    if verified.empty:
        pending = len(ai_log_df[~ai_log_df['AI_Correct'].isin(['✅', '❌'])])
        if pending > 0:
            print(f"\n📡 AI 추천 검증 대기 중: {pending}건 (10일 후 update 실행)")
        return

    total = len(verified)
    hits = len(verified[verified['AI_Correct'] == '✅'])
    hit_rate = hits / total * 100

    acted = verified[verified['Acted'] == 'Y']
    not_acted = verified[verified['Acted'] == 'N']
    missed_hits = not_acted[not_acted['AI_Correct'] == '✅']
    missed_profit = pd.to_numeric(missed_hits['Virtual_Return'], errors='coerce').sum()

    print(f"\n{'=' * 70}")
    print(f"🤖 [ AI 추천 성과 리포트 ]")
    print(f"{'=' * 70}")
    print(f"  총 추천: {total}건 | 적중: {hits}건 | 적중률: {hit_rate:.1f}%")
    print(f"  실제 매수: {len(acted)}건 | 미매수: {len(not_acted)}건")

    if len(missed_hits) > 0:
        print(f"\n  ⚠️ 놓친 기회: {len(missed_hits)}건 (AI 맞았는데 안 산 것)")
        print(f"  💸 놓친 가상 수익 합계: {missed_profit:+.1f}%")

    # AI 확률 구간별 적중률
    v = verified.copy()
    v['AI_Prob'] = pd.to_numeric(v['AI_Prob'], errors='coerce')
    v['Is_Hit'] = (v['AI_Correct'] == '✅').astype(int)

    print(f"\n  📊 AI 확률 구간별 적중률:")
    for lo, hi in [(0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.7), (0.7, 1.0)]:
        sub = v[(v['AI_Prob'] >= lo) & (v['AI_Prob'] < hi)]
        if len(sub) > 0:
            print(f"     {lo:.0%}~{hi:.0%}: {sub['Is_Hit'].mean() * 100:.0f}% ({len(sub)}건)")

    # 모델 정밀도 구간별 적중률
    v['Hist_Precision'] = pd.to_numeric(v['Hist_Precision'], errors='coerce')
    print(f"\n  📊 모델 정밀도 구간별 적중률:")
    for lo, hi in [(0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 1.0)]:
        sub = v[(v['Hist_Precision'] >= lo) & (v['Hist_Precision'] < hi)]
        if len(sub) > 0:
            print(f"     {lo:.0%}~{hi:.0%}: {sub['Is_Hit'].mean() * 100:.0f}% ({len(sub)}건)")

    print(f"{'=' * 70}")


# ============================================================================
# [유틸리티] 보유 중 종목 조회
# ============================================================================

def show_holdings():
    """현재 보유 중인 종목을 출력합니다."""
    trades_df = _load_sheet(SHEET_TRADES)

    if trades_df.empty or 'Result' not in trades_df.columns:
        print("\n📋 보유 중인 종목이 없습니다.")
        return

    holdings = trades_df[trades_df['Result'] == '⏳ 보유중']
    if holdings.empty:
        print("\n📋 보유 중인 종목이 없습니다.")
        return

    print(f"\n📋 현재 보유 종목 ({len(holdings)}건)")
    print(f"{'─' * 70}")
    print(f"  {'#':>3} | {'종목':<6} | {'매수가':>10} | {'수량':>5} | "
          f"{'손절가':>10} | {'매수일':^12}")
    print(f"{'─' * 70}")

    for _, h in holdings.iterrows():
        stop = f"${float(h['Stop_Price']):,.2f}" if h['Stop_Price'] != '' else '—'
        print(f"  {int(h['Trade_ID']):>3} | {h['Ticker']:<6} | "
              f"${float(h['Entry_Price']):>8,.2f} | {int(h['Shares']):>5} | "
              f"{stop:>10} | {h['Entry_Date']:^12}")

    print(f"{'─' * 70}")
    return holdings


# ============================================================================
# [유틸리티] 엑셀 파일 열기
# ============================================================================

def open_journal():
    """OS에 맞게 엑셀 파일을 엽니다."""
    if not os.path.exists(JOURNAL_FILE):
        print(f"⚠️ {JOURNAL_FILE}이 아직 생성되지 않았습니다.")
        return

    import platform
    system = platform.system()
    if system == 'Darwin':
        os.system(f'open "{JOURNAL_FILE}"')
    elif system == 'Windows':
        os.startfile(JOURNAL_FILE)
    else:
        os.system(f'xdg-open "{JOURNAL_FILE}"')

    print(f"📂 {JOURNAL_FILE} 열기 완료")


# ============================================================================
# [CLI] 명령줄 인터페이스
# ============================================================================

def main():
    if len(sys.argv) < 2:
        print("""
📓 trade_journal.py 사용법:

  add TICKER PRICE SHARES [메모]    매수 기록
  close TRADE_ID PRICE [사유]       매도 기록
  holdings                          보유 종목 조회
  log scan                          screener → predict → 기록
  log TICKER TICKER ...             지정 종목 정밀 분석 + 기록
  update                            AI 추천 사후 검증 (10일 후)
  stats                             월간 통계 출력
  open                              엑셀 파일 열기
        """)
        return

    command = sys.argv[1].lower()

    # --- 매수 기록 ---
    if command == 'add':
        if len(sys.argv) < 5:
            print("사용법: python trade_journal.py add IONQ 35.20 12 [메모]")
            return
        ticker = sys.argv[2]
        price = float(sys.argv[3])
        shares = int(sys.argv[4])
        reason = ' '.join(sys.argv[5:]) if len(sys.argv) > 5 else ''
        add_trade(ticker, price, shares, reason)

    # --- 매도 기록 ---
    elif command == 'close':
        if len(sys.argv) < 4:
            print("사용법: python trade_journal.py close 1 38.50 [익절/손절]")
            return
        trade_id = int(sys.argv[2])
        exit_price = float(sys.argv[3])
        reason = ' '.join(sys.argv[4:]) if len(sys.argv) > 4 else ''
        close_trade(trade_id, exit_price, reason)

    # --- 보유 종목 ---
    elif command == 'holdings':
        show_holdings()

    # --- AI 추천 기록 ---
    elif command == 'log':
        if len(sys.argv) < 3:
            print("사용법:")
            print("  python trade_journal.py log scan        → 풀 스캔 + 기록")
            print("  python trade_journal.py log IONQ PLTR   → 지정 종목 + 기록")
            return

        if sys.argv[2].lower() == 'scan':
            # screener → screener 강력매수 → predict 정밀 → 기록
            print("📡 screener(필터) → predict(정밀) → 기록\n")
            from screener import get_universe, filter_hot_stocks, ai_scanner
            from predict import Deep_Scan

            universe = get_universe()
            candidates = filter_hot_stocks(universe)
            if not candidates:
                print("⚠️ 1차 필터 통과 종목 없음.")
                return

            screener_picks = ai_scanner(candidates)
            if not screener_picks:
                print("⚠️ screener AI 통과 종목 없음.")
                return

            # 강력매수만 predict 정밀 분석
            strong = [p['Ticker'] for p in screener_picks if p['Prob'] >= config.AI_FILTER]
            if strong:
                print(f"\n🔥 강력매수 {len(strong)}개 → 정밀 분석...")
                full_results = Deep_Scan(strong)
                if full_results:
                    log_ai_recommendations(full_results)
                    return

            # 강력매수 없으면 screener 결과 전체 기록
            log_ai_recommendations(screener_picks)

        else:
            # 지정 종목 정밀 분석
            tickers = [t.upper() for t in sys.argv[2:]]
            from predict import Deep_Scan
            results = Deep_Scan(tickers)
            if results:
                log_ai_recommendations(results)

    # --- AI 검증 ---
    elif command == 'update':
        update_ai_results()

    # --- 통계 ---
    elif command == 'stats':
        generate_stats()

    # --- 엑셀 열기 ---
    elif command == 'open':
        open_journal()

    else:
        print(f"⚠️ 알 수 없는 명령: {command}")
        print("사용 가능: add, close, holdings, log, update, stats, open")


if __name__ == "__main__":
    main()