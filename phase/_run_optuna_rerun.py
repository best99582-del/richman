"""
Optuna 재최적화 실행 스크립트 (Phase: phase_optuna_rerun)

- Layer 2 (500 trials) 먼저
- 그 후 Layer 1 (250 trials)
- 결과를 phase/optuna_rerun_result.json 으로 저장
"""

import json
import sys
import time
from pathlib import Path

# Windows cp949 콘솔에서 유니코드(em-dash 등) 출력 가능하도록 stdout/stderr를 UTF-8로 재구성
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 프로젝트 루트를 import path에 추가
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import optuna

import config
from indicators import Make_Indicators
from predict import Add_AI_Signals
from data_loader import load_ohlcv
from optimize import objective_layer1, objective_layer2

optuna.logging.set_verbosity(optuna.logging.WARNING)


def main():
    out_path = ROOT / "phase" / "optuna_rerun_result.json"
    log_path = ROOT / "phase" / "optuna_rerun_log.txt"

    log_lines = []

    def log(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        log_lines.append(line)
        log_path.write_text("\n".join(log_lines), encoding="utf-8")

    log(f"TEST_TICKERS = {config.TEST_TICKERS}")
    log(f"AI_FEATURES = {config.AI_FEATURES}")

    # --- 데이터 전처리 ---
    raw_dfs = {}
    processed_dfs = {}
    for ticker in config.TEST_TICKERS:
        log(f"[preprocess] {ticker} ...")
        raw_df = load_ohlcv(ticker, start=config.START_DATE, drop_intraday=True)
        raw_dfs[ticker] = raw_df.copy()
        df = Make_Indicators(raw_df)
        df = Add_AI_Signals(df)
        processed_dfs[ticker] = df.dropna()
        log(f"[preprocess] {ticker} done — rows={len(processed_dfs[ticker])}")

    log("=" * 60)
    log("Layer 2 시작 (500 trials)")
    log("=" * 60)
    t0 = time.time()
    study_l2 = optuna.create_study(direction='maximize')
    study_l2.optimize(
        lambda trial: objective_layer2(trial, processed_dfs),
        n_trials=500,
        show_progress_bar=False,
    )
    l2_secs = time.time() - t0
    log(f"Layer 2 완료 — {l2_secs:.1f}s, best={study_l2.best_value:.4f}")
    log(f"Layer 2 best_params = {study_l2.best_params}")

    log("=" * 60)
    log("Layer 1 시작 (250 trials)")
    log("=" * 60)
    t0 = time.time()
    study_l1 = optuna.create_study(direction='maximize')
    study_l1.optimize(
        lambda trial: objective_layer1(trial, raw_dfs),
        n_trials=250,
        show_progress_bar=False,
    )
    l1_secs = time.time() - t0
    log(f"Layer 1 완료 — {l1_secs:.1f}s, best={study_l1.best_value:.4f}")
    log(f"Layer 1 best_params = {study_l1.best_params}")

    result = {
        "test_tickers": config.TEST_TICKERS,
        "ai_features": list(config.AI_FEATURES),
        "layer2": {
            "n_trials": 500,
            "best_value": study_l2.best_value,
            "best_params": study_l2.best_params,
            "elapsed_seconds": l2_secs,
        },
        "layer1": {
            "n_trials": 250,
            "best_value": study_l1.best_value,
            "best_params": study_l1.best_params,
            "elapsed_seconds": l1_secs,
        },
    }
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"결과 저장: {out_path}")
    log("DONE")


if __name__ == "__main__":
    main()
