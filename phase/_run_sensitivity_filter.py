"""
test_sensitivity의 test_ai_filter만 단독 실행 (수분 절약).

(FP=10, TP=7%) 임시 적용된 config 상태에서 AI_FILTER 백테스트 sweep만.
test_filter_calib(분류 정밀도)과 교차 비교 용도.
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

print(f"임시 라벨 정의 확인: AI_FORECAST_PERIOD={config.AI_FORECAST_PERIOD}, AI_TARGET_PCT={config.AI_TARGET_PCT}")
print(f"피처: {config.AI_FEATURES}")
print()

stock_data = ts._prepare_all()
ts.test_ai_filter(stock_data)
