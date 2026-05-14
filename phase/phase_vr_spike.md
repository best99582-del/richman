# Phase: Volume_Ratio → Volume_Spike 교체

## Context

CLAUDE.md 로드맵 2번 "Volume_Ratio AI 피처 점검" 작업.

### 발견

5-Fold CV 정밀도 측정에서 Volume_Ratio가 모델에 손해:

| 종목 | 6피처(VR 포함) | 5피처(VR 제외) | Δ |
|---|---|---|---|
| APLD | 0.5213 | 0.5371 | -0.0158 |
| SOFI | 0.3070 | 0.3085 | -0.0015 |
| IREN | 0.5416 | 0.5594 | -0.0178 |
| IONQ | 0.4630 | 0.4573 | +0.0057 |
| PLTR | 0.2632 | 0.2687 | -0.0056 |
| AAPL | 0.0497 | 0.0496 | +0.0001 |
| **평균** | — | — | **-0.0058** |

**→ Volume_Ratio가 평균 -0.58%p 정밀도를 떨어뜨림.**

## 원인 분석 (5가지 가설)

| 가설 | 결과 |
|---|---|
| 1. VR 신호 자체 | VR>2일 때 급등 77.8% (전체 평균 62% 대비 +15.8%p) — 신호는 강함 |
| 2. 후행성 | 전일 상승 후 VR 1.48, 평상시 1.06 — 약간 후행이긴 함 |
| 3. **극단값 분포** | mean=1.06, std=0.94, **max=17.43** (평균의 17배) |
| 4. 다른 피처와 상관 | BandWidth 0.006, RSI 0.134, Disparity 0.225 (모두 낮음 — 독립 정보) |
| 5. 신호 강도 | 급등 직전 VR 1.14, 평범한 날 0.91 — 차이 0.23밖에 안 됨 |

### 진단 결론

VR > 2 같은 **극단 시점에서는 신호 강함**, 그러나 **평소의 미세한 차이는 노이즈**.
XGBoost가 모든 시점을 학습하면서 노이즈에 휘둘리고, 극단값 17이 분할 기준을 왜곡.

## 4가지 변환 실험

5개 베이스 피처(`RSI, Disparity, BandWidth, Slow_K, Slow_D`) + 다음 추가:

| 옵션 | 변환 | 6종목 평균 정밀도 |
|---|---|---|
| A. 원본 | Volume_Ratio | 0.3578 |
| B. log | log(VR+1) | 0.3578 (효과 없음) |
| **C. Spike** | **`VR > 2` 이진** | **0.3663 🥇 최고** |
| D. Clip | clip(VR, 0, 3) | 0.3589 |
| E. 없음 | (5개) | 0.3634 |

**🥇 C. Volume_Spike (VR>2 이진) 채택**: 6종목 중 4종목 최고, 평균 +0.85%p (원본 대비)

## 변경 내용

### [indicators.py:191-194](../indicators.py)
```python
# [18] 거래량 폭증 플래그 (v10: AI 피처용 — 극단값 노이즈 제거)
df['Volume_Spike'] = (df['Volume_Ratio'] > 2).astype(int)
```

`Volume_Ratio` 원본은 표시/분석용으로 유지. 이 위에 이진 플래그만 추가.

### [config.py:109](../config.py#L109)
```python
# Before: 'Volume_Ratio'
# After:  'Volume_Spike'
```

AI_FEATURES 한 줄만 교체. 나머지 5개 피처 그대로.

## 검증

| 항목 | 결과 |
|---|---|
| Volume_Spike 분포 (APLD) | 1=54회 / 0=851회 (6% 발생) |
| 신규 피처 정밀도 (APLD) | 0.5213 → **0.5393** (+1.8%p) |
| 모든 모듈 import 정상 | ✅ predict/screener/backtest/alert/optimize/trade_journal |
| trade_journal log APLD/SOFI | ✅ 정상 작동, 결과 그대로 |

## 백테스트 영향

피처 교체로 AI_FEATURES 자체가 바뀜 → predict.py의 final_prob 산출이 바뀌고
backtest.py의 AI 필터 분기도 바뀌므로 **추후 별도 백테스트 비교 필요**.
일단 단발 정밀도 개선은 확인됨.

## 상태

- [x] 원인 분석 (5가지 가설)
- [x] 4가지 변환 실험
- [x] indicators.py에 Volume_Spike 컬럼 추가
- [x] config.AI_FEATURES 교체
- [x] 정상 작동 + 정밀도 개선 검증
- [x] phase 문서 작성
- [ ] 커밋 + GitHub push
- [ ] (선택) 5종목 백테스트 비교
