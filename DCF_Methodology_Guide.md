# ValuationLab: DCF & Monte Carlo Methodology Guide

This document outlines the exact mathematical pipelines, data extraction protocols, and assumptions used by the ValuationLab backend engine to calculate the intrinsic fair value of a company.

---

## 1. Data Ingestion & Historical Normalization
The engine fetches consolidated financial statements (Income Statement, Balance Sheet, Cash Flow) via `yfinance`. To guarantee data integrity, it cross-intersects the reporting dates across all three statements, ensuring that all metrics belong to the exact same fiscal period.

The engine calculates historical averages over the last 4 years to establish baseline assumptions:
*   **Revenue Growth**: Compound Annual Growth Rate (CAGR) or average YoY growth.
*   **EBIT Margin**: Average `Operating Income / Total Revenue`.
*   **D&A Intensity**: Average `Depreciation & Amortization / Total Revenue`.
*   **CapEx Intensity**: Average `Capital Expenditure / Total Revenue` (using normalized positive values).
*   **Net Working Capital (NWC) Ratio**: Average `(Current Assets - Cash) - (Current Liabilities - Short Term Debt) / Total Revenue`.

---

## 2. Cost of Capital (WACC)
The engine calculates the Weighted Average Cost of Capital (WACC) dynamically based on real-time market data.

### A. Cost of Equity ($K_e$)
Uses the Capital Asset Pricing Model (CAPM):
$$K_e = R_f + \beta \times ERP$$
*   **Risk-Free Rate ($R_f$)**: Fetched directly from the Federal Reserve Economic Data (FRED) API. Uses the 10-Year US Treasury yield for US equities, or the India 10-Year Government Bond yield for Indian equities.
*   **Beta ($\beta$)**: Fetched from Yahoo Finance (5-year monthly).
*   **Equity Risk Premium (ERP)**: Market-specific default (e.g., 5.0% for US, 7.0% for India).

### B. Cost of Debt ($K_d$)
$$K_d = \frac{\text{Interest Expense}}{\text{Total Debt}}$$
*   The raw cost of debt is floored at 4.0% to prevent anomalous zero-debt edge cases.
*   **After-Tax Cost of Debt**: $K_d \times (1 - T)$, where $T$ is the statutory corporate tax rate (21% for US, 25.17% for India).

### C. Weights & WACC
*   **Weight of Equity ($W_e$)**: $\frac{\text{Market Cap}}{\text{Market Cap} + \text{Total Debt}}$
*   **Weight of Debt ($W_d$)**: $\frac{\text{Total Debt}}{\text{Market Cap} + \text{Total Debt}}$
*   **Final WACC**: $(W_e \times K_e) + (W_d \times \text{After-Tax } K_d)$

---

## 3. Projected Free Cash Flows (5-Year Stage)
The engine projects the Unlevered Free Cash Flow (UFCF) for 5 years.

**1. Revenue Projection:**
Revenue grows at the user-defined `start_growth` rate in Year 1. This growth rate fades *linearly* over 5 years until it converges with the `terminal_growth` rate (default 2.5%) in Year 5.

**2. Operating Profit (NOPAT):**
$$EBIT_t = Revenue_t \times Margin_t$$
$$NOPAT_t = EBIT_t \times (1 - \text{Tax Rate})$$
*(Note: If historical margins are negative, the engine linearly interpolates them toward a target breakeven/positive margin over the 5 years).*

**3. Reinvestment (CapEx, D&A, NWC):**
*   **D&A**: $Revenue_t \times \text{Historical D\&A Intensity}$
*   **CapEx**: $Revenue_t \times \text{Historical CapEx Intensity}$
*   **Change in NWC ($\Delta NWC_t$)**: Calculated incrementally to prevent extreme swings.
    $$\Delta NWC_t = \text{Normalized NWC Ratio} \times (Revenue_t - Revenue_{t-1})$$

**4. Unlevered Free Cash Flow (UFCF):**
$$UFCF_t = NOPAT_t + D\&A_t - CapEx_t - \Delta NWC_t$$

**5. Present Value:**
Each year's UFCF is discounted back to today:
$$PV(\text{UFCF}_t) = \frac{UFCF_t}{(1 + WACC)^t}$$

---

## 4. Terminal Value
The engine assumes the company operates in perpetuity after Year 5, using the **Gordon Growth Model**.

$$TV = \frac{UFCF_5 \times (1 + g)}{WACC - g}$$
Where $g$ is the Terminal Growth Rate (default 2.5%, roughly aligned with long-term GDP growth/inflation).

**Safety Validations:**
1. If $WACC \le g$, the Gordon Growth Model mathematically breaks (yielding an infinite value). The engine voids the terminal value.
2. If $UFCF_5 \le 0$, a perpetual growth model cannot be applied to a cash-burning state. The engine voids the terminal value.

The Terminal Value is discounted to present value:
$$PV(TV) = \frac{TV}{(1 + WACC)^5}$$

---

## 5. The Enterprise-to-Equity Bridge
The engine bridges the operating Enterprise Value (EV) to the final shareholder Equity Value.

$$Enterprise Value (EV) = \sum PV(UFCF) + PV(TV)$$

$$Equity Value = EV + \text{Liquid Assets} - \text{Total Debt}$$

*   **Liquid Assets**: Explicitly includes both *Cash & Cash Equivalents* AND *Other Short-Term Investments (Marketable Securities)*.
*   **Total Debt**: Explicitly includes Short-Term Debt, Long-Term Debt, AND *Capital Lease Obligations*.

**Final Implied Share Price:**
$$\text{Share Price} = \max\left(0, \frac{\text{Equity Value}}{\text{Shares Outstanding}}\right)$$
*(If the company's EV is insufficient to cover its Net Debt, the Equity Value is negative. Since stockholders have limited liability, the share price is floored at ₹0.00).*

---

## 6. Monte Carlo Simulation Engine
Because DCFs are highly sensitive to small assumption changes, the platform runs a **10,000-iteration Monte Carlo simulation** to map the probability distribution of fair values.

**1. The Sampling Pipeline:**
*   The engine sets a target of 10,000 valid simulations.
*   It draws **30,000** initial samples (a 3x oversample) from Gaussian (Normal) distributions for:
    *   Revenue Growth
    *   EBIT Margin
    *   WACC (via underlying Risk-Free Rate, ERP, Cost of Debt variations)

**2. Rejection Filtering:**
The engine discards "economically invalid" parallel universes. For example:
*   Simulations where $WACC \le \text{Terminal Growth}$.
*   Simulations where Cost of Debt goes negative.

**3. Execution & Percentiles:**
*   The engine truncates the surviving valid samples down to exactly 10,000.
*   It runs the entire 5-stage DCF algorithm 10,000 separate times.
*   The results are sorted into percentiles (P5, P25, Median, P75, P95).
*   **Verdict Generation**: If the current market price is below P25, it is a BUY. If it is below P5, it is a STRONG BUY. If it exceeds P75/P95, it is a SELL / STRONG SELL. If the median is ₹0 due to overwhelming bankruptcy/debt risk, the verdict safely outputs "N/A" to prevent false signals.
