"""test_sensitivity의 test_bb_squeeze만 단독 실행. v10.2 운용값 위에서."""
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

print(f"config: FP={config.AI_FORECAST_PERIOD}, TP={config.AI_TARGET_PCT}%, AI_FILTER={config.AI_FILTER}, BB_SQUEEZE_RATIO(현재)={config.BB_SQUEEZE_RATIO}")
print(f"피처: {config.AI_FEATURES}")
print()

stock_data = ts._prepare_all()
ts.test_bb_squeeze(stock_data)
