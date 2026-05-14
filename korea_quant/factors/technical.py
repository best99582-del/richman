# ============================================================================
# korea_quant/factors/technical.py
# ============================================================================
# 역할:
#   기술 지표 팩터 (가격/거래량 기반).
#   universe.py가 종목별 OHLCV 로드 → calc_indicators() 호출 →
#   결과값을 Universe DataFrame에 컬럼으로 부착.
#
# 구현 팩터 (3개):
#   RSIFactor         - RSI(14), rank_asc (낮은 RSI = 과매도 반등 기대)
#   MACDFactor        - MACD Histogram, rank_desc (모멘텀 강할수록 ↑)
#   VolumeRatioFactor - 당일 거래량 / 20일 평균 거래량, rank_desc
#
# calc_indicators(price_df) 추가 반환값 (현재 팩터 미사용, 향후 활용):
#   BB_Width    - 볼린저밴드 폭 (스퀴즈 후 확장 관점)
#   Above_MA20  - 종가 > MA20 여부 (1.0 / 0.0)
#
# 입력:
#   - calc_indicators(): 단일 종목 OHLCV DataFrame
#   - Factor.compute(): Universe DataFrame (RSI/MACD_Hist/Volume_Ratio 컬럼 필요)
# ============================================================================

import sys
import os
import logging

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from configs import config
from factors.factor_base import FactorBase

logger = logging.getLogger(__name__)

# ta 라이브러리 임포트
try:
    import ta
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False
    logger.warning('ta 라이브러리 미설치. pip install ta')


# ============================================================================
# [유틸] 단일 종목 OHLCV → 기술지표 계산
# ============================================================================

def calc_indicators(price_df: pd.DataFrame) -> dict:
    """
    단일 종목 OHLCV DataFrame → 최신 기술지표값 dict 반환.

    Args:
        price_df: 인덱스=날짜, 컬럼=Open/High/Low/Close/Volume

    Returns:
        dict — RSI, MACD_Hist, BB_Width, Above_MA20, Volume_Ratio
    """
    if price_df is None or len(price_df) < 30:
        return {}

    close = price_df['Close']
    high = price_df['High']
    low = price_df['Low']
    volume = price_df['Volume']

    result = {}

    if TA_AVAILABLE:
        # RSI(14)
        try:
            rsi = ta.momentum.RSIIndicator(close, window=14).rsi()
            result['RSI'] = rsi.iloc[-1]
        except Exception:
            result['RSI'] = np.nan

        # MACD Histogram
        try:
            macd = ta.trend.MACD(close)
            result['MACD_Hist'] = macd.macd_diff().iloc[-1]
        except Exception:
            result['MACD_Hist'] = np.nan

        # 볼린저밴드 폭
        try:
            bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
            bb_width = (bb.bollinger_hband() - bb.bollinger_lband()) / bb.bollinger_mavg() * 100
            result['BB_Width'] = bb_width.iloc[-1]
        except Exception:
            result['BB_Width'] = np.nan
    else:
        # ta 없으면 직접 계산
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        result['RSI'] = (100 - 100 / (1 + rs)).iloc[-1]
        result['MACD_Hist'] = np.nan
        result['BB_Width'] = np.nan

    # MA20 대비 위치
    ma20 = close.rolling(20).mean()
    result['Above_MA20'] = 1.0 if close.iloc[-1] > ma20.iloc[-1] else 0.0

    # 거래량 비율 (당일 / 20일 평균)
    avg_vol = volume.rolling(20).mean().iloc[-1]
    result['Volume_Ratio'] = float(volume.iloc[-1] / avg_vol) if avg_vol > 0 else 1.0

    return result


# ============================================================================
# [팩터] RSI — 낮을수록 과매도 반등 가능성 (higher_is_better=False)
# ============================================================================

class RSIFactor(FactorBase):
    """
    RSI(14). 낮을수록 과매도 구간 → 반등 기대.
    팩터 투자 관점: 모멘텀보다 역추세(mean-reversion) 활용.
    higher_is_better=False: 낮은 RSI → 고점수.
    """
    name = 'RSI'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        """
        df에 'RSI' 컬럼이 있으면 직접 사용.
        없으면 빈 Series 반환 (universe.py에서 price 로드 후 채워야 함).
        """
        if 'RSI' in df.columns:
            return pd.to_numeric(df['RSI'], errors='coerce').clip(0, 100)
        logger.warning('RSI: RSI 컬럼 없음. universe.py에서 기술지표 계산 필요.')
        return pd.Series(dtype=float)


# ============================================================================
# [팩터] MACD Histogram 모멘텀 — 높을수록 고점수
# ============================================================================

class MACDFactor(FactorBase):
    """MACD Histogram 양수 전환 모멘텀"""
    name = 'MACD_Hist'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'MACD_Hist' in df.columns:
            return pd.to_numeric(df['MACD_Hist'], errors='coerce')
        logger.warning('MACD_Hist: 컬럼 없음')
        return pd.Series(dtype=float)


# ============================================================================
# [팩터] 거래량 비율 — 높을수록 고점수 (관심 급증)
# ============================================================================

class VolumeRatioFactor(FactorBase):
    """거래량 / 20일 평균 거래량"""
    name = 'Volume_Ratio'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'Volume_Ratio' in df.columns:
            return pd.to_numeric(df['Volume_Ratio'], errors='coerce').clip(0, 10)
        logger.warning('Volume_Ratio: 컬럼 없음')
        return pd.Series(dtype=float)


# ============================================================================
# 팩터 레지스트리
# ============================================================================

ALL_TECHNICAL_FACTORS = [
    RSIFactor(),
    MACDFactor(),
    VolumeRatioFactor(),
]


# ============================================================================
# [단독 실행] 삼성전자 기술지표 계산 확인
# ============================================================================

if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from data.data_loader import get_price

    print('=' * 60)
    print('technical.py - 기술지표 계산 확인')
    print('=' * 60)

    test_tickers = [('005930', '삼성전자'), ('000660', 'SK하이닉스'), ('035420', 'NAVER')]

    print(f'\n{"코드":<8} {"종목명":<12} {"RSI":>6} {"MACD_H":>8} {"BB폭%":>7} {"MA20위":>6} {"거래량비":>8}')
    print('-' * 60)

    for code, name in test_tickers:
        df = get_price(code, '2024-01-01', '2024-12-31')
        if df.empty:
            print(f'  {code} {name}: 데이터 없음')
            continue

        ind = calc_indicators(df)
        rsi = ind.get('RSI', float('nan'))
        macd = ind.get('MACD_Hist', float('nan'))
        bbw = ind.get('BB_Width', float('nan'))
        ma20 = ind.get('Above_MA20', float('nan'))
        vr = ind.get('Volume_Ratio', float('nan'))

        print(f'  {code} {name:<12} {rsi:>6.1f} {macd:>8.4f} {bbw:>7.2f} {ma20:>6.0f} {vr:>8.2f}x')

    print(f'\n[OK] technical.py 확인 완료')
    print('=' * 60)
