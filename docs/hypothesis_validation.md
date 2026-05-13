# 🧪 핵심 가설 독립 검증 결과

> **검증일**: 2026-05-06 01:15

## H1: ⚠️ INCONCLUSIVE

- **avg_lift**: 1.07
- **avg_precision**: 0.3993

<details><summary>상세 데이터</summary>

```json
[
  {
    "Ticker": "APLD",
    "Base_Rate": 0.5169,
    "Signals_052": 142,
    "Precision_052": 0.4648,
    "Signals_060": 5,
    "Precision_060": 0.6,
    "Avg_Signal_Return": 17.46,
    "Lift_052": 0.9
  },
  {
    "Ticker": "RKLB",
    "Base_Rate": 0.4501,
    "Signals_052": 111,
    "Precision_052": 0.4234,
    "Signals_060": 31,
    "Precision_060": 0.3548,
    "Avg_Signal_Return": 14.87,
    "Lift_052": 0.94
  },
  {
    "Ticker": "PLTR",
    "Base_Rate": 0.2611,
    "Signals_052": 77,
    "Precision_052": 0.2987,
    "Signals_060": 3,
    "Precision_060": 0.3333,
    "Avg_Signal_Return": 8.54,
    "Lift_052": 1.14
  },
  {
    "Ticker": "SOFI",
    "Base_Rate": 0.2617,
    "Signals_052": 185,
    "Precision_052": 0.2865,
    "Signals_060": 8,
    "Precision_060": 0.0,
    "Avg_Signal_Return": 8.87,
    "Lift_052": 1.09
  },
  {
    "Ticker": "IONQ",
    "Base_Rate": 0.4105,
    "Signals_052": 172,
    "Precision_052": 0.5233,
    "Signals_060": 28,
    "Precision_060": 0.5357,
    "Avg_Signal_Return": 16.7,
    "Lift_052": 1.27
  }
]
```
</details>

---

## H2: ⚠️ INCONCLUSIVE

- **filtered_sharpe**: 0.96
- **unfiltered_sharpe**: 0.96
---

## H3: ❌ FAIL

- **lookahead**: CLEAN

<details><summary>상세 데이터</summary>

```json
[
  {
    "Ticker": "APLD",
    "Regime": "Bull",
    "Avg_Fwd_Return": 6.13,
    "Days": 320
  },
  {
    "Ticker": "APLD",
    "Regime": "Sideways",
    "Avg_Fwd_Return": 5.96,
    "Days": 386
  },
  {
    "Ticker": "APLD",
    "Regime": "Bear",
    "Avg_Fwd_Return": 7.35,
    "Days": 183
  },
  {
    "Ticker": "RKLB",
    "Regime": "Bull",
    "Avg_Fwd_Return": 1.4,
    "Days": 432
  },
  {
    "Ticker": "RKLB",
    "Regime": "Sideways",
    "Avg_Fwd_Return": 4.61,
    "Days": 462
  },
  {
    "Ticker": "RKLB",
    "Regime": "Bear",
    "Avg_Fwd_Return": 2.58,
    "Days": 343
  },
  {
    "Ticker": "PLTR",
    "Regime": "Bull",
    "Avg_Fwd_Return": 3.2,
    "Days": 436
  },
  {
    "Ticker": "PLTR",
    "Regime": "Sideways",
    "Avg_Fwd_Return": 0.52,
    "Days": 489
  },
  {
    "Ticker": "PLTR",
    "Regime": "Bear",
    "Avg_Fwd_Return": 3.64,
    "Days": 351
  }
]
```
</details>

---

## H4: ✅ PASS

- **kelly_avg**: 14.43
- **equal_avg**: 11.11

<details><summary>상세 데이터</summary>

```json
[
  {
    "Ticker": "APLD",
    "Kelly_Return": 18.85,
    "Equal_Return": 17.61
  },
  {
    "Ticker": "RKLB",
    "Kelly_Return": 12.72,
    "Equal_Return": 8.21
  },
  {
    "Ticker": "PLTR",
    "Kelly_Return": 11.72,
    "Equal_Return": 7.52
  }
]
```
</details>

---

