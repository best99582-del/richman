# ============================================================================
# korea_quant/factors/factor_base.py
# ============================================================================
# 역할:
#   모든 팩터 클래스가 상속하는 추상 베이스.
#   팩터 추가 시 이 클래스를 상속하고 compute()만 구현하면 됨.
#   score() 는 베이스가 제공 → config.FACTORS[name]['scoring'] 기반 자동 분기.
#
# 팩터 추가 절차:
#   1) fundamental.py 또는 technical.py에 FactorBase 상속 클래스 작성
#   2) name 속성에 config.FACTORS 키와 동일한 문자열 설정
#   3) compute(df) → pd.Series 구현 (원시값 반환)
#   4) ALL_FUNDAMENTAL_FACTORS / ALL_TECHNICAL_FACTORS 리스트에 등록
#   5) config.FACTORS 딕셔너리에 weight + scoring 추가
#
# 스코어링 방식 (config.FACTORS[name]['scoring']):
#   'rank_asc'  : 낮은 원시값 → 높은 점수 (PER/PSR/POR 등 가치지표)
#   'rank_desc' : 높은 원시값 → 높은 점수 (ROE/성장률 등)
#   'zscore'    : 표준화 후 0~1 클리핑
#
# NaN 처리: 중앙값 대체 (해당 종목은 중간 점수 0.5 부근으로 평가됨).
# ============================================================================

from abc import ABC, abstractmethod
import numpy as np
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from configs import config


class FactorBase(ABC):
    """
    팩터 추상 베이스 클래스.

    상속 시 반드시 구현:
        name      : 팩터 이름 (config.FACTORS 키와 일치해야 함)
        compute() : Universe DataFrame -> 팩터 원시값 Series 반환

    score()는 config.FACTORS[name]['scoring'] 설정을 자동으로 읽어 적용.
    """

    name: str

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        """
        Args:
            df: Universe DataFrame (인덱스=Code)

        Returns:
            Series -- 인덱스: Code, 값: 팩터 원시값 (float)
        """

    def score(self, df: pd.DataFrame) -> pd.Series:
        """
        팩터 원시값 -> 0~1 정규화 점수.

        스코어링 방식은 config.FACTORS[self.name]['scoring'] 에서 읽음.
        해당 팩터가 config에 없으면 'rank_desc' 를 기본 적용.

        Returns:
            Series -- 인덱스: Code, 값: 0~1 점수
        """
        raw = self.compute(df)

        # NaN 처리: 중앙값 대체 (데이터 없는 종목은 중간 점수)
        median = raw.median()
        raw = raw.fillna(median)

        if raw.empty:
            return pd.Series(dtype=float)

        if raw.std() == 0:
            return pd.Series(0.5, index=raw.index)

        # 팩터별 스코어링 방식 읽기
        factor_cfg = config.FACTORS.get(self.name, {})
        method = factor_cfg.get('scoring', 'rank_desc')

        if method == 'rank_asc':
            # 낮은 원시값 = 높은 점수
            scored = 1.0 - raw.rank(pct=True)
        elif method == 'zscore':
            scored = (raw - raw.mean()) / raw.std()
            scored = (scored.clip(-3, 3) + 3) / 6
        else:
            # rank_desc (기본): 높은 원시값 = 높은 점수
            scored = raw.rank(pct=True)

        return scored.rename(self.name)
