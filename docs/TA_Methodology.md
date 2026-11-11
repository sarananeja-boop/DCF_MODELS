# ValuationLabs Technical Analysis Methodology (v0.1)

**Engine Version:** `ta-foundation-2.5.0`  
**Model Version:** `2.5.0`  
**Signal Execution Convention:** `confirmed-bar-close-next-open`

This document defines every mathematical formula, smoothing convention, causal confirmation rule, and coverage threshold used by the ValuationLabs Technical Analysis (TA) module. It serves as the single source of truth for backend calculations, unit tests, and the in-app methodology guide.

---

## 1. Price Bases & Exchange Calendars

### 1.1 Dual Price Series
Every security is processed into two distinct daily OHLCV series from raw Yahoo Finance history (`auto_adjust=False, actions=True`):
1. **Split-Adjusted OHLCV (`ohlc_split`)**:
   - Adjusted for forward and reverse stock splits only.
   - Used for **price charts, moving averages, support/resistance levels, volume profile, candlestick/swing structures, and ATR stop-loss levels** so historical price levels match actual traded chart levels.
2. **Total-Return Adjusted OHLCV (`ohlc_tr`)**:
   - Constructed by multiplying `Open, High, Low, Close` by the total-return factor:
     $$\text{TR Factor}_t = \frac{\text{Adj Close}_t}{\text{Close}_t}$$
   - Used for **total-return backtesting, return distributions, benchmark alpha/beta regressions, Yang–Zhang volatility cones, and monthly seasonality**.

### 1.2 Exchange Timezones & Forming Bars
- **India (`NSE` / `BSE`)**: `Asia/Kolkata` (`IST`), regular session `09:15–15:30 IST`, benchmark `^NSEI` (Nifty 50). Primary listing resolves to `.NS`, with automatic fallback to `.BO` when NSE history is unavailable.
- **United States (`NYSE` / `NASDAQ`)**: `America/New_York` (`ET`), regular session `09:30–16:00 ET`, benchmark `^GSPC` (S&P 500).
- **Forming-Bar Rule**:
  - `last_session` always reports the last **completed** daily exchange session (`YYYY-MM-DD`).
  - Weekly (`W-FRI`) and monthly (`ME`) resampled series exclude any incomplete (forming) current week or month when computing weekly/monthly indicators (`weekly_completed`, `monthly_completed`).

---

## 2. Coverage Contract (Minimum History Thresholds)

No indicator or statistical module may emit a silent value when historical observations fall below its minimum required sample size:

| Capability Key | Feature Scope | Minimum Observations | Unit |
| :--- | :--- | ---: | :--- |
| `chart_basic_indicators` | Candlestick chart, SMA/EMA $\le 50$, RSI(14), MACD(12,26,9), ATR(14), Bollinger(20,2) | **60** | `daily_bars` |
| `long_ma_trend_templates` | SMA 150/200, Weinstein Stage (30W), Minervini 8-Point Trend Template | **260** | `daily_bars` |
| `hurst_variance_ratio` | Hurst Exponent (DFA-1) & Lo–MacKinlay Variance Ratio | **504** | `daily_bars` |
| `backtester` | Walk-Forward Event Signal Backtester | **1,260** | `daily_bars` |
| `yang_zhang_5y_percentile` | Yang–Zhang Volatility 5-Year Percentile Rank | **1,280** | `daily_bars` |
| `monthly_seasonality` | Monthly Seasonality Matrix & Kruskal–Wallis Test | **96** | `monthly_returns` |

---

## 3. Core Indicator Formulas (TA v0.1)

### 3.1 Simple & Exponential Moving Averages (`SMA`, `EMA`)
- **Simple Moving Average**:
  $$\text{SMA}_n(t) = \frac{1}{n} \sum_{i=0}^{n-1} C_{t-i}$$
  Undefined (`null`) for $t < n - 1$. Standard windows: $n \in \{20, 50, 150, 200\}$.
- **Exponential Moving Average**:
  $$\alpha = \frac{2}{n + 1}, \quad \text{EMA}_n(t) = \alpha C_t + (1 - \alpha)\text{EMA}_n(t-1)$$
  Seeded at $t = n - 1$ using the $n$-period simple average $\text{SMA}_n(n-1)$.

### 3.2 Wilder's Relative Strength Index (`RSI(14)`)
Uses J. Welles Wilder Jr.'s (1978) recursive smoothing ($\alpha = 1/14$):
1. Price change: $\Delta C_t = C_t - C_{t-1}$, with $U_t = \max(\Delta C_t, 0)$ and $D_t = \max(-\Delta C_t, 0)$.
2. Initial 14-period seed at $t = 14$:
   $$\bar{U}_{14} = \frac{1}{14}\sum_{i=1}^{14} U_i, \quad \bar{D}_{14} = \frac{1}{14}\sum_{i=1}^{14} D_i$$
3. Wilder recursive update for $t > 14$:
   $$\bar{U}_t = \frac{13 \cdot \bar{U}_{t-1} + U_t}{14}, \quad \bar{D}_t = \frac{13 \cdot \bar{D}_{t-1} + D_t}{14}$$
4. Relative Strength & RSI:
   $$\text{RS}_t = \frac{\bar{U}_t}{\bar{D}_t}, \quad \text{RSI}_t = 100 - \frac{100}{1 + \text{RS}_t}$$

### 3.3 Moving Average Convergence Divergence (`MACD(12, 26, 9)`)
$$\text{MACD}_t = \text{EMA}_{12}(C)_t - \text{EMA}_{26}(C)_t$$
$$\text{Signal}_t = \text{EMA}_9(\text{MACD})_t, \quad \text{Histogram}_t = \text{MACD}_t - \text{Signal}_t$$

### 3.4 Wilder's Average True Range (`ATR(14)`)
1. True Range:
   $$\text{TR}_t = \max\left(H_t - L_t,\; |H_t - C_{t-1}|,\; |L_t - C_{t-1}|\right)$$
2. Seeded at $t = 13$ (14 observations) as the arithmetic mean of $\text{TR}_{0..13}$, then updated via Wilder's RMA ($\alpha = 1/14$):
   $$\text{ATR}_t = \frac{13 \cdot \text{ATR}_{t-1} + \text{TR}_t}{14}$$

### 3.5 Bollinger Bands (`BB(20, 2)`) & Bandwidth / `%B`
- Middle Band: $\mu_t = \text{SMA}_{20}(C)_t$
- Rolling Standard Deviation ($\text{ddof} = 0$):
  $$\sigma_t = \sqrt{\frac{1}{20}\sum_{i=0}^{19} (C_{t-i} - \mu_t)^2}$$
- Upper & Lower Bands:
  $$\text{Upper}_t = \mu_t + 2\sigma_t, \quad \text{Lower}_t = \mu_t - 2\sigma_t$$
- Percent B (`%B`) and Bandwidth:
  $$\%B_t = \frac{C_t - \text{Lower}_t}{\text{Upper}_t - \text{Lower}_t}, \quad \text{BW}_t = \frac{\text{Upper}_t - \text{Lower}_t}{\mu_t}$$

### 3.6 Anchored VWAP (`AVWAP`)
Given an anchor index $t_0$ and Typical Price $\text{TP}_i = \frac{H_i + L_i + C_i}{3}$:
$$\text{AVWAP}_t(t_0) = \frac{\sum_{i=t_0}^{t} \text{TP}_i \cdot V_i}{\sum_{i=t_0}^{t} V_i} \quad \text{for } t \ge t_0$$
Standard anchors:
1. **YTD Anchor**: First trading session of the current calendar year.
2. **52-Week High Anchor**: Date of highest high over the trailing 252 trading sessions.
3. **52-Week Low Anchor**: Date of lowest low over the trailing 252 trading sessions.
4. **Last Confirmed Swing Low Anchor**: Most recent causally confirmed 5-bar fractal swing low.

---

## 4. Causal Support/Resistance, Volume Profile & Trend Stage

### 4.1 Causal Fractal Swing Pivots & Support/Resistance (Zero Repaint)
- A bar at index $p$ is a **Swing High** of order $(L, R) = (5, 5)$ if:
  $$H_p = \max_{i \in [p-L, p+R]} H_i$$
- A bar at index $p$ is a **Swing Low** of order $(L, R) = (5, 5)$ if:
  $$L_p = \min_{i \in [p-L, p+R]} L_i$$
- **Strict No-Repaint Guarantee**: A swing pivot at index $p$ is **never emitted or known** until bar $p + R$ has closed (`confirmed_index = p + R`, `confirmed_date = date[p + R]`). Evaluating the detector on `df.iloc[:k]` never alters any pivot whose `confirmed_index < k`.
- Confirmed pivots over the trailing 252 sessions are clustered within a bandwidth of $0.75 \times \text{ATR}_{14}$ into horizontal Support and Resistance zones ranked by touch count and recency.

### 4.2 Volume Profile (`est. from daily bars`)
- Over the trailing 252 daily sessions, the price range $[\min(L), \max(H)]$ is partitioned into $B = 24$ uniform price bins.
- For each daily bar $t$, its volume $V_t$ is distributed uniformly across all price bins overlapped by $[L_t, H_t]$.
- **Point of Control (`POC`)**: Midpoint price of the bin with maximum accumulated volume.
- **Value Area (`VAH`, `VAL`)**: Contiguous bin interval around the POC containing $70\%$ of total traded volume.
- All UI surfaces label Volume Profile outputs **"est. from daily bars"** to distinguish daily-bar volume distribution from tick-level exchange order-book profiles.

### 4.3 Weinstein Stage & Minervini Trend Template (Preview)
- **Weinstein Stage (1–4)**: Determined from completed weekly bars using the 30-week SMA ($\approx 150$-day SMA) and its 4-week slope:
  - **Stage 2 (Advancing)**: Price $>$ 30W SMA and 30W SMA slope $> +0.15\%$ per week.
  - **Stage 4 (Declining)**: Price $<$ 30W SMA and 30W SMA slope $< -0.15\%$ per week.
  - **Stage 3 (Topping / Distribution)**: Prior trend advancing or elevated, price churning near/below flattening 30W SMA.
  - **Stage 1 (Basing / Accumulation)**: Prior trend declining or depressed, price consolidating near flattening 30W SMA.
- **Minervini 8-Point Trend Template**: Counts how many of the 8 canonical SEPA trend criteria are satisfied on daily bars (`C > SMA150`, `C > SMA200`, `SMA150 > SMA200`, `SMA200 rising >= 20 sessions`, `SMA50 > SMA150 & SMA200`, `C > SMA50`, `C >= 1.30 × 52W Low`, `C >= 0.75 × 52W High`).

---

## 5. Fixed-Risk Position Sizing Calculator

Given account capital $K$, risk budget fraction $r \in (0, 0.05]$, max portfolio weight cap $w_{\max} \in (0, 1]$, entry price $P_{\text{entry}}$, stop price $P_{\text{stop}}$, and round-trip transaction cost $c_{\text{bps}}$ (`10 bps` US, `30 bps` IN):
1. **Wrong-Side Stop Guardrail**: If $P_{\text{stop}} \ge P_{\text{entry}}$ or $P_{\text{stop}} \le 0$, position sizing is rejected with an explicit validation error.
2. **Friction-Adjusted Risk per Share**:
   $$P_{\text{entry}}^{\text{eff}} = P_{\text{entry}} \left(1 + \frac{c_{\text{bps}}}{20000}\right), \quad P_{\text{stop}}^{\text{eff}} = P_{\text{stop}} \left(1 - \frac{c_{\text{bps}}}{20000}\right)$$
   $$\text{Risk per Share} = P_{\text{entry}}^{\text{eff}} - P_{\text{stop}}^{\text{eff}}$$
3. **Whole-Share Quantity (Capped by Risk Budget & Max Weight)**:
   $$Q_{\text{risk}} = \left\lfloor \frac{K \cdot r}{\text{Risk per Share}} \right\rfloor, \quad Q_{\text{cap}} = \left\lfloor \frac{K \cdot w_{\max}}{P_{\text{entry}}^{\text{eff}}} \right\rfloor, \quad Q = \max(0, \min(Q_{\text{risk}}, Q_{\text{cap}}))$$

---

## 6. Label Qualification Policy (Decision D1)

To prevent confusion between DCF valuation signals and technical trend signals:
- Every fundamental verdict is explicitly prefixed: **`Valuation outlook: <STRONGLY BULLISH | BULLISH | NEUTRAL | BEARISH | STRONGLY BEARISH>`**.
- Every technical condition label is explicitly prefixed: **`Technical condition: <Bullish | Neutral | Bearish | Preview>`**.


---

## 11. Two-Stage Technical Composite Score (`ta-score-v0.2`)

### 11.1 Stage A — Indicator Standardization ($s_j \in [-1, +1]$)
One vote per concept across **6 fixed-weight pillars** (16 total indicators):

1. **Trend Structure ($W_{\text{Trend}} = 0.25$)**:
   - `ma_alignment` ($w = 0.40$): Mean of 4 binary pairwise votes ($\text{Price} > \text{SMA}_{20}$, $\text{SMA}_{20} > \text{SMA}_{50}$, $\text{SMA}_{50} > \text{SMA}_{200}$, $\text{Price} > \text{SMA}_{200}$) in $[-1, +1]$.
   - `sma200_slope` ($w = 0.30$): $\tanh(\Delta_{20}\%\text{SMA}_{200} / 2.0\%)$.
   - `adx_di` ($w = 0.30$): $\text{clamp}\!\left(\frac{+\text{DI}_{14} - -\text{DI}_{14}}{+\text{DI}_{14} + -\text{DI}_{14}} \cdot \min(1, \text{ADX}_{14}/30) \cdot 1.6, -1, 1\right)$.
2. **Momentum & Velocity ($W_{\text{Momentum}} = 0.15$)**:
   - `rsi_14` ($w = 0.40$): $\tanh((\text{RSI}_{14} - 50) / 18)$.
   - `macd_hist_slope` ($w = 0.35$): $\tanh(1.2 \cdot \frac{\text{Hist}}{\text{ATR}_{14}} + 1.5 \cdot \frac{\Delta_3\text{Hist}}{\text{ATR}_{14}})$.
   - `roc_63` ($w = 0.25$): $\tanh(\text{ROC}_{63}\% / 15\%)$.
3. **Volatility & Compression ($W_{\text{Volatility}} = 0.10$)**:
   - `bb_pct_b` ($w = 0.50$): $\text{clamp}(2 \cdot (\%B - 0.50), -1, 1)$.
   - `ttm_squeeze` ($w = 0.50$): $\text{clamp}(\tanh(0.8 \cdot \text{Mom}_{\text{ATR}}) \cdot m_{\text{sqz}}, -1, 1)$ where $m_{\text{sqz}} = 1.25$ on squeeze release, $0.75$ while squeeze is active, $1.0$ otherwise.
4. **Institutional Volume Flow ($W_{\text{Volume}} = 0.20$)**:
   - `obv_slope_t` ($w = 0.40$): $\tanh(t_{\text{OLS}}(\text{OBV}_{20}) / 2.5)$.
   - `cmf_20` ($w = 0.30$): $\text{clamp}(\text{CMF}_{20} / 0.25, -1, 1)$.
   - `up_down_vol` ($w = 0.30$): $\tanh(\ln(\text{UpVol}_{50} / \text{DownVol}_{50}) / 0.45)$.
5. **Benchmark Relative Strength ($W_{\text{RS}} = 0.15$)**:
   - `mansfield_rs` ($w = 0.60$): $\tanh(\text{Mansfield RS} / 10.0)$ where $\text{Mansfield RS}_t = 100 \cdot (\text{RS}_t / \text{SMA}_{252}(\text{RS})_t - 1)$.
   - `alpha_63d_tstat` ($w = 0.40$): $\tanh(t_{\alpha, 63\text{D}} / 2.0)$.
6. **Stage & Volume Acceptance ($W_{\text{Structure}} = 0.15$)**:
   - `weinstein_stage` ($w = 0.40$): Stage $2 \to +1.00$, Stage $1 \to +0.15$, Stage $3 \to -0.35$, Stage $4 \to -1.00$.
   - `minervini_template` ($w = 0.30$): $2 \cdot (\text{Passed}/8) - 1$.
   - `vp_position` ($w = 0.30$): $> \text{VAH} \to +0.90$, $[\text{POC}, \text{VAH}] \to +0.45$, $[\text{VAL}, \text{POC}) \to -0.35$, $< \text{VAL} \to -0.85$.

### 11.2 Stage B — Pillar Aggregation, Multi-Timeframe & Coverage Gate
- **Coverage Gate**: Every pillar $k$ requires $\ge 60\%$ of its indicator weight available and total available weight $\sum_k W_k c_k \ge 70\%$. Otherwise the score is suppressed and displays `"Score unavailable (coverage X%)"`.
- **Single-Timeframe Score**:
  $$S_{tf} = 100 \sum_{k=1}^6 W_k \left(\frac{P_k + 1}{2}\right) \in [0, 100]$$
- **Multi-Timeframe Composite Score** (completed weekly and monthly bars only):
  $$S_{\text{MTF}} = 0.50 \cdot S_D + 0.35 \cdot S_W + 0.15 \cdot S_M$$
- **Qualified Labels**:
  - $S_{\text{MTF}} \ge 60.0 \implies \text{"Technical condition: Bullish"}$
  - $40.0 < S_{\text{MTF}} < 60.0 \implies \text{"Technical condition: Neutral"}$
  - $S_{\text{MTF}} \le 40.0 \implies \text{"Technical condition: Bearish"}$

---

## 12. Statistical Regime Diagnostics (Reported Separately)

1. **Hurst Exponent via Detrended Fluctuation Analysis (`DFA-1`)**:
   - Computed over $N = 504$ daily total-return log returns across scales $s \in [10, 126]$.
   - Moving-block bootstrap ($B = 120$, block length $20$) 95% confidence interval.
   - Reports `"Indeterminate (95% CI spans 0.50)"` whenever $0.50 \in [\text{CI}_{2.5\%}, \text{CI}_{97.5\%}]$, with a 10-day hysteresis check.
2. **Lo–MacKinlay Variance Ratio Test (`VR(2, 5, 10, 20)`) & Chow–Denning Joint Test**:
   - Heteroskedasticity-robust $z^*(q)$ test statistic for $q \in \{2, 5, 10, 20\}$.
   - Joint statistic $CD^* = \max_q |z^*(q)|$ evaluated against the 95% Studentized Maximum Modulus critical value $\text{SMM}_{0.05, k=4, \infty} = 2.491$.
3. **Yang–Zhang Realized Volatility (`20D` / `60D`)**:
   - Minimum-variance unbiased estimator combining overnight ($\ln(O_t/C_{t-1})$), open-to-close ($\ln(C_t/O_t)$), and Rogers–Satchell variance, annualized ($\times \sqrt{252}$) in `% annualized`, with `1Y` (`252D`) and `5Y` (`1260D`) empirical percentiles.

---

## 13. 3×4 Fundamental × Weinstein Stage Classification Matrix (R6)

- **Rows**: Live Fundamental Valuation Outlook (`Bullish` [incl. Strongly Bullish], `Neutral`, `Bearish` [incl. Strongly Bearish], plus a greyed `Valuation Unreliable / Distressed` row that activates only when DCF is flagged distressed).
- **Columns**: Completed-weekly Weinstein Stage 1 (`Basing`), Stage 2 (`Advancing`), Stage 3 (`Topping`), Stage 4 (`Declining`).
- Strictly descriptive, non-prescriptive cell classification (e.g., `"Bullish Valuation · Stage 4 Declining — Possible Value Trap · Trend Unconfirmed"`).

---

## 14. Per-Stock Signal Backtester (`ta-backtest-v0.3`)

### 14.1 Zero Look-Ahead Execution Contract
- **Signal Observation**: Every signal rule is evaluated strictly on confirmed daily bar close $t$ using data up to and including index $t$ (`ohlc_tr[:t+1]`).
- **Entry Fill**: Next trading session's total-return open:
  $$\text{Entry}(t) = \text{Open}_{\text{tr}}[t + 1]$$
- **Exit Fill**: Total-return close after $h \in \{5, 10, 20, 60\}$ trading days:
  $$\text{Exit}(t, h) = \text{Close}_{\text{tr}}[t + h]$$
- **Unfinished Horizons**: Any signal trigger where $t + h \ge N$ is excluded from completed trade statistics and surfaced separately in `pending_signals`.
- **Transaction Costs**: Default round-trip friction is `10 bps` (`0.10%`, `US`) and `30 bps` (`0.30%`, `IN`), user-editable in `[0, 500]` bps. Both Gross and Net returns are reported:
  $$R_{\text{gross}}(t, h) = d \cdot \left(\frac{\text{Close}_{\text{tr}}[t + h]}{\text{Open}_{\text{tr}}[t + 1]} - 1\right), \quad R_{\text{net}}(t, h) = R_{\text{gross}}(t, h) - \frac{\text{cost\_bps}}{10000}$$

### 14.2 20-Bar Causal De-Clustering & 70/30 Chronological Sample Split
- **De-Clustering**: Consecutive triggers within a 20-trading-day cooldown window are suppressed causally ($t_{\text{next}} - t_{\text{last\_accepted}} \ge 20$). Both raw trigger counts (`n_raw`) and de-clustered trigger counts (`n_declustered`) are reported.
- **Sample Split**: The historical bar index is split chronologically at $\lfloor 0.70 \cdot N \rfloor$:
  - **In-Sample (`IS`)**: First 70% of daily bars ($t < \lfloor 0.70 \cdot N \rfloor$).
  - **Out-of-Sample (`OOS`)**: Final 30% of daily bars ($t \ge \lfloor 0.70 \cdot N \rfloor$).
  - Signal parameters are canonical and frozen; no parameter optimization is performed.

### 14.3 The 10 Frozen Signal Definitions ($\times 4\text{ Horizons} = 40\text{ Tests}$)
1. **`rsi_oversold_recovery`** (`Long +1`): Wilder $\text{RSI}(14)_{t-1} \le 30$ and $\text{RSI}(14)_t > 30$.
2. **`rsi_70_continuation`** (`Long +1`): Wilder $\text{RSI}(14)_{t-1} < 70$ and $\text{RSI}(14)_t \ge 70$ (momentum breakout continuation hypothesis).
3. **`rsi_70_reversal`** (`Inverse -1`): Wilder $\text{RSI}(14)_{t-1} \ge 70$ and $\text{RSI}(14)_t < 70$ (overbought mean-reversion hypothesis).
4. **`macd_bull_cross_below_zero`** (`Long +1`): $\text{MACD}(12,26,9)_{t-1} \le \text{Signal}_{t-1}$, $\text{MACD}_t > \text{Signal}_t$, and $\text{MACD}_t < 0$.
5. **`golden_cross_50_200`** (`Long +1`): $\text{SMA}_{50, t-1} \le \text{SMA}_{200, t-1}$ and $\text{SMA}_{50, t} > \text{SMA}_{200, t}$.
6. **`supertrend_bull_flip`** (`Long +1`): Causal $\text{Supertrend}(10, 3.0)$ direction flips from $-1$ at $t-1$ to $+1$ at $t$.
7. **`ttm_squeeze_bull_release`** (`Long +1`): Bollinger $(20, 2.0)$ exits Keltner $(\text{EMA}_{20} \pm 1.5 \cdot \text{ATR}_{14})$ compression at bar $t$ with positive midline momentum.
8. **`dma_50_200_pullback`** (`Long +1`): In an uptrend ($C_t > \text{SMA}_{200, t}$ and $\text{SMA}_{50, t} > \text{SMA}_{200, t}$), $L_t$ tests within $1\%$ of $\text{SMA}_{50, t}$ (or $\text{SMA}_{200, t}$) and $C_t$ closes back above the tested moving average.
9. **`breakout_52w_high_vol`** (`Long +1`): $C_t > \max_{s \in [t-252, t-1]} H_s$ on $\text{Volume}_t \ge 1.5 \times \text{SMA}_{20}(\text{Volume})_t$.
10. **`bollinger_lower_reentry`** (`Long +1`): $C_{t-1} < \text{BB}_{\text{lower}}(20, 2.0)_{t-1}$ and $C_t \ge \text{BB}_{\text{lower}}(20, 2.0)_t$.

### 14.4 Statistical Inference, Multiple-Testing Control & Labeling
- **Excess Returns**: Reported both against unconditional $h$-day stock drift ($\bar{R}_{\text{uncond}}(h)$) and against matched $[t+1, t+h]$ benchmark returns (`^NSEI` / `^GSPC`).
- **Win Rate CI**: Exact Wilson score 95% confidence interval on net win proportion.
- **Bootstrap Inference**: Moving-block bootstrap ($B = 1000$, block length $\lceil h / 20 \rceil$) 95% confidence interval and two-sided $p$-value on in-sample net excess return.
- **False Discovery Rate**: Benjamini–Hochberg (`BH-FDR`) step-up adjusted $q$-values across all $M = 40$ tests jointly.
- **Path Excursions**: Median and P90 Maximum Adverse Excursion (`MAE` $\le 0$) and Maximum Favorable Excursion (`MFE` $\ge 0$) over $[t+1, t+h]$.
- **Non-Promotional Classification Rules**:
  - `N_IS < 15`: `"Insufficient evidence"`
  - `net_excess_is > 0`, 95% bootstrap CI excludes $0$, $q < 0.10$, **and** `net_excess_oos > 0` (matching positive sign out-of-sample): `"Historically favourable"`
  - Otherwise: `"No reliable edge"`
  - Promotional words (`"buy"`, `"sell"`, `"profitable"`) are strictly banned. Every backtest view includes an explicit survivorship-bias and single-security look-back disclosure.

