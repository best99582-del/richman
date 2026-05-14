# ============================================================================
# korea_quant/factors/fundamental.py
# ============================================================================
# 역할: 재무 팩터 구현 (16개)
#
# [밸류에이션 배수] - rank_asc (낮을수록 좋음)
#   PER_TTM    : 시가총액 / TTM 순이익
#   PBR_Q      : 시가총액 / 분기말 자기자본
#   PSR_TTM    : 시가총액 / TTM 매출액
#   POR_TTM    : 시가총액 / TTM 영업이익
#   PCR_TTM    : 시가총액 / TTM 영업현금흐름
#   PGPR_TTM   : 시가총액 / TTM 매출총이익
#
# [성장률] - rank_desc (높을수록 좋음). 분기 YoY 누적 기준.
#   SALES_GROWTH_Q : (Q_cur 매출 - Q_prev 매출) / |Q_prev 매출|
#   GP_GROWTH_Q    : 매출총이익 YoY
#   OP_GROWTH_Q    : 영업이익 YoY
#   NET_GROWTH_Q   : 순이익 YoY
#
# [수익성] - rank_desc (높을수록 좋음)
#   ROE_Q          : TTM 순이익 / 분기말 자기자본
#   ROA_Q          : TTM 순이익 / 분기말 총자산
#   OP_MARGIN_TTM  : TTM 영업이익 / TTM 매출액
#
# [원시값 사이즈] - rank_desc (큰 기업 우선) 또는 rank_asc (작은 기업 우선)
#   SALES_TTM      : TTM 매출액
#   OP_PROFIT_TTM  : TTM 영업이익
#   NET_PROFIT_TTM : TTM 순이익
#
# 적자/음수 종목 처리: 본 모듈에서는 그대로 계산해서 반환.
# 적자 필터링은 config.ENTRY_CONDITIONS 에서 사용자가 직접 설정.
#
# 입력 DataFrame 필수 컬럼 (universe.py가 자동 부착):
#   MarketCap, sales, sales_ttm, sales_prev, sales_cur,
#   op_profit, op_profit_ttm, op_profit_prev, op_profit_cur,
#   net_profit, net_profit_ttm, net_profit_prev,
#   gross_profit, gross_profit_ttm, gross_profit_prev, gross_profit_cur,
#   operating_cf, operating_cf_ttm,
#   equity, total_assets
# 필수 컬럼 없으면 빈 Series 반환 → scorer가 자동 스킵.
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


def _ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """안전한 비율 계산. 분모 0/NaN은 NaN으로."""
    num = pd.to_numeric(numerator, errors='coerce')
    den = pd.to_numeric(denominator, errors='coerce').replace(0, np.nan)
    return num / den


# ============================================================================
# [밸류에이션 배수 팩터]
# ============================================================================

class PER_TTM_Factor(FactorBase):
    """PER_TTM = 시가총액 / TTM 순이익"""
    name = 'PER_TTM'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'MarketCap' not in df.columns or 'net_profit_ttm' not in df.columns:
            return pd.Series(dtype=float)
        return _ratio(df['MarketCap'], df['net_profit_ttm'])


class PBR_Q_Factor(FactorBase):
    """PBR_Q = 시가총액 / 분기말 자기자본"""
    name = 'PBR_Q'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'MarketCap' not in df.columns or 'equity' not in df.columns:
            return pd.Series(dtype=float)
        return _ratio(df['MarketCap'], df['equity'])


class PSR_TTM_Factor(FactorBase):
    """PSR_TTM = 시가총액 / TTM 매출액"""
    name = 'PSR_TTM'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'MarketCap' not in df.columns or 'sales_ttm' not in df.columns:
            return pd.Series(dtype=float)
        return _ratio(df['MarketCap'], df['sales_ttm'])


class POR_TTM_Factor(FactorBase):
    """POR_TTM = 시가총액 / TTM 영업이익"""
    name = 'POR_TTM'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'MarketCap' not in df.columns or 'op_profit_ttm' not in df.columns:
            return pd.Series(dtype=float)
        return _ratio(df['MarketCap'], df['op_profit_ttm'])


class PCR_TTM_Factor(FactorBase):
    """PCR_TTM = 시가총액 / TTM 영업현금흐름"""
    name = 'PCR_TTM'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'MarketCap' not in df.columns or 'operating_cf_ttm' not in df.columns:
            return pd.Series(dtype=float)
        return _ratio(df['MarketCap'], df['operating_cf_ttm'])


class PGPR_TTM_Factor(FactorBase):
    """PGPR_TTM = 시가총액 / TTM 매출총이익"""
    name = 'PGPR_TTM'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'MarketCap' not in df.columns or 'gross_profit_ttm' not in df.columns:
            return pd.Series(dtype=float)
        return _ratio(df['MarketCap'], df['gross_profit_ttm'])


# ============================================================================
# [성장률 팩터] - 분기 YoY (당기 분기 누적 vs 전년 동기 분기 누적)
# ============================================================================

def _yoy(cur: pd.Series, prev: pd.Series) -> pd.Series:
    """YoY 성장률 = (cur - prev) / |prev|. 분모 0이면 NaN."""
    cur = pd.to_numeric(cur, errors='coerce')
    prev = pd.to_numeric(prev, errors='coerce')
    den = prev.abs().replace(0, np.nan)
    growth = (cur - prev) / den
    return growth.clip(-1.0, 5.0)  # -100% ~ +500% 클리핑


class SalesGrowthQFactor(FactorBase):
    name = 'SALES_GROWTH_Q'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'sales_cur' not in df.columns or 'sales_prev' not in df.columns:
            return pd.Series(dtype=float)
        return _yoy(df['sales_cur'], df['sales_prev'])


class GPGrowthQFactor(FactorBase):
    name = 'GP_GROWTH_Q'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'gross_profit_cur' not in df.columns or 'gross_profit_prev' not in df.columns:
            return pd.Series(dtype=float)
        return _yoy(df['gross_profit_cur'], df['gross_profit_prev'])


class OpGrowthQFactor(FactorBase):
    name = 'OP_GROWTH_Q'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'op_profit_cur' not in df.columns or 'op_profit_prev' not in df.columns:
            return pd.Series(dtype=float)
        return _yoy(df['op_profit_cur'], df['op_profit_prev'])


class NetGrowthQFactor(FactorBase):
    name = 'NET_GROWTH_Q'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'net_profit' not in df.columns or 'net_profit_prev' not in df.columns:
            return pd.Series(dtype=float)
        return _yoy(df['net_profit'], df['net_profit_prev'])


# ============================================================================
# [수익성 팩터]
# ============================================================================

class ROE_Q_Factor(FactorBase):
    """ROE_Q = TTM 순이익 / 분기말 자기자본"""
    name = 'ROE_Q'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'net_profit_ttm' not in df.columns or 'equity' not in df.columns:
            return pd.Series(dtype=float)
        roe = _ratio(df['net_profit_ttm'], df['equity'])
        return roe.clip(-1.0, 2.0)


class ROA_Q_Factor(FactorBase):
    """ROA_Q = TTM 순이익 / 분기말 총자산"""
    name = 'ROA_Q'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'net_profit_ttm' not in df.columns or 'total_assets' not in df.columns:
            return pd.Series(dtype=float)
        roa = _ratio(df['net_profit_ttm'], df['total_assets'])
        return roa.clip(-0.5, 0.5)


class OpMarginTTMFactor(FactorBase):
    """OP_MARGIN_TTM = TTM 영업이익 / TTM 매출액"""
    name = 'OP_MARGIN_TTM'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'op_profit_ttm' not in df.columns or 'sales_ttm' not in df.columns:
            return pd.Series(dtype=float)
        margin = _ratio(df['op_profit_ttm'], df['sales_ttm'])
        return margin.clip(-1.0, 1.0)


# ============================================================================
# [원시값 사이즈 팩터]
# ============================================================================

class SalesTTMFactor(FactorBase):
    name = 'SALES_TTM'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'sales_ttm' not in df.columns:
            return pd.Series(dtype=float)
        return pd.to_numeric(df['sales_ttm'], errors='coerce')


class OpProfitTTMFactor(FactorBase):
    name = 'OP_PROFIT_TTM'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'op_profit_ttm' not in df.columns:
            return pd.Series(dtype=float)
        return pd.to_numeric(df['op_profit_ttm'], errors='coerce')


class NetProfitTTMFactor(FactorBase):
    name = 'NET_PROFIT_TTM'

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if 'net_profit_ttm' not in df.columns:
            return pd.Series(dtype=float)
        return pd.to_numeric(df['net_profit_ttm'], errors='coerce')


# ============================================================================
# 팩터 레지스트리 (scorer.py 에서 일괄 로드)
# ============================================================================

ALL_FUNDAMENTAL_FACTORS = [
    # 밸류에이션 배수
    PER_TTM_Factor(),
    PBR_Q_Factor(),
    PSR_TTM_Factor(),
    POR_TTM_Factor(),
    PCR_TTM_Factor(),
    PGPR_TTM_Factor(),
    # 성장률
    SalesGrowthQFactor(),
    GPGrowthQFactor(),
    OpGrowthQFactor(),
    NetGrowthQFactor(),
    # 수익성
    ROE_Q_Factor(),
    ROA_Q_Factor(),
    OpMarginTTMFactor(),
    # 원시값
    SalesTTMFactor(),
    OpProfitTTMFactor(),
    NetProfitTTMFactor(),
]


# ============================================================================
# [단독 실행] 팩터 클래스 로딩 확인
# ============================================================================

if __name__ == '__main__':
    print('=' * 60)
    print('fundamental.py - 등록된 팩터 클래스')
    print('=' * 60)
    print(f'  총 {len(ALL_FUNDAMENTAL_FACTORS)}개 팩터')
    print(f'  {"팩터명":<20} {"클래스명"}')
    print('  ' + '-' * 50)
    for f in ALL_FUNDAMENTAL_FACTORS:
        cfg = config.FACTORS.get(f.name)
        status = f' (w={cfg["weight"]}, {cfg["scoring"]})' if cfg else ' [inactive]'
        print(f'  {f.name:<20} {f.__class__.__name__}{status}')
    print('=' * 60)
