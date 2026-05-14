# ============================================================================
# korea_quant/screener/screener.py
# ============================================================================
# 역할: 현재 시점 기준 팩터 전략 부합 종목 추출
#
# 파이프라인:
#   1. get_universe()  → 당일 기준 Universe (시총/거래량/섹터 필터)
#   2. score_universe() → 팩터별 점수 계산
#   3. select_portfolio() → 상위 TOP_N 종목 선별
#   4. 콘솔 출력 + CSV 저장
#
# 출력 컬럼:
#   순위, 종목코드, 종목명, 섹터, 시가총액, 각 팩터 점수, 종합 점수, 추천 비중
# ============================================================================

import sys
import os
import logging
from datetime import datetime

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from configs import config
from universe.universe import get_universe
from scoring.scorer import score_universe, select_portfolio

logger = logging.getLogger(__name__)


# ============================================================================
# [핵심] 현재 시점 스크리닝
# ============================================================================

def run_screener(
    top_n: int | None = None,
    add_technicals: bool = True,
    save_csv: bool = True,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    현재 시점 기준 팩터 전략 상위 종목 추출.

    Args:
        top_n:           선별 종목 수 (None이면 config.TOP_N)
        add_technicals:  기술적 지표 계산 여부 (느리지만 정확도 향상)
        save_csv:        결과 CSV 저장 여부
        verbose:         진행 상황 출력

    Returns:
        DataFrame — 순위별 정렬된 종목 정보 + 팩터 점수 + 비중
    """
    top_n = top_n or config.TOP_N
    today = datetime.now().strftime('%Y-%m-%d')

    if verbose:
        print('=' * 65)
        print('  korea_quant 팩터 스크리너')
        print(f'  기준일: {today} | TOP {top_n}종목 | 리밸런싱: {config.REBALANCE_FREQ}')
        print('=' * 65)

    # -------------------------------------------------------------------------
    # [1] Universe 생성
    # -------------------------------------------------------------------------
    if verbose:
        print('\n[1] Universe 구성 중...')

    universe = get_universe(
        add_technicals=add_technicals,
        add_financials=True,
        use_cache=True,
        verbose=verbose,
    )

    if universe.empty:
        print('[FAIL] Universe 구성 실패')
        return pd.DataFrame()

    if verbose:
        print(f'  Universe 최종: {len(universe)}개 종목')

    # -------------------------------------------------------------------------
    # [2] 팩터 스코어링
    # -------------------------------------------------------------------------
    if verbose:
        print('\n[2] 팩터 스코어링 중...')

    scored = score_universe(universe, verbose=verbose)

    if 'score_total' not in scored.columns or scored['score_total'].isna().all():
        print('[WARNING] 팩터 점수 계산 실패 - DART API 키 확인 필요')
        print('  configs/config.py → DART_API_KEY 설정 후 재실행')

    # -------------------------------------------------------------------------
    # [3] 상위 종목 선별
    # -------------------------------------------------------------------------
    if verbose:
        print(f'\n[3] 상위 {top_n}종목 선별...')

    portfolio = _select_top_n(scored, top_n)

    if portfolio.empty:
        print('[WARNING] 선별된 종목 없음')
        return pd.DataFrame()

    # -------------------------------------------------------------------------
    # [4] 출력용 DataFrame 구성
    # -------------------------------------------------------------------------
    output = _build_output(portfolio, verbose=verbose)

    # -------------------------------------------------------------------------
    # [5] 콘솔 출력
    # -------------------------------------------------------------------------
    if verbose:
        _print_result(output, today)

    # -------------------------------------------------------------------------
    # [6] CSV 저장
    # -------------------------------------------------------------------------
    if save_csv:
        _save_result(output, today)

    return output


# ============================================================================
# [내부] top_n 적용 선별 (scorer.select_portfolio를 top_n 파라미터로 래핑)
# ============================================================================

def _select_top_n(scored_df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """score_total 기준 상위 top_n 종목 + 동일 비중."""
    df = scored_df.dropna(subset=['score_total']).copy()

    if df.empty or df['score_total'].sum() == 0:
        # 팩터 점수 없으면 MarketCap 기준 선별
        all_df = scored_df.dropna(subset=['MarketCap']).copy() if 'MarketCap' in scored_df.columns else scored_df.copy()
        df = all_df.nlargest(top_n, 'MarketCap') if 'MarketCap' in all_df.columns else all_df.head(top_n)
        df['score_total'] = 0.0
    else:
        df = df.nlargest(top_n, 'score_total')

    if config.WEIGHT_METHOD == 'score' and df['score_total'].sum() > 0:
        total_score = df['score_total'].sum()
        df['weight'] = df['score_total'] / total_score
    else:
        df['weight'] = 1.0 / len(df) if len(df) > 0 else 0.0

    return df


# ============================================================================
# [내부] 출력 DataFrame 구성
# ============================================================================

def _build_output(portfolio: pd.DataFrame, verbose: bool = False) -> pd.DataFrame:
    """선별 종목 DataFrame을 화면 출력/저장용으로 정리."""
    df = portfolio.copy()
    df = df.reset_index()
    df.index = range(1, len(df) + 1)
    df.index.name = 'Rank'

    # 시가총액 억 원 단위
    if 'MarketCap' in df.columns:
        df['MarketCap_억'] = (df['MarketCap'] / 1e8).round(0).astype(int)

    # 팩터 점수 컬럼 목록
    score_cols = [c for c in df.columns if c.startswith('score_')]

    # 최종 출력 컬럼 순서
    base_cols = ['Code', 'Name', 'Market']
    if 'Sector' in df.columns:
        base_cols.append('Sector')
    if 'MarketCap_억' in df.columns:
        base_cols.append('MarketCap_억')
    if 'Close' in df.columns:
        base_cols.append('Close')

    group_cols = ['score_value', 'score_growth', 'score_quality', 'score_technical']
    group_cols = [c for c in group_cols if c in df.columns]

    end_cols = ['score_total', 'weight']
    end_cols = [c for c in end_cols if c in df.columns]

    keep = [c for c in base_cols + group_cols + end_cols if c in df.columns]
    return df[keep]


# ============================================================================
# [내부] 콘솔 출력
# ============================================================================

def _print_result(output: pd.DataFrame, today: str):
    print('\n' + '=' * 80)
    print(f'  팩터 스크리닝 결과 ({today})')
    print('=' * 80)

    # 컬럼 헤더
    has_sector = 'Sector' in output.columns
    has_cap = 'MarketCap_억' in output.columns
    has_value = 'score_value' in output.columns
    has_growth = 'score_growth' in output.columns
    has_tech = 'score_technical' in output.columns

    header = f'  {"순위":>3}  {"코드":<7} {"종목명":<14}'
    if has_sector:
        header += f' {"섹터":<10}'
    if has_cap:
        header += f' {"시총(억)":>8}'
    if has_value:
        header += f' {"가치":>5}'
    if has_growth:
        header += f' {"성장":>5}'
    if has_tech:
        header += f' {"기술":>5}'
    header += f' {"종합":>6}  {"비중":>5}'
    print(header)
    print('  ' + '-' * 75)

    for rank, row in output.iterrows():
        code = str(row.get('Code', ''))
        name = str(row.get('Name', ''))[:13]
        line = f'  {rank:>3}  {code:<7} {name:<14}'

        if has_sector:
            sector = str(row.get('Sector', ''))[:9]
            line += f' {sector:<10}'
        if has_cap:
            cap = int(row.get('MarketCap_억', 0))
            line += f' {cap:>8,}'
        if has_value:
            line += f' {row.get("score_value", 0):>5.2f}'
        if has_growth:
            line += f' {row.get("score_growth", 0):>5.2f}'
        if has_tech:
            line += f' {row.get("score_technical", 0):>5.2f}'

        total = row.get('score_total', 0)
        weight = row.get('weight', 0)
        line += f' {total:>6.3f}  {weight:>4.1%}'
        print(line)

    if 'weight' in output.columns:
        print(f'\n  비중 합계: {output["weight"].sum():.1%}')

    print('=' * 80)

    # 데이터 소스 안내
    if 'score_total' not in output.columns or output.get('score_total', pd.Series()).mean() == 0:
        print()
        print('  [INFO] 현재 기술적 지표만 유효 - 재무 팩터는 DART API 키 필요')
        print('  [INFO] configs/config.py -> DART_API_KEY 설정 시 전체 팩터 사용 가능')


# ============================================================================
# [내부] CSV 저장
# ============================================================================

def _save_result(output: pd.DataFrame, today: str):
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    filename = f'screen_{today.replace("-", "")}.csv'
    path = os.path.join(config.REPORT_DIR, filename)

    try:
        output.to_csv(path, encoding='utf-8-sig')
        print(f'\n  [OK] 결과 저장: {path}')
    except Exception as e:
        logger.error('CSV 저장 실패: %s', e)


# ============================================================================
# [단독 실행] 스크리닝 실행
# ============================================================================

if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)

    import argparse
    parser = argparse.ArgumentParser(description='korea_quant 팩터 스크리너')
    parser.add_argument('--top', type=int, default=config.TOP_N, help=f'선별 종목 수 (기본: {config.TOP_N})')
    parser.add_argument('--no-tech', action='store_true', help='기술적 지표 제외 (빠름)')
    parser.add_argument('--no-save', action='store_true', help='CSV 저장 안 함')
    args = parser.parse_args()

    result = run_screener(
        top_n=args.top,
        add_technicals=not args.no_tech,
        save_csv=not args.no_save,
        verbose=True,
    )

    if not result.empty:
        print(f'\n[OK] 스크리닝 완료 - {len(result)}개 종목')
    else:
        print('\n[FAIL] 스크리닝 결과 없음')
