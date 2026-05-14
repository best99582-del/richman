# ============================================================================
# 🔬 test_predict.py — AI 예측 모델 검증
# ============================================================================
import numpy as np

from indicators import Make_Indicators
from predict import Analyze_Full, Add_AI_Signals, Create_Windowed_Data, _create_model, _calc_pos_weight
import config
from data_loader import load_ohlcv

TEST_TICKERS = config.TEST_TICKERS


# ============================================================================
# [공통] 데이터 1회 전처리 (클래스 균형·피처 중요도 테스트용)
# ============================================================================

def _prepare_all() -> dict:
    """지표 산출 완료 데이터 캐싱 — AI 신호 없이 지표만 (학습 데이터 생성용)"""
    stock_data = {}
    for ticker in TEST_TICKERS:
        try:
            df = load_ohlcv(ticker, start=config.START_DATE, drop_intraday=True)
            df = Make_Indicators(df)
            df = df.dropna()
            stock_data[ticker] = df
        except Exception as e:
            print(f"  ⚠️ {ticker} 실패: {e}")
    return stock_data


# ============================================================================
# [검증 1] AI 예측이 무작위가 아닌지 확인
# ============================================================================

def test_ai_not_random():
    """
    Analyze_Full() 전체 파이프라인 실행으로 비랜덤성 확인.
    확률이 0.45~0.55 수렴이면 모델이 아무것도 학습하지 못한 것.
    ⚠️ 5-Fold CV 포함 — 종목당 약 30초 소요
    """
    print("\n" + "="*70)
    print("🔬 [AI 검증 1] 예측이 무작위가 아닌지 확인")
    print("   ⚠️ 종목당 ~30초 소요 (5-Fold CV)")
    print("="*70)

    for ticker in TEST_TICKERS:
        try:
            result = Analyze_Full(ticker)
            if result is None:
                print(f"  {ticker}: ⚠️ 분석 실패")
                continue

            prob  = result['Prob']
            prec  = result['Hist_Precision']
            sigs  = result['Signals']

            status = "✅" if 0.1 < prob < 0.95 else "⚠️ 극단값 (과적합 의심)"
            print(f"  {ticker}: AI확률={prob:.3f} | 정밀도={prec:.3f} | 신호={sigs}회 | {status}")
        except Exception as e:
            print(f"  {ticker}: ⚠️ 에러: {e}")

    print(f"\n  ℹ️ 0.45~0.55 수렴 → 학습 실패")
    print(f"  ℹ️ 0.95+ → 과적합   |   정밀도 0.5 미만 → 역방향 예측")


# ============================================================================
# [검증 2] 클래스 균형 확인
# ============================================================================

def test_class_balance(stock_data: dict):
    """
    AI 타겟(y=1) 비율 확인.
    10~40%가 적정 — 너무 낮으면 희귀 이벤트라 학습이 어렵고,
    너무 높으면 AI가 구별할 여지가 없어 변별력이 사라짐.
    """
    print("\n" + "="*70)
    print("🔬 [AI 검증 2] 학습 데이터 클래스 균형")
    print(f"   현재: TARGET={config.AI_TARGET_PCT}% / {config.AI_FORECAST_PERIOD}일 (Close 기준)")
    print("="*70)

    for ticker, df in stock_data.items():
        try:
            _, y = Create_Windowed_Data(
                df, config.AI_FEATURES, config.AI_WINDOW_SIZE,
                config.AI_TARGET_PCT, config.AI_FORECAST_PERIOD
            )
            pos_rate = np.mean(y) * 100
            status = "✅" if 10 < pos_rate < 50 else "⚠️ 불균형"
            print(f"  {ticker}: 전체 {len(y)}개 | "
                  f"급등(1): {np.sum(y)}개 ({pos_rate:.1f}%) | "
                  f"비급등(0): {np.sum(y == 0)}개 ({100-pos_rate:.1f}%) | {status}")
        except Exception as e:
            print(f"  {ticker}: ⚠️ 에러: {e}")

    print(f"\n  ℹ️ 10~40%가 적정")
    print(f"  ℹ️ 5% 미만 → AI_TARGET_PCT 낮추기  |  60%+ → AI_TARGET_PCT 높이기")


# ============================================================================
# [검증 3] 피처 중요도 분석
# ============================================================================

def test_feature_importance(stock_data: dict):
    """
    XGBoost 피처 중요도 확인.
    특정 피처가 70%+ 이면 과의존 → feature_experiment.py 실행 권고.

    중요도 집계 방식:
      feature_importances_ shape = (WINDOW_SIZE × n_feats,)
      layout = [day0_feat0, day0_feat1, ..., dayN_featM]
      → reshape(WINDOW_SIZE, n_feats) 후 axis=0 합산 → 피처별 전체 기여도
    """
    print("\n" + "="*70)
    print("🔬 [AI 검증 3] 피처 중요도 분석")
    print(f"   현재 피처: {config.AI_FEATURES}")
    print("="*70)

    ticker = list(stock_data.keys())[0]
    df = stock_data[ticker]

    try:
        X, y = Create_Windowed_Data(
            df, config.AI_FEATURES, config.AI_WINDOW_SIZE,
            config.AI_TARGET_PCT, config.AI_FORECAST_PERIOD
        )
        model = _create_model(_calc_pos_weight(y))
        model.fit(X, y)

        n_feats = len(config.AI_FEATURES)
        feat_sums = model.feature_importances_.reshape(config.AI_WINDOW_SIZE, n_feats).sum(axis=0)
        total = feat_sums.sum()

        print(f"  {ticker} 피처 중요도 (D-{config.AI_WINDOW_SIZE}~D-1 윈도우 합산):")
        for feat, imp in sorted(zip(config.AI_FEATURES, feat_sums), key=lambda x: -x[1]):
            pct = imp / total * 100
            bar = '█' * int(pct / 3)
            print(f"    {feat:<15}: {pct:>5.1f}% {bar}")

        top_feat, top_imp = max(zip(config.AI_FEATURES, feat_sums), key=lambda x: x[1])
        if top_imp / total > 0.7:
            print(f"\n  ⚠️ {top_feat}이 {top_imp/total:.0%}로 과의존 — feature_experiment.py 실행 권고")
        else:
            print(f"\n  ✅ 피처 분산 양호")

    except Exception as e:
        print(f"  {ticker}: ⚠️ 에러: {e}")


# ============================================================================
# [검증 4] 폭락 직전 AI 판단 점검
# ============================================================================

def test_crash_guard():
    """
    알려진 폭락 직전(코로나/금리인상 충격)에 AI가 매수를 냈는지 점검.
    QQQ 기준 — 개별 소형주는 종목 특이 노이즈가 많아 시장 방어력 판단 어려움.
    매수신호가 '있음'이면 하락장 방어가 안 되는 것.
    """
    print("\n" + "="*70)
    print("🔬 [AI 검증 4] 폭락 직전 AI 판단 점검 (QQQ 기준)")
    print("="*70)

    crash_events = [
        ('2020-02-14', '2020-02-19', '코로나 폭락 직전'),
        ('2022-01-03', '2022-01-10', '금리인상 하락 시작'),
    ]

    try:
        df = load_ohlcv('QQQ', start='2019-01-01', drop_intraday=True)
        df = Make_Indicators(df)
        df = Add_AI_Signals(df)

        for start, end, event in crash_events:
            try:
                period = df.loc[start:end]
                if period.empty:
                    continue
                avg_prob  = period['AI_Prob'].mean()
                would_buy = (period['AI_Prob'] >= config.AI_FILTER).any()
                status    = "❌ 위험" if would_buy else "✅ 매수 없음"
                print(f"  [{event}] {start} ~ {end}")
                print(f"    AI확률: {avg_prob:.3f} | 매수신호: {'있음' if would_buy else '없음'} {status}")
            except Exception:
                pass

    except Exception as e:
        print(f"  QQQ: ⚠️ 에러: {e}")

    print(f"\n  ℹ️ 폭락 직전 매수신호가 없어야 정상 — 있으면 AI_FILTER 상향 검토")


# ============================================================================
# [실행]
# ============================================================================


import sys
import os

class Logger(object):
    def __init__(self, filename="results/default.txt"):
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        self.terminal = sys.stdout
        self.log = open(filename, "w", encoding='utf-8')

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        self.terminal.flush()
        self.log.flush()

if __name__ == "__main__":
    sys.stdout = Logger('results/test_predict_results.txt')
    print("🔬 [Richman] AI 예측 모델 종합 검증")
    print(f"   대상: {TEST_TICKERS}")
    print(f"   피처: {config.AI_FEATURES}")
    print("="*70)

    print("\n⏳ 공통 데이터 전처리 중...")
    stock_data = _prepare_all()

    test_ai_not_random()                  # [1] AI 비랜덤성 확인 (느림 — Analyze_Full)
    test_class_balance(stock_data)        # [2] 클래스 균형
    test_feature_importance(stock_data)   # [3] 피처 중요도
    test_crash_guard()                    # [4] 폭락 방어 점검

    print("\n" + "="*70)
    print("✅ AI 검증 완료!")
    print("   → 피처 과의존·클래스 불균형 발견 시: feature_experiment.py 실행")
    print("="*70)
