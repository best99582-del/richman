"""
test_sensitivity의 신규 [6][7] 검증(FP, TP)만 단독 실행.

현재 config: FP=10, TP=7, AI_FILTER=0.55 (이미 v10.2 반영 완료)
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
import test_sensitivity as ts

print(f"현재 config: FP={config.AI_FORECAST_PERIOD}, TP={config.AI_TARGET_PCT}%, AI_FILTER={config.AI_FILTER}")
print(f"피처: {config.AI_FEATURES}")
print()

indicators_dict = ts._prepare_indicators_only()
ts.test_forecast_period(indicators_dict)
ts.test_target_pct(indicators_dict)
