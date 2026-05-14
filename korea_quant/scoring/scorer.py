# ============================================================================
# korea_quant/scoring/scorer.py
# ============================================================================
# 역할:
#   Universe DataFrame을 받아 팩터별 점수 + 그룹별 합산 + 종합 점수 산출,
#   그리고 종합 점수 기준 상위 TOP_N 종목 선별 + 비중 계산.
#
# 처리 흐름 (score_universe):
#   [0] 진입 조건식 필터 - config.ENTRY_CONDITIONS + ENTRY_LOGIC
#                          (스코어링 전 1차 컷, AND/OR/괄호 논리식 지원)
#   [1] 팩터별 점수      - 각 Factor 클래스 .score() 호출 (factor_base.py)
#                          → score_{팩터명} 컬럼으로 부착
#   [2] 그룹별 합산      - 가치/성장/수익성/기술 그룹별 점수 합산
#                          → score_value, score_growth, score_quality, score_technical
#   [3] 가중 합산        - config.FACTORS 가중치 적용 → score_total
#
# 처리 흐름 (select_portfolio):
#   - score_total 기준 상위 TOP_N 추출 (SORT_ORDER 따라 desc/asc)
#   - WEIGHT_METHOD에 따라 비중 계산 (equal / score / atr)
#
# 스코어링 방식 (config.FACTORS 에서 팩터별로 개별 설정):
#   'rank_asc'  - 낮은 값 = 높은 점수 (PSR, POR, PBR, RSI 등)
#   'rank_desc' - 높은 값 = 높은 점수 (ROE, 성장률 등)
#   'zscore'    - 표준화 후 0~1 클리핑
# ============================================================================

import sys
import os
import logging

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from configs import config
from factors.fundamental import ALL_FUNDAMENTAL_FACTORS
from factors.technical import ALL_TECHNICAL_FACTORS

logger = logging.getLogger(__name__)


# ============================================================================
# [내부] 진입 조건식 필터
# ============================================================================

_OPS = {
    '>=': lambda s, v: s >= v,
    '<=': lambda s, v: s <= v,
    '>':  lambda s, v: s > v,
    '<':  lambda s, v: s < v,
    '==': lambda s, v: s == v,
}


def _get_factor_raw(df: pd.DataFrame, factor_name: str) -> pd.Series:
    """
    Universe DataFrame에서 팩터 원시값 Series를 가져온다.
    컬럼 직접 참조를 우선, 없으면 팩터 클래스 compute() 사용.
    """
    # 컬럼 직접 참조 우선 (이미 Universe에 부착된 값)
    if factor_name in df.columns:
        return pd.to_numeric(df[factor_name], errors='coerce')
    # 없으면 팩터 클래스 compute() 호출
    all_factors = ALL_FUNDAMENTAL_FACTORS + ALL_TECHNICAL_FACTORS
    for f in all_factors:
        if f.name == factor_name:
            try:
                result = f.compute(df)
                if not result.empty:
                    return result
            except Exception:
                pass
            break
    return pd.Series(dtype=float)


def apply_entry_conditions(df: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    """
    config.ENTRY_CONDITIONS + config.ENTRY_LOGIC 기반으로 종목 필터링.

    각 조건식은 팩터 원시값(compute() 결과)을 기준으로 평가.
    NaN 종목은 해당 조건에서 False 처리 (보수적 필터).

    Returns:
        조건을 통과한 종목만 남긴 DataFrame
    """
    conditions = config.ENTRY_CONDITIONS
    if not conditions:
        return df

    n_before = len(df)
    cond_masks = {}

    for cond in conditions:
        cid    = cond['id']
        fname  = cond['factor']
        op     = cond['op']
        val    = cond['value']

        raw = _get_factor_raw(df, fname)
        if raw.empty:
            # 팩터 데이터 없으면 해당 조건은 전체 True (조건 무시)
            if verbose:
                print(f'  [조건 {cid}] {fname} {op} {val} -> 데이터 없음, 조건 무시')
            cond_masks[cid] = pd.Series(True, index=df.index)
            continue

        raw = raw.reindex(df.index)
        op_fn = _OPS.get(op)
        if op_fn is None:
            raise ValueError(f'지원하지 않는 연산자: {op}')

        mask = op_fn(raw, val).fillna(False)
        cond_masks[cid] = mask

        if verbose:
            passed = mask.sum()
            print(f'  [조건 {cid}] {fname} {op} {val} -> {passed}/{len(df)}개 통과')

    # 논리 조건식 평가
    logic = config.ENTRY_LOGIC.strip()
    if not logic:
        # 빈 문자열이면 전체 AND
        final_mask = pd.Series(True, index=df.index)
        for mask in cond_masks.values():
            final_mask = final_mask & mask
    else:
        # ENTRY_LOGIC 문자열을 파이썬 표현식으로 변환 후 eval
        import re
        expr = logic
        # AND/OR 를 먼저 치환 (단어 경계 기준)
        expr = re.sub(r'\bAND\b', '&', expr)
        expr = re.sub(r'\bOR\b',  '|', expr)
        # 조건 ID (A, B, C...) 를 cond_masks 참조로 치환 (단어 경계 기준)
        for cid in sorted(cond_masks.keys(), key=len, reverse=True):
            expr = re.sub(r'\b' + re.escape(cid) + r'\b', f'cond_masks["{cid}"]', expr)
        final_mask = eval(expr)  # noqa: S307

    result = df[final_mask]
    n_after = len(result)

    if verbose:
        logic_display = logic if logic else 'ALL AND'
        print(f'  [진입 조건 결과] 논리: {logic_display} | {n_before} -> {n_after}개 종목')

    return result


# ============================================================================
# [핵심] 종합 팩터 스코어링
# ============================================================================

def score_universe(universe: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    """
    Universe DataFrame -> 팩터별 점수 + 종합 점수 추가하여 반환.

    Args:
        universe: get_universe() 반환 DataFrame (인덱스=Code)
        verbose:  팩터별 유효 종목 수 출력

    Returns:
        원본 universe에 아래 컬럼 추가된 DataFrame:
        - score_{팩터명} : 각 팩터 0~1 점수
        - score_value    : 가치 그룹 합산
        - score_growth   : 성장 그룹 합산
        - score_quality  : 퀄리티 그룹 합산
        - score_technical: 기술 그룹 합산
        - score_total    : 최종 가중 합산 점수 (0~1)
    """
    df = universe.copy()
    all_factors = ALL_FUNDAMENTAL_FACTORS + ALL_TECHNICAL_FACTORS

    # -------------------------------------------------------------------------
    # [0] 진입 조건식 필터 (스코어링 전 1차 컷)
    # -------------------------------------------------------------------------
    if config.ENTRY_CONDITIONS:
        if verbose:
            print('\n  [진입 조건 필터]')
        df = apply_entry_conditions(df, verbose=verbose)
        if df.empty:
            if verbose:
                print('  [WARNING] 조건 필터 후 남은 종목 없음')
            return universe.copy()  # 원본 반환 (score 컬럼 없음)

    # -------------------------------------------------------------------------
    # [1] 팩터별 점수 계산
    # -------------------------------------------------------------------------
    factor_scores = {}
    for factor in all_factors:
        if factor.name not in config.FACTORS:
            continue
        try:
            scores = factor.score(df)
            valid = scores.notna().sum()
            if valid == 0:
                if verbose:
                    print(f'  [{factor.name}] 유효 데이터 없음 - 스킵')
                continue
            factor_scores[factor.name] = scores
            df[f'score_{factor.name}'] = scores
            if verbose:
                method = config.FACTORS[factor.name].get('scoring', 'rank_desc')
                print(f'  [{factor.name}] {method} | 유효 {valid}개 | 평균 {scores.mean():.3f}')
        except Exception as e:
            logger.warning('팩터 스코어 계산 실패 (%s): %s', factor.name, e)

    # -------------------------------------------------------------------------
    # [2] 그룹별 합산
    # -------------------------------------------------------------------------
    VALUE_FACTORS   = ['PSR_TTM', 'POR_TTM', 'PBR_Q', 'PER_TTM', 'PCR_TTM', 'PGPR_TTM']
    GROWTH_FACTORS  = ['SALES_GROWTH_Q', 'OP_GROWTH_Q', 'GP_GROWTH_Q', 'NET_GROWTH_Q']
    QUALITY_FACTORS = ['ROE_Q', 'ROA_Q', 'OP_MARGIN_TTM']
    TECH_FACTORS    = ['RSI', 'MACD_Hist', 'Volume_Ratio']

    df['score_value']     = _group_sum(factor_scores, VALUE_FACTORS)
    df['score_growth']    = _group_sum(factor_scores, GROWTH_FACTORS)
    df['score_quality']   = _group_sum(factor_scores, QUALITY_FACTORS)
    df['score_technical'] = _group_sum(factor_scores, TECH_FACTORS)

    # -------------------------------------------------------------------------
    # [3] 가중 합산 -> 최종 점수
    # -------------------------------------------------------------------------
    total = pd.Series(0.0, index=df.index)
    weight_used = 0.0

    for fname, cfg in config.FACTORS.items():
        if fname in factor_scores:
            total += factor_scores[fname] * cfg['weight']
            weight_used += cfg['weight']

    if weight_used > 0:
        total = total / weight_used

    df['score_total'] = total

    if verbose:
        available = len(factor_scores)
        total_defined = len(config.FACTORS)
        print(f'\n  사용된 팩터: {available}/{total_defined}개 (가중치 합계: {weight_used:.2f})')
        print(f'  정렬 방향: {config.SORT_ORDER}')

    return df


# ============================================================================
# [내부] 그룹 내 팩터 점수 합산
# ============================================================================

def _group_sum(factor_scores: dict, names: list) -> pd.Series:
    """해당 그룹의 팩터 점수를 합산. 없는 팩터는 무시."""
    result = None
    for name in names:
        if name in factor_scores:
            if result is None:
                result = factor_scores[name].copy()
            else:
                result = result.add(factor_scores[name], fill_value=0)
    if result is None:
        return pd.Series(dtype=float)
    return result


# ============================================================================
# [내부] ATR 계산
# ============================================================================

def _calc_atr(codes: list, as_of_date: str) -> pd.Series:
    """
    종목 리스트의 ATR(평균 진폭) 을 계산하여 Series로 반환.
    ATR = 최근 config.ATR_PERIOD 일간 True Range 의 평균.

    Returns:
        Series -- 인덱스: Code, 값: ATR (가격 기준 절대값)
        계산 실패 종목은 NaN.
    """
    from data.data_loader import get_price
    from datetime import timedelta

    end = as_of_date or pd.Timestamp.today().strftime('%Y-%m-%d')
    start = (pd.Timestamp(end) - timedelta(days=config.ATR_PRICE_DAYS)).strftime('%Y-%m-%d')

    atr_values = {}
    for code in codes:
        try:
            price = get_price(code, start, end, use_cache=True)
            if price is None or len(price) < config.ATR_PERIOD:
                atr_values[code] = np.nan
                continue
            high  = price['High']
            low   = price['Low']
            close = price['Close'].shift(1)
            tr = pd.concat([
                high - low,
                (high - close).abs(),
                (low  - close).abs(),
            ], axis=1).max(axis=1)
            atr_values[code] = tr.rolling(config.ATR_PERIOD).mean().iloc[-1]
        except Exception:
            atr_values[code] = np.nan

    return pd.Series(atr_values)


def _atr_weight(df: pd.DataFrame, as_of_date: str = None) -> pd.Series:
    """
    ATR 역비례 비중 계산.
    변동성 낮은 종목 = 높은 비중.
    단일 종목 비중 상한: config.ATR_MAX_WEIGHT.

    Returns:
        Series -- 인덱스: Code, 값: 비중 (합계=1.0)
    """
    atr = _calc_atr(list(df.index), as_of_date)
    atr = atr.reindex(df.index)

    # ATR을 Close 가격으로 나눠 상대 변동성으로 정규화
    if 'Close' in df.columns:
        close = pd.to_numeric(df['Close'], errors='coerce')
        rel_atr = atr / close.replace(0, np.nan)
    else:
        rel_atr = atr

    # 계산 실패 종목은 중앙값으로 대체
    rel_atr = rel_atr.fillna(rel_atr.median())

    if rel_atr.sum() == 0 or rel_atr.isna().all():
        return pd.Series(1.0 / len(df), index=df.index)

    # 역비례 비중 (변동성 낮을수록 비중 높음)
    inv_atr = 1.0 / rel_atr.replace(0, np.nan)
    inv_atr = inv_atr.fillna(inv_atr.median())
    weights = inv_atr / inv_atr.sum()

    # 상한 클리핑 후 재정규화
    max_w = config.ATR_MAX_WEIGHT
    clipped = weights.clip(upper=max_w)
    # 상한 초과분을 나머지 종목에 비례 재배분 (2회 반복으로 수렴)
    for _ in range(2):
        excess = (clipped - max_w).clip(lower=0).sum()
        if excess < 1e-6:
            break
        clipped = clipped.clip(upper=max_w)
        below_mask = clipped < max_w
        if below_mask.sum() == 0:
            break
        clipped[below_mask] += excess * (clipped[below_mask] / clipped[below_mask].sum())
        clipped = clipped.clip(upper=max_w)

    return clipped / clipped.sum()


# ============================================================================
# [포트폴리오 선별] 상위 N종목 + 비중 계산
# ============================================================================

def select_portfolio(scored_df: pd.DataFrame, as_of_date: str = None) -> pd.DataFrame:
    """
    score_total 기준 상위 TOP_N 종목 선별 + 비중 배분.
    정렬 방향은 config.SORT_ORDER ('desc' / 'asc') 를 따름.
    비중 방식은 config.WEIGHT_METHOD ('equal' / 'score' / 'atr') 를 따름.

    Args:
        scored_df:   score_universe() 반환 DataFrame
        as_of_date:  ATR 계산 기준일 (None 이면 오늘)

    Returns:
        DataFrame -- 상위 TOP_N 종목 (weight 컬럼 추가)
    """
    df = scored_df.dropna(subset=['score_total']).copy()

    ascending = (config.SORT_ORDER == 'asc')
    if ascending:
        df = df.nsmallest(config.TOP_N, 'score_total')
    else:
        df = df.nlargest(config.TOP_N, 'score_total')

    if config.WEIGHT_METHOD == 'score':
        total_score = df['score_total'].sum()
        df['weight'] = df['score_total'] / total_score if total_score > 0 else 1.0 / len(df)
    elif config.WEIGHT_METHOD == 'atr':
        df['weight'] = _atr_weight(df, as_of_date)
    else:
        # equal (기본)
        df['weight'] = 1.0 / len(df)

    return df


# ============================================================================
# [단독 실행] Universe 스코어링 확인
# ============================================================================

if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from universe.universe import get_universe

    print('=' * 60)
    print('scorer.py - 팩터 스코어링 확인')
    print('=' * 60)

    print('\n[1] Universe 로드...')
    universe = get_universe(add_technicals=True, use_cache=True, verbose=False)
    print(f'  Universe: {len(universe)}개 종목')

    print('\n[2] 팩터 스코어링...')
    scored = score_universe(universe, verbose=True)

    print('\n[3] 종합 스코어 상위 20종목:')
    portfolio = select_portfolio(scored)

    print(f'\n  {"순위":>3} {"코드":<8} {"종목명":<15} {"종합점수":>8} {"가치":>6} {"성장":>6} {"기술":>6} {"비중":>6}')
    print('  ' + '-' * 65)

    for rank, (code, row) in enumerate(portfolio.iterrows(), 1):
        name = str(row.get('Name', ''))[:14]
        total = row.get('score_total', 0)
        val = row.get('score_value', 0)
        grow = row.get('score_growth', 0)
        tech = row.get('score_technical', 0)
        weight = row.get('weight', 0)
        print(f'  {rank:>3} {code:<8} {name:<15} {total:>8.3f} {val:>6.2f} {grow:>6.2f} {tech:>6.2f} {weight:>5.1%}')

    print(f'\n  비중 합계: {portfolio["weight"].sum():.1%}')
    print(f'\n[OK] scorer.py 확인 완료')
    print('=' * 60)
