# ============================================================================
# 🔬 test_signal_grid.py — AI_FORECAST_PERIOD × AI_TARGET_PCT 그리드 캘리브레이션
# ============================================================================
# 목적: (보유기간, 목표수익률) 조합별 순수 신호 품질을 비교하여
#       AI 학습 라벨 정의를 종목 특성에 맞게 재캘리브레이션.
#
# 측정 지표 (셀당):
#   - CV_Precision (5-Fold 평균)
#   - Positive_Rate (학습 라벨 y=1 비율, %)
#   - Signal_Count (CV 누적 매수신호 수)
#
# 백테스트 시뮬레이션 없음 — 순수 분류 메트릭만.
# ============================================================================

import json
import os
import sys

import numpy as np

import config
from data_loader import load_ohlcv
from indicators import Make_Indicators
from predict import cv_precision, Create_Windowed_Data

# Windows cp949 콘솔 한글/유니코드 대응
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

TEST_TICKERS = config.TEST_TICKERS
FORECAST_PERIODS = [3, 5, 7, 10, 14]   # 일
TARGET_PCTS = [5, 7, 10, 15, 20]       # %

CURRENT_FP = config.AI_FORECAST_PERIOD
CURRENT_TP = config.AI_TARGET_PCT

OUTPUT_TXT = "results/signal_grid_results.txt"
OUTPUT_JSON = "results/signal_grid_results.json"


# ============================================================================
# [공통] Tee — 콘솔 + 파일 동시 출력
# ============================================================================

class Tee:
    def __init__(self, *files):
        self.files = files

    def write(self, s):
        for f in self.files:
            f.write(s)

    def flush(self):
        for f in self.files:
            f.flush()


# ============================================================================
# [공통] 데이터 전처리 (지표 산출까지만, AI 라벨은 셀별로 다시 만듦)
# ============================================================================

def _prepare_all() -> dict:
    print("⏳ 데이터 전처리 중 (지표 산출)...")
    stock_data = {}
    for ticker in TEST_TICKERS:
        try:
            df = load_ohlcv(ticker, start=config.START_DATE, drop_intraday=True)
            df = Make_Indicators(df)
            df = df.dropna()
            stock_data[ticker] = df
            print(f"  ✅ {ticker}: {len(df)}일")
        except Exception as e:
            print(f"  ⚠️ {ticker} 실패: {e}")
    return stock_data


# ============================================================================
# [핵심] 단일 종목 그리드 측정
# ============================================================================

def grid_per_ticker(ticker: str, df) -> dict:
    """단일 종목에 대해 (FP, TP) 그리드의 측정값 dict 반환.

    Returns:
        dict: { (fp, tp): {'precision': float, 'pos_rate': float, 'signals': int} }
    """
    result = {}
    for fp in FORECAST_PERIODS:
        for tp in TARGET_PCTS:
            try:
                # 양성비 계산 (cv_precision 내부와 동일한 윈도잉)
                _, y = Create_Windowed_Data(
                    df, config.AI_FEATURES, config.AI_WINDOW_SIZE, tp, fp
                )
                pos_rate = float(np.mean(y) * 100) if len(y) > 0 else 0.0

                # CV 정밀도
                prec, sigs = cv_precision(
                    df,
                    features=config.AI_FEATURES,
                    window=config.AI_WINDOW_SIZE,
                    target_pct=tp,
                    forecast_period=fp,
                )
                result[(fp, tp)] = {
                    'precision': float(prec),
                    'pos_rate': pos_rate,
                    'signals': int(sigs),
                }
            except Exception as e:
                result[(fp, tp)] = {
                    'precision': 0.0,
                    'pos_rate': 0.0,
                    'signals': 0,
                    'error': str(e),
                }
    return result


# ============================================================================
# [집계] 종목별 그리드 → 5종목 평균 그리드
# ============================================================================

def aggregate(per_ticker: dict) -> dict:
    """{ticker: grid} → {(fp,tp): {'precision','pos_rate','signals'} 평균}"""
    avg = {}
    for fp in FORECAST_PERIODS:
        for tp in TARGET_PCTS:
            precs, rates, sigs = [], [], []
            for grid in per_ticker.values():
                cell = grid.get((fp, tp), {})
                if cell.get('error'):
                    continue
                precs.append(cell['precision'])
                rates.append(cell['pos_rate'])
                sigs.append(cell['signals'])
            avg[(fp, tp)] = {
                'precision': float(np.mean(precs)) if precs else 0.0,
                'pos_rate': float(np.mean(rates)) if rates else 0.0,
                'signals': float(np.mean(sigs)) if sigs else 0.0,
            }
    return avg


# ============================================================================
# [출력] 그리드 표 + 판정
# ============================================================================

def _verdict(cell: dict) -> str:
    p, r = cell['precision'], cell['pos_rate']
    if r < 5:
        return "❌희귀"
    if r > 55:
        return "❌변별X"
    if 15 <= r <= 45 and p >= 0.55:
        return "✅우수"
    if p < 0.50:
        return "❌부진"
    return "⚠️보통"


def print_grid(title: str, grid: dict):
    print(f"\n{'=' * 96}")
    print(f"  {title}")
    print(f"  현재 운용값: FP={CURRENT_FP}일 / TP={CURRENT_TP}%  ◀")
    print('=' * 96)

    # 헤더: TARGET_PCT 열
    print(f"\n  {'FP \\ TP':>8} |", end='')
    for tp in TARGET_PCTS:
        print(f" {str(tp) + '%':>16} |", end='')
    print()
    print(f"  {'─' * 92}")

    for fp in FORECAST_PERIODS:
        # row 1: precision | pos_rate | signals
        print(f"  {str(fp) + '일':>8} |", end='')
        for tp in TARGET_PCTS:
            cell = grid.get((fp, tp), {})
            p = cell.get('precision', 0)
            r = cell.get('pos_rate', 0)
            s = cell.get('signals', 0)
            marker = "◀" if (fp == CURRENT_FP and tp == CURRENT_TP) else " "
            txt = f"P{p:.2f} R{r:>4.0f}% S{int(s):>3}{marker}"
            print(f" {txt:>16} |", end='')
        print()
        # row 2: 판정
        print(f"  {'':>8} |", end='')
        for tp in TARGET_PCTS:
            cell = grid.get((fp, tp), {})
            v = _verdict(cell) if 'precision' in cell else ''
            print(f" {v:>16} |", end='')
        print()
        print(f"  {'─' * 92}")


def find_top_cells(grid: dict, n: int = 5) -> list:
    """양성비 5~55% 범위에서 정밀도 상위 N개 셀"""
    candidates = []
    for (fp, tp), cell in grid.items():
        if 5 <= cell['pos_rate'] <= 55 and cell['signals'] > 0:
            candidates.append((cell['precision'], fp, tp, cell))
    candidates.sort(reverse=True, key=lambda x: x[0])
    return candidates[:n]


# ============================================================================
# [실행]
# ============================================================================

def main():
    os.makedirs('results', exist_ok=True)
    log_f = open(OUTPUT_TXT, 'w', encoding='utf-8')
    sys.stdout = Tee(sys.__stdout__, log_f)

    print("🔬 [Richman] AI_FORECAST_PERIOD × AI_TARGET_PCT 그리드 캘리브레이션")
    print(f"  대상: {TEST_TICKERS}")
    print(f"  피처: {config.AI_FEATURES}")
    print(f"  그리드: FP={FORECAST_PERIODS} × TP={TARGET_PCTS} (={len(FORECAST_PERIODS) * len(TARGET_PCTS)}셀 × {len(TEST_TICKERS)}종목)")
    print(f"  측정: CV_Precision(5-Fold) + Positive_Rate + Signal_Count")

    stock_data = _prepare_all()
    if not stock_data:
        print("⚠️ 데이터 없음 — 종료")
        return

    # --- 종목별 그리드 ---
    per_ticker = {}
    import time
    start = time.time()
    for i, (ticker, df) in enumerate(stock_data.items(), 1):
        elapsed = time.time() - start
        avg_per_ticker = elapsed / max(i - 1, 1)
        eta = avg_per_ticker * (len(stock_data) - i + 1) if i > 1 else 0
        print(f"\n🧠 ({i}/{len(stock_data)}) {ticker} 그리드 측정 중... [잔여 ~{eta:.0f}초]")
        per_ticker[ticker] = grid_per_ticker(ticker, df)
        print_grid(f"📊 {ticker} 단독 그리드", per_ticker[ticker])

    # --- 5종목 평균 그리드 ---
    avg_grid = aggregate(per_ticker)
    print_grid("📊 5종목 평균 그리드 (종합)", avg_grid)

    # --- 추천 셀 ---
    print(f"\n{'=' * 96}")
    print(f"  🏆 5종목 평균 — 정밀도 상위 5 (양성비 5~55% 범위 내)")
    print('=' * 96)
    top = find_top_cells(avg_grid, n=5)
    if not top:
        print("  ⚠️ 적정 양성비 + 정밀도 양호 셀 없음")
    else:
        print(f"  {'순위':>4} | {'FP':>4} | {'TP':>4} | {'정밀도':>8} | {'양성비':>8} | {'신호수':>8} | 판정")
        print(f"  {'─' * 80}")
        for rank, (prec, fp, tp, cell) in enumerate(top, 1):
            marker = "◀현재" if (fp == CURRENT_FP and tp == CURRENT_TP) else ""
            print(f"  {rank:>4} | {fp:>3}일 | {tp:>3}% | {prec:>7.3f} | {cell['pos_rate']:>7.1f}% | {int(cell['signals']):>8} | {_verdict(cell)} {marker}")

        # 현재 운용값 셀 정밀도 — 비교용
        cur_cell = avg_grid.get((CURRENT_FP, CURRENT_TP), {})
        if cur_cell:
            print(f"\n  현재(FP={CURRENT_FP}, TP={CURRENT_TP}%): 정밀도={cur_cell['precision']:.3f}, 양성비={cur_cell['pos_rate']:.1f}%, 신호수={int(cur_cell['signals'])} → {_verdict(cur_cell)}")
            best_prec, best_fp, best_tp, _ = top[0]
            delta = best_prec - cur_cell['precision']
            print(f"  최상위(FP={best_fp}, TP={best_tp}%) 대비 Δ정밀도 = {delta:+.3f}")

    # --- JSON 저장 (튜플 키는 문자열로) ---
    def to_serializable(grid):
        return {f"{fp}_{tp}": v for (fp, tp), v in grid.items()}
    json_out = {
        'forecast_periods': FORECAST_PERIODS,
        'target_pcts': TARGET_PCTS,
        'current_fp': CURRENT_FP,
        'current_tp': CURRENT_TP,
        'per_ticker': {t: to_serializable(g) for t, g in per_ticker.items()},
        'average': to_serializable(avg_grid),
    }
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(json_out, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 96}")
    print(f"  결과 저장: {OUTPUT_TXT} / {OUTPUT_JSON}")
    print(f"  소요: {time.time() - start:.1f}초")
    print('=' * 96)

    sys.stdout = sys.__stdout__
    log_f.close()


if __name__ == "__main__":
    main()
