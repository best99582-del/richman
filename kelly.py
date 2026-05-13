# ============================================================================
# 💸 [퀀트 유니버스] 자금 관리 엔진 (kelly.py)
# ============================================================================
# 역할: Half-Kelly 공식으로 종목별 최적 투입 비중 및 매수 수량 산출
# 파이프라인 위치: [5단계] 자금 관리
# 의존성: config.py (리스크 파라미터), predict.py (AI_Prob, Model_Precision)
#
# 핵심 공식:
#   Kelly: f = p - (q / r)
#   Half-Kelly: f × KELLY_FRACTION (파산 확률 대폭 감소)
#   여기서 p=승률(모델 정밀도), q=패률(1-p), r=손익비 — config.WIN_LOSS_RATIO 고정
# ============================================================================

import math

import config


# ============================================================================
# [내부 헬퍼] 기본 켈리 산출 — 손익비 config.WIN_LOSS_RATIO 고정
# ============================================================================

def _base_kelly(precision: float) -> float:
    """순수 켈리 공식: f = p - q/r. 기댓값 음수면 0."""
    q = 1.0 - precision
    return max(0.0, precision - q / config.WIN_LOSS_RATIO)


def _apply_cap(weight: float) -> float:
    """단일 종목 최대 비중 캡 (MAX_WEIGHT_PER_TRADE) 적용."""
    return min(weight, config.MAX_WEIGHT_PER_TRADE)


# ============================================================================
# [핵심 함수 1] Half-Kelly 비중 계산 (AI 확신도 가중 + MAX 캡)
# ============================================================================

def Calculate_Half_Kelly(model_precision: float, ai_prob: float) -> float:
    """
    predict.py의 라플라스 정밀도(승률)와 당일 AI 확신도를 융합하여
    Half-Kelly 최적 투입 비중을 산출.

    손익비는 config.WIN_LOSS_RATIO로 고정 — ATR이 큰 고변동 종목에서 동적
    손익비가 1.0 미만으로 떨어져 비중이 0에 수렴하는 문제를 회피.

    Args:
        model_precision: 라플라스 스무딩 정밀도 (0.0~1.0)
        ai_prob: 당일 AI 상승 확신도 (0.0~1.0, AI_FILTER 미만이면 0 반환)

    Returns:
        float: 최종 투입 비중 (MAX_WEIGHT_PER_TRADE 캡 적용). 부적격 시 0.0.
    """
    if ai_prob < config.AI_FILTER:
        return 0.0

    base = _base_kelly(model_precision)
    if base <= 0:
        return 0.0

    # 확신도 가중치: AI_FILTER 통과 직후 1.0 → ai_prob=1.0이면 1.5
    confidence_weight = 1.0 + (
        (ai_prob - config.AI_FILTER) / (1.0 - config.AI_FILTER)
    ) * 0.5

    return _apply_cap(base * confidence_weight * config.KELLY_FRACTION)


# ============================================================================
# [핵심 함수 2] 참고 비중 — AI 확신도 무관, 정밀도만으로 Half-Kelly 산출
# ============================================================================

def Calculate_Reference_Kelly(model_precision: float) -> float:
    """
    관망 종목용 참고비중: AI_FILTER에 막혔어도 "모델 정밀도만 보면 얼마짜리
    베팅인가"를 알려줌. confidence_weight=1.0 중립 기준 + MAX 캡 적용.
    """
    return _apply_cap(_base_kelly(model_precision) * config.KELLY_FRACTION)


# ============================================================================
# [핵심 함수 3] ATR 기반 동적 손절가 산출
# ============================================================================

def _get_stop_loss_price(entry_price: float, atr: float) -> float:
    """진입가에서 ATR × ATR_STOP_MULTIPLIER 아래에 최초 손절선 설정."""
    return entry_price - (atr * config.ATR_STOP_MULTIPLIER)


# ============================================================================
# [핵심 함수 4] 최종 매수 수량 산출
# ============================================================================

def Get_Position_Size(
    total_capital: float,
    current_price: float,
    atr: float,
    model_precision: float,
    ai_prob: float
) -> tuple:
    """
    전체 자본 → Satellite 할당 → 켈리 비중 → 수수료 반영 → 최종 매수 주수 산출.

    Returns:
        tuple: (매수 주수, 손절가, 켈리 비중). 투자 부적격 시 (0, 0.0, 0.0).
    """
    kelly_weight = Calculate_Half_Kelly(model_precision, ai_prob)
    if kelly_weight <= 0:
        return 0, 0.0, 0.0

    satellite_capital = total_capital * config.SATELLITE_ALLOCATION
    trade_amount = satellite_capital * kelly_weight

    adjusted_price = current_price * (1 + config.FEE_RATE)
    shares_to_buy = math.floor(trade_amount / adjusted_price)

    stop_loss_price = _get_stop_loss_price(current_price, atr)

    return shares_to_buy, stop_loss_price, kelly_weight


# ============================================================================
# [단독 실행] 포워드테스팅 비중 시뮬레이터
# ============================================================================

if __name__ == "__main__":
    """
    포워드테스팅 모드: 사용자가 실측 승률을 입력하면 손익비 고정 / Half-Kelly
    기반 비중을 산출. 매월 매매 결과로 측정한 승률을 반영해 직관 검증.
    """
    print("📊 [ kelly.py — 포워드테스팅 비중 시뮬레이터 ]")
    print(f"   손익비 고정 {config.WIN_LOSS_RATIO} | "
          f"Kelly Fraction {config.KELLY_FRACTION} | "
          f"AI_FILTER {config.AI_FILTER}")
    print("=" * 60)

    try:
        win_rate = float(input("▶ 실측 승률 입력 (예: 0.60): ").strip())
        ai_prob = float(input("▶ AI 확신도 입력 (예: 0.70): ").strip())
    except ValueError:
        print("❌ 숫자 입력 필요")
        raise SystemExit(1)

    weight = Calculate_Half_Kelly(win_rate, ai_prob)
    satellite = config.CAPITAL * config.SATELLITE_ALLOCATION
    invest = satellite * weight

    print("-" * 60)
    print(f"입력 승률:           {win_rate:.2%}")
    print(f"입력 AI 확신도:      {ai_prob:.2%}")
    print(f"Half-Kelly 비중:     {weight:.2%}  (MAX 캡 {config.MAX_WEIGHT_PER_TRADE:.0%} 반영)")
    print(f"Satellite 자금:      ${satellite:,.0f}")
    print(f"투입 금액:           ${invest:,.0f}  (전체 자본의 {invest/config.CAPITAL:.2%})")
    print("=" * 60)
