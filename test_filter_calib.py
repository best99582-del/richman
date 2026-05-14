# ============================================================================
# 🔬 test_filter_calib.py — AI_FILTER 재캘리브레이션
# ============================================================================
# 목적: (FP=10, TP=7%) 고정 후 AI_FILTER 임계값별 신호 품질 측정.
#       phase_signal_grid.md 추천 라벨 정의 위에서 적정 필터값 결정.
#
# 측정 지표 (필터값당):
#   - CV_Precision (5-Fold 평균)
#   - Signal_Count (CV 누적 매수신호 수)
#   - Hits (≈ precision × signals, 기대 적중 횟수 근사)
#
# 5종목 평균 + 종목별 출력. 백테스트 없음.
# ============================================================================

import json
import os
import sys
import time

import numpy as np

import config
from data_loader import load_ohlcv
from indicators import Make_Indicators
from predict import cv_precision

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

TEST_TICKERS = config.TEST_TICKERS

# 고정 라벨 정의 (phase_signal_grid 추천)
FIXED_FP = 10
FIXED_TP = 7

# 필터 스윕
FILTER_VALUES = [0.45, 0.50, 0.52, 0.55, 0.58, 0.60, 0.63, 0.65, 0.70]

CURRENT_FILTER = config.AI_FILTER

OUTPUT_TXT = "results/filter_calib_results.txt"
OUTPUT_JSON = "results/filter_calib_results.json"


class Tee:
    def __init__(self, *files):
        self.files = files

    def write(self, s):
        for f in self.files:
            f.write(s)

    def flush(self):
        for f in self.files:
            f.flush()


def _prepare_all() -> dict:
    print("⏳ 데이터 전처리 중 (지표 산출)...")
    stock_data = {}
    for ticker in TEST_TICKERS:
        try:
            df = load_ohlcv(ticker, start=config.START_DATE, drop_intraday=True)
            df = Make_Indicators(df).dropna()
            stock_data[ticker] = df
            print(f"  ✅ {ticker}: {len(df)}일")
        except Exception as e:
            print(f"  ⚠️ {ticker} 실패: {e}")
    return stock_data


def sweep_per_ticker(df) -> dict:
    """필터값별 (CV 정밀도, 신호수, hits) 측정"""
    result = {}
    for f in FILTER_VALUES:
        try:
            prec, sigs = cv_precision(
                df,
                features=config.AI_FEATURES,
                window=config.AI_WINDOW_SIZE,
                target_pct=FIXED_TP,
                forecast_period=FIXED_FP,
                ai_filter=f,
            )
            result[f] = {
                'precision': float(prec),
                'signals': int(sigs),
                'hits': float(prec) * int(sigs),  # 기대 적중 (precision × signals)
            }
        except Exception as e:
            result[f] = {'precision': 0.0, 'signals': 0, 'hits': 0.0, 'error': str(e)}
    return result


def aggregate(per_ticker: dict) -> dict:
    """5종목 평균"""
    avg = {}
    for f in FILTER_VALUES:
        precs, sigs, hits = [], [], []
        for grid in per_ticker.values():
            cell = grid.get(f, {})
            if cell.get('error'):
                continue
            precs.append(cell['precision'])
            sigs.append(cell['signals'])
            hits.append(cell['hits'])
        avg[f] = {
            'precision': float(np.mean(precs)) if precs else 0.0,
            'signals': float(np.mean(sigs)) if sigs else 0.0,
            'hits': float(np.mean(hits)) if hits else 0.0,
        }
    return avg


def _verdict(cell: dict) -> str:
    p, s = cell['precision'], cell['signals']
    if s < 20:
        return "❌신호부족"
    if p >= 0.60:
        return "✅우수"
    if p >= 0.55:
        return "✅양호"
    if p >= 0.50:
        return "⚠️보통"
    return "❌부진"


def print_sweep(title: str, grid: dict):
    print(f"\n{'=' * 78}")
    print(f"  {title}")
    print(f"  고정: FP={FIXED_FP}일 / TP={FIXED_TP}%   |   현재 AI_FILTER={CURRENT_FILTER}")
    print('=' * 78)
    print(f"  {'AI_FILTER':>10} | {'정밀도':>8} | {'신호수':>8} | {'적중수(≈)':>10} | 판정")
    print(f"  {'─' * 70}")
    for f in FILTER_VALUES:
        c = grid.get(f, {})
        marker = " ◀현재" if abs(f - CURRENT_FILTER) < 1e-4 else ""
        print(
            f"  {f:>10.2f} | {c.get('precision', 0):>7.3f} | "
            f"{int(c.get('signals', 0)):>8} | {c.get('hits', 0):>10.1f} | "
            f"{_verdict(c)}{marker}"
        )


def recommend(avg_grid: dict) -> tuple:
    """우선순위: 정밀도 ≥ 0.55 중 hits(기대 적중) 최대 셀.
    조건 못 미치면 정밀도 최대 셀."""
    qualified = [(f, c) for f, c in avg_grid.items()
                 if c['precision'] >= 0.55 and c['signals'] >= 50]
    if qualified:
        best = max(qualified, key=lambda x: x[1]['hits'])
        return best, "정밀도≥0.55 + hits 최대"
    # fallback
    best = max(avg_grid.items(), key=lambda x: x[1]['precision'])
    return best, "정밀도 최대 (조건 미충족 fallback)"


def main():
    os.makedirs('results', exist_ok=True)
    log_f = open(OUTPUT_TXT, 'w', encoding='utf-8')
    sys.stdout = Tee(sys.__stdout__, log_f)

    print("🔬 [Richman] AI_FILTER 재캘리브레이션")
    print(f"  대상: {TEST_TICKERS}")
    print(f"  피처: {config.AI_FEATURES}")
    print(f"  고정 라벨: FP={FIXED_FP}일 / TP={FIXED_TP}% (phase_signal_grid 추천)")
    print(f"  스윕: AI_FILTER={FILTER_VALUES}")
    print(f"  측정: CV_Precision(5-Fold) + Signal_Count + Hits(≈정밀도×신호수)")

    stock_data = _prepare_all()
    if not stock_data:
        print("⚠️ 데이터 없음 — 종료")
        return

    start = time.time()
    per_ticker = {}
    for i, (ticker, df) in enumerate(stock_data.items(), 1):
        print(f"\n🧠 ({i}/{len(stock_data)}) {ticker} 필터 스윕 중...")
        per_ticker[ticker] = sweep_per_ticker(df)
        print_sweep(f"📊 {ticker} 단독 스윕", per_ticker[ticker])

    avg = aggregate(per_ticker)
    print_sweep("📊 5종목 평균 스윕 (종합)", avg)

    # 추천
    print(f"\n{'=' * 78}")
    print(f"  🏆 추천 AI_FILTER")
    print('=' * 78)
    (best_f, best_cell), rule = recommend(avg)
    print(f"  추천: AI_FILTER = {best_f:.2f}")
    print(f"    선정 규칙: {rule}")
    print(f"    정밀도 {best_cell['precision']:.3f} | 평균 신호수 {best_cell['signals']:.0f} | hits {best_cell['hits']:.1f}")

    cur_cell = avg.get(CURRENT_FILTER) or avg.get(round(CURRENT_FILTER, 2))
    if cur_cell:
        delta_p = best_cell['precision'] - cur_cell['precision']
        delta_h = best_cell['hits'] - cur_cell['hits']
        print(f"\n  현재(AI_FILTER={CURRENT_FILTER}): "
              f"정밀도 {cur_cell['precision']:.3f} | 신호 {cur_cell['signals']:.0f} | hits {cur_cell['hits']:.1f}")
        print(f"  Δ정밀도 = {delta_p:+.3f}    Δhits = {delta_h:+.1f}")

    # JSON 저장
    def to_serializable(grid):
        return {f"{f:.2f}": v for f, v in grid.items()}
    json_out = {
        'fixed_fp': FIXED_FP,
        'fixed_tp': FIXED_TP,
        'current_filter': CURRENT_FILTER,
        'filter_values': FILTER_VALUES,
        'per_ticker': {t: to_serializable(g) for t, g in per_ticker.items()},
        'average': to_serializable(avg),
        'recommended': {
            'filter': best_f,
            'precision': best_cell['precision'],
            'signals': best_cell['signals'],
            'hits': best_cell['hits'],
            'rule': rule,
        },
    }
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(json_out, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 78}")
    print(f"  결과 저장: {OUTPUT_TXT} / {OUTPUT_JSON}")
    print(f"  소요: {time.time() - start:.1f}초")
    print('=' * 78)

    sys.stdout = sys.__stdout__
    log_f.close()


if __name__ == "__main__":
    main()
