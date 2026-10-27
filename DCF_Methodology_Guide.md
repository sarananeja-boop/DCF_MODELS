# ValuationLab: Quantitative DCF & Stochastic Monte Carlo Methodology

**Version 2.0 · Institutional Valuation Whitepaper**  
**Author:** Sarandeep Aneja  
**Coverage:** Cross-Border Equities (NSE/BSE India & NYSE/NASDAQ United States)  
**Engines:** 5-Year Unlevered FCFF Engine, Tier-1 Capital FCFE Banking Engine, Cholesky Correlated Monte Carlo

---

## 1. Executive Summary & Mathematical Foundations

ValuationLab implements an institutional fundamental equity research architecture designed to price operating businesses strictly from first principles. Rather than relying on static single-point price targets or heuristic multiples, the platform separates corporate operations into:

1. **Operating Cash Flow Generation:** Deterministic multi-stage discounting of distributable cash.
2. **Dynamic Capital Pricing:** Time-varying Cost of Capital (WACC / CAPM) anchored to live sovereign debt curves.
3. **Stochastic Macro Stress-Testing:** 10,000-scenario correlated Monte Carlo simulations via Cholesky decomposition of historical covariance structures.
4. **Dual-Track Industry Routing:** Automatic detection and algorithmic branching between non-financial operating firms (Unlevered FCFF) and regulated financial institutions (Tier-1 Regulatory Capital FCFE).

```
                                  [Ticker Ingestion]
                                          │
                  ┌───────────────────────┴───────────────────────┐
                  ▼                                               ▼
       [Non-Financial Corporates]                     [Banks & Lending NBFCs]
                  │                                               │
    ┌─────────────┴─────────────┐                   ┌─────────────┴─────────────┐
    ▼                           ▼                   ▼                           ▼
[Live FRED / RBI]      [Tri-Statement Date]   [Live RBI / FRED]      [Tier-1 Regulatory]
[Risk-Free Yields]     [Reconciliation]       [Sovereign Yield]      [Capital Adequacy]
    │                           │                   │                           │
    ▼                           ▼                   ▼                           ▼
[CAPM & Dynamic WACC]  [5-Yr Unlevered FCFF]  [Cost of Equity Ke]    [Regulatory FCFE]
    │                           │                   │                           │
    └─────────────┬─────────────┘                   └─────────────┬─────────────┘
                  │                                               │
                  ▼                                               ▼
     [Gordon Growth Terminal EV]                    [Justified P/B Terminal Eq]
                  │                                               │
                  ▼                                               ▼
     [Enterprise-to-Equity Bridge]                  [Direct Equity Value (P0)]
                  │                                               │
                  └───────────────────────┬───────────────────────┘
                                          │
                                          ▼
                      [7-Variable Covariance Matrix (Σ)]
                                          │
                                          ▼
                        [Cholesky Factorization: LLᵀ = Σ]
                                          │
                                          ▼
                      [10,000 Heavy-Tailed Student's t Runs]
                                          │
                                          ▼
                  [Empirical Distribution: P5, P25, Median, P75, P95]
```

---

## 2. Cross-Border Macroeconomic & Statutory Architectures

ValuationLab treats capital structures differently based on domestic legal, taxation, and sovereign monetary environments. The platform cross-references live macroeconomic feeds with statutory parameters for Indian and US capital markets:

| Parameter | Indian Equities (NSE / BSE) | US Equities (NYSE / NASDAQ) | Mathematical Derivation / Feed |
| :--- | :--- | :--- | :--- |
| **Sovereign Risk-Free Rate ($R_f$)** | RBI 10-Year Benchmark G-Sec Yield | US 10-Year Treasury Yield | Live FRED API (`DGS10` / `INDIRLTLT01STM`) |
| **Market Equity Risk Premium ($ERP$)** | $7.00\%$ | $5.00\%$ | Damodaran Mature Market + Sovereign CDS Spread |
| **Corporate Income Tax Rate ($\tau$)** | $25.17\%$ | $21.00\%$ | Sec. 115BAA (22% + 10% Surcharge + 4% Cess) vs. US TCJA |
| **Perpetual Terminal Growth Rate ($g_{\infty}$)** | $2.50\%$ (Real Conservative Default) | $2.50\%$ (Real Conservative Default) | $\min(\text{Historical GDP Trend}, R_f - 1.5\%)$ |
| **Reporting Currency** | Indian Rupee (₹ INR Crores) | US Dollar ($ USD Millions) | Local Filing Denomination |
| **Statement Standard** | Ind AS / IFRS Consolidated | US GAAP / SEC 10-K Consolidated | Standardized Audited Primary Filings |

---

## 3. Data Cleaning, Tri-Statement Date Intersection & Normalization

Raw financial filings often contain trailing twelve-month (TTM) calendar misalignments, restated line items, and non-recurring operational distortions. To ensure quantitative integrity, ValuationLab executes a rigorous tri-statement intersection pipeline:

### 3.1 Date-Intersection Protocol
Let $\mathcal{D}_I$, $\mathcal{D}_B$, and $\mathcal{D}_C$ represent the set of fiscal reporting dates available in the Income Statement, Balance Sheet, and Cash Flow Statement, respectively:

$$\mathcal{D}_{\text{valid}} = \mathcal{D}_I \cap \mathcal{D}_B \cap \mathcal{D}_C$$

Only fiscal years $t \in \mathcal{D}_{\text{valid}}$ are retained for historical parameter estimation (minimum 3 years, default 4 years). If date intersection yields fewer than 3 concurrent fiscal periods, the engine flags data insufficiency.

### 3.2 Normalized Operational Ratios
The baseline historical parameters are calculated as weighted averages over the historical window:

1. **Historical Revenue Compound Annual Growth Rate ($CAGR_H$):**
   $$CAGR_H = \left(\frac{\text{Revenue}_0}{\text{Revenue}_{-k}}\right)^{\frac{1}{k}} - 1$$

2. **Normalized Operating Margin ($\mu^*$):**
   $$\mu^* = \frac{1}{k} \sum_{t=-k}^0 \left(\frac{\text{EBIT}_t}{\text{Revenue}_t}\right)$$

3. **Depreciation and Amortization Intensity ($\delta^*$):**
   $$\delta^* = \frac{1}{k} \sum_{t=-k}^0 \left(\frac{\text{DA}_t}{\text{Revenue}_t}\right)$$

4. **Capital Expenditure Intensity ($\kappa^*$):**
   $$\kappa^* = \frac{1}{k} \sum_{t=-k}^0 \left(\frac{\text{CapEx}_t}{\text{Revenue}_t}\right)$$

5. **Net Working Capital Ratio ($\omega^*$):**
   $$\text{NWC}_t = (\text{Current Assets}_t - \text{Cash}_t) - (\text{Current Liabilities}_t - \text{Short-Term Debt}_t)$$
   $$\omega^* = \frac{1}{k} \sum_{t=-k}^0 \left(\frac{\text{NWC}_t}{\text{Revenue}_t}\right)$$

---

## 4. Cost of Capital Architecture (Dynamic WACC & CAPM)

The discount rate represents the opportunity cost of all capital providers, incorporating both market risk and debt capital distress structures.

```
            Cost of Equity (Ke)                    After-Tax Cost of Debt (Kd)
     ┌───────────────────────────────┐          ┌───────────────────────────────┐
     │ Ke = Rf + β × ERP             │          │ Synthetic ICR = EBIT / IntExp │
     │  - Rf: Live FRED / RBI 10Y    │          │ Credit Rating: Damodaran Table│
     │  - β:  Cov(Ri, Rm) / Var(Rm)  │          │ Kd = Rf + Spread              │
     │  - ERP: 5.0% (US) / 7.0% (IN) │          │ After-Tax = Kd × (1 - τ)      │
     └───────────────┬───────────────┘          └───────────────┬───────────────┘
                     │                                          │
                     ▼                                          ▼
            Weight of Equity (We)                      Weight of Debt (Wd)
             We = E / (D + E)                           Wd = D / (D + E)
                     │                                          │
                     └───────────────────┬──────────────────────┘
                                         │
                                         ▼
                                   [Blended WACC]
                        WACC = (We × Ke) + (Wd × Kd × (1 - τ))
```

### 4.1 Cost of Equity ($K_e$) via Modern Portfolio Theory
$$K_e = R_f + \beta_L \times ERP$$

Where $\beta_L$ is the levered equity beta estimated against the local market benchmark index (NIFTY 50 / S&P 500). If capital structure adjustments are applied, beta is unlevered and relevered via the Hamada equation:

$$\beta_U = \frac{\beta_L}{1 + (1 - \tau) \frac{D}{E}}$$
$$\beta_L^* = \beta_U \left[1 + (1 - \tau) \frac{D^*}{E^*}\right]$$

### 4.2 Synthetic Debt Rating & Cost of Debt ($K_d$)
For non-rated and mid-cap companies, book interest rates can be distorted by legacy debt or zero-interest promoter loans. ValuationLab computes a synthetic credit rating by evaluating the company's Interest Coverage Ratio ($ICR$):

$$ICR = \frac{\text{EBIT}_0}{\text{Interest Expense}_0}$$

The synthetic rating determines the default credit spread over the risk-free anchor:

| Interest Coverage Ratio (Large Cap) | Synthetic Rating | Default Spread ($\Delta_{\text{spread}}$) |
| :--- | :--- | :--- |
| $> 8.50\times$ | AAA | $+0.63\%$ |
| $6.50\times - 8.50\times$ | AA | $+0.78\%$ |
| $4.25\times - 6.50\times$ | A | $+1.08\%$ |
| $3.00\times - 4.25\times$ | BBB | $+1.56\%$ |
| $2.50\times - 3.00\times$ | BB | $+2.40\%$ |
| $2.00\times - 2.50\times$ | B | $+3.60\%$ |
| $1.25\times - 2.00\times$ | CCC | $+6.00\%$ |
| $< 1.25\times$ | D / Distressed | $+9.00\%$ |

The nominal pre-tax cost of debt is floored at $4.00\%$:

$$K_d = \max\left(0.04,\, R_f + \Delta_{\text{spread}}\right)$$
$$\text{After-Tax } K_d = K_d \times (1 - \tau)$$

### 4.3 Capital Structure Weights & Blended WACC
Market capitalization ($E = P_0 \times \text{Shares Outstanding}$) and Total Debt ($D = \text{Short-Term Debt} + \text{Long-Term Debt} + \text{Capital Leases}$) define the market value capital weights:

$$W_e = \frac{E}{D + E}, \quad W_d = \frac{D}{D + E}$$
$$WACC = \left(W_e \times K_e\right) + \left(W_d \times K_d \times (1 - \tau)\right)$$

### 4.4 Mid-Year Discounting Convention
Because businesses generate free cash flow continuously throughout the fiscal year rather than on December 31, year-end discounting systematically underestimates intrinsic value. ValuationLab applies the mid-year discount convention:

$$DF_t = \frac{1}{(1 + WACC)^{t - 0.5}} \quad \text{for } t \in \{1, 2, 3, 4, 5\}$$

---

## 5. Non-Financial Corporate Pipeline: 5-Year Unlevered FCFF Engine

For industrial, consumer, technology, energy, and healthcare companies, ValuationLab discounts Unlevered Free Cash Flow to Firm (FCFF).

### 5.1 Linear Growth Decay & Margin Normalization
High initial growth decays linearly toward the long-term sustainable terminal rate to avoid compound runaway projections:

$$g_t = g_{\text{start}} - \left(\frac{g_{\text{start}} - g_{\infty}}{5}\right) \times (t - 1)$$
$$\text{Revenue}_t = \text{Revenue}_{t-1} \times (1 + g_t)$$

Operating EBIT margins linearly converge toward historical normalized efficiency:

$$\mu_t = \mu_0 + \left(\frac{\mu^* - \mu_0}{5}\right) \times t$$
$$\text{EBIT}_t = \text{Revenue}_t \times \mu_t$$

### 5.2 Distributable Cash Flow Formulation
$$\text{NOPAT}_t = \text{EBIT}_t \times (1 - \tau)$$
$$\text{DA}_t = \text{Revenue}_t \times \delta^*$$
$$\text{CapEx}_t = \text{Revenue}_t \times \kappa^*$$
$$\Delta\text{NWC}_t = \omega^* \times (\text{Revenue}_t - \text{Revenue}_{t-1})$$

$$\text{FCFF}_t = \text{NOPAT}_t + \text{DA}_t - \text{CapEx}_t - \Delta\text{NWC}_t$$

### 5.3 Gordon Growth Terminal Value ($TV_5$)
At the end of Year 5, the firm is assumed to achieve mature stable growth in perpetuity:

$$TV_5 = \frac{\text{FCFF}_5 \times (1 + g_{\infty})}{WACC - g_{\infty}}$$

**Mathematical Safety Constraints:**
1. If $WACC \le g_{\infty}$, the Gordon Growth denominator becomes non-positive ($\le 0$), which violates economic stability. In this regime, the terminal value is mathematically voided.
2. If $\text{FCFF}_5 \le 0$, a perpetual growth model cannot be compounded on negative cash flow; terminal value is suppressed.

The terminal value is discounted to present value using the full 5-year factor:

$$PV(TV_5) = \frac{TV_5}{(1 + WACC)^5}$$

### 5.4 Enterprise-to-Equity Bridge
Operating Enterprise Value ($EV$) equals the sum of discounted explicit cash flows plus discounted terminal value:

$$EV = \sum_{t=1}^5 \left(\text{FCFF}_t \times DF_t\right) + PV(TV_5)$$

To bridge Enterprise Value to Shareholder Equity Value ($P_0$):

$$\text{Equity Value} = EV + \text{Cash} + \text{Marketable Securities} - \text{Total Debt} - \text{Lease Obligations} - \text{Minority Interest}$$

$$\text{Implied Per-Share Fair Value} = \max\left(0,\, \frac{\text{Equity Value}}{\text{Shares Outstanding}}\right)$$

*(If debt exceeds enterprise value, shareholder liability is legally bounded at zero).*

---

## 6. Financial Institutions Pipeline: Tier-1 Regulatory Capital FCFE Engine

Commercial banks, lending NBFCs, and financial institutions cannot be valued using FCFF or WACC because:
1. Customer deposits and short-term debt are **operational working capital**, not capital structure financing.
2. Interest income and interest expense are primary operating revenues and costs.
3. Balance sheet growth is strictly governed by **Reserve Bank of India (RBI)** or **Federal Reserve (Basel III)** Tier-1 Capital Adequacy Ratios ($CAR$).

```
                      [Commercial Bank / Lending NBFC]
                                      │
              ┌───────────────────────┴───────────────────────┐
              ▼                                               ▼
   [Operating Net Income]                           [Regulatory Equity]
   Net Interest Income - Provisions                 Risk-Weighted Assets × CET1
              │                                               │
              └───────────────────────┬───────────────────────┘
                                      │
                                      ▼
                      [Free Cash Flow to Equity (FCFE)]
                      FCFE = Net Income - ΔRegulatory Equity
                                      │
                                      ▼
                      [Cost of Equity Discounting: Ke]
                      PV(FCFE) discounted at Ke (100% Equity)
                                      │
                                      ▼
                      [Justified P/B Terminal Value]
                      P/B = (ROE - g) / (Ke - g)
                      TV_Equity = Book Value_5 × (P/B)
```

### 6.1 Regulatory Capital Formation & FCFE Derivation
For banks, distributable cash is Free Cash Flow to Equity ($FCFE$):

$$\text{Regulatory Equity}_t = \text{Risk-Weighted Assets}_t \times \text{Target CET1 Ratio}$$
$$\Delta\text{Regulatory Equity}_t = \text{Regulatory Equity}_t - \text{Regulatory Equity}_{t-1}$$
$$\text{FCFE}_t = \text{Net Income}_t - \Delta\text{Regulatory Equity}_t$$

### 6.2 Sustainable ROE Justified Price-to-Book Terminal Value
Terminal equity value is anchored to the institution's sustainable Return on Equity ($ROE$) relative to its Cost of Equity ($K_e$):

$$\text{Justified } \frac{P}{B} = \frac{ROE - g_{\infty}}{K_e - g_{\infty}}$$
$$TV_{\text{Equity}} = \text{Book Value}_5 \times \left(\frac{ROE - g_{\infty}}{K_e - g_{\infty}}\right)$$

$$\text{Bank Equity Value} = \sum_{t=1}^5 \frac{\text{FCFE}_t}{(1 + K_e)^{t - 0.5}} + \frac{TV_{\text{Equity}}}{(1 + K_e)^5}$$

---

## 7. Stochastic Monte Carlo Engine: Cholesky Covariance Decomposition

Traditional sensitivity tables alter only one or two variables independently in isolation, ignoring macroeconomic correlations (e.g., when risk-free rates rise, borrowing costs surge and valuation multiples contract). 

ValuationLab resolves this by deploying a **10,000-iteration correlated stochastic simulation engine** governed by Cholesky factorization.

```
       [Historical Financials & Macro Feeds]
                         │
                         ▼
     [7-Variable Covariance Matrix Construction: Σ]
       - Revenue Growth               - Equity Risk Premium
       - Operating EBIT Margin        - Synthetic Cost of Debt
       - Risk-Free Rate (Rf)          - Terminal Growth Rate
       - Levered Beta
                         │
                         ▼
     [Cholesky Factorization: Σ = L · Lᵀ]
       L = Lower triangular square-root matrix
                         │
                         ▼
     [Correlated Shock Vector Generation]
       Z ~ Student's t (ν = 5 d.o.f., Heavy-Tailed Fat Shocks)
       X = μ + L · Z
                         │
                         ▼
     [Oversampling Pipeline: 30,000 Raw Worlds]
                         │
                         ▼
     [Strict Economic Sanity Filters]
       ❌ Discard: WACC ≤ g_infinity
       ❌ Discard: Kd < 0 or Ke < Rf
       ❌ Discard: Margins > 95% or Negative Borrowing Spreads
                         │
                         ▼
     [Truncation to Exactly 10,000 Verified Converged Trials]
                         │
                         ▼
     [DCF Pipeline Execution across all 10,000 Worlds]
                         │
                         ▼
     [Empirical Valuation Distribution: P5, P25, Median, P75, P95]
```

### 7.1 The 7-Variable Covariance Matrix ($\Sigma$)
The engine models the joint distribution of seven economic variables:
$$\mathbf{Y} = \begin{bmatrix} g_{\text{start}} & \mu_{\text{target}} & R_f & \beta & ERP & K_d & g_{\infty} \end{bmatrix}^T$$

Historical variances and empirical correlations populate the symmetric positive semi-definite covariance matrix $\Sigma$:

$$\Sigma = \begin{bmatrix}
\sigma_1^2 & \rho_{1,2}\sigma_1\sigma_2 & \cdots & \rho_{1,7}\sigma_1\sigma_7 \\
\rho_{2,1}\sigma_2\sigma_1 & \sigma_2^2 & \cdots & \rho_{2,7}\sigma_2\sigma_7 \\
\vdots & \vdots & \ddots & \vdots \\
\rho_{7,1}\sigma_7\sigma_1 & \rho_{7,2}\sigma_7\sigma_2 & \cdots & \sigma_7^2
\end{bmatrix}$$

### 7.2 Cholesky Decomposition ($L L^T = \Sigma$)
Because $\Sigma$ is symmetric and positive-definite, there exists a unique lower triangular matrix $\mathbf{L}$ such that:

$$\Sigma = \mathbf{L} \mathbf{L}^T$$

where:
$$L_{j,j} = \sqrt{\Sigma_{j,j} - \sum_{k=1}^{j-1} L_{j,k}^2}$$
$$L_{i,j} = \frac{1}{L_{j,j}} \left(\Sigma_{i,j} - \sum_{k=1}^{j-1} L_{i,k} L_{j,k}\right) \quad \text{for } i > j$$

### 7.3 Heavy-Tailed Fat-Shock Generation (Student's $t$)
Standard Gaussian random walks underestimate catastrophic market crises (the "black swan" problem). ValuationLab draws independent random vectors from a Student's $t$ distribution with five degrees of freedom ($\nu = 5$):

$$\mathbf{Z} \sim t_{\nu=5}\left(\mathbf{0}, \mathbf{I}_7\right)$$

Correlated macro shocks $\mathbf{X}$ are computed via linear transformation:

$$\mathbf{X} = \mathbf{\mu} + \mathbf{L} \mathbf{Z}$$

### 7.4 3× Oversampling & Rejection Filtering Protocol
To prevent pathological mathematical breakdowns, the engine oversamples **30,000 candidate trials** and discards economically invalid worlds:

1. **Gordon Denominator Constraint:** $WACC_i - g_{\infty, i} \le 0.005$ (voids infinite or negative terminal values).
2. **Nominal Cost of Debt Constraint:** $K_{d, i} < R_{f, i}$ (lenders do not lend below sovereign yields).
3. **Cost of Equity Lower Bound:** $K_{e, i} < R_{f, i}$ (equity risk premium cannot be negative).
4. **Margin Boundaries:** $\mu_{\text{target}, i} > 0.95$ or $\mu_{\text{target}, i} < -0.80$ (unrealistic operating limits).

The surviving valid sample set is truncated to **exactly 10,000 verified simulations**.

### 7.5 Empirical Percentiles & Value-at-Risk ($VaR$)
The resulting 10,000 fair value outputs $\{P_0^{(1)}, P_0^{(2)}, \dots, P_0^{(10000)}\}$ are sorted into ascending order to construct non-parametric empirical percentiles:

*   **P5 (Severe Bearish Stress-Test):** 5th percentile fair value under high rates and compressed margins.
*   **P25 (Conservative Base Case):** Lower quartile boundary for margin of safety entry.
*   **P50 (Median Intrinsic Fair Value):** Robust central tendency benchmark.
*   **P75 (Optimistic Target):** Upper quartile valuation under favorable reinvestment cycles.
*   **P95 (Blue-Sky Bull Case):** Maximum reasonable upside limit.

---

## 8. Model Verification & Trading Multiples Cross-Check

Every intrinsic DCF valuation is cross-referenced against current market trading multiples to detect model divergence and market mispricings:

```
                            [DCF Intrinsic Output]
                                      │
                                      ▼
                      [Implied Trading Multiples]
                     Implied EV/EBITDA, P/E, P/B
                                      │
                                      ▼
                      [Comparison Against Peers]
                 Divergence = |Implied Multiple - Market Multiple|
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        ▼                             ▼                             ▼
 [Verified Badge]              [Warning Flag]               [Distressed Flag]
   Gap < 50%                     Gap: 50% - 80%               Equity ≤ 0 OR
 Strong institutional          Speculative multiple          >20% MC wipeout
   alignment                     expansion / contraction       unreliable DCF
```

1. **Implied EV/EBITDA Multiple:**
   $$\text{Implied } \frac{EV}{\text{EBITDA}} = \frac{EV_{\text{DCF}}}{\text{EBITDA}_0}$$

2. **Implied Price-to-Earnings ($P/E$):**
   $$\text{Implied } \frac{P}{E} = \frac{\text{Equity Value}_{\text{DCF}}}{\text{Net Income}_0}$$

3. **Implied Price-to-Book ($P/B$):**
   $$\text{Implied } \frac{P}{B} = \frac{\text{Equity Value}_{\text{DCF}}}{\text{Total Book Equity}_0}$$

### Verification Thresholds:
*   **VERIFIED BADGE ($\text{Gap} < 50\%$):** Implied multiple tightly matches the trading multiple, validating that cash flow projections are institutionally grounded.
*   **WARNING BADGE ($50\% \le \text{Gap} \le 80\%$):** The market is pricing in aggressive speculative growth or temporary earnings trough.
*   **DISTRESSED ALERT:** Triggered when Debt $> EV$ (implied share price ₹0.00), Year-5 FCFF $< 0$, or $> 20\%$ of Monte Carlo simulations wipe out shareholder equity.

---

## 9. Mathematical Symbols & LaTeX Nomenclature Reference

| Symbol | Mathematical Definition | Primary Dimension |
| :--- | :--- | :--- |
| $\text{FCFF}_t$ | Free Cash Flow to Firm in period $t$ | Currency ($\text{INR} / \text{USD}$) |
| $\text{FCFE}_t$ | Free Cash Flow to Equity in period $t$ | Currency ($\text{INR} / \text{USD}$) |
| $\text{NOPAT}_t$ | Net Operating Profit After Tax ($\text{EBIT} \times (1 - \tau)$) | Currency ($\text{INR} / \text{USD}$) |
| $WACC$ | Weighted Average Cost of Capital | Percentage Rate ($\text{p.a.}$) |
| $K_e$ | Cost of Equity under CAPM | Percentage Rate ($\text{p.a.}$) |
| $K_d$ | Pre-tax Cost of Borrowed Debt Capital | Percentage Rate ($\text{p.a.}$) |
| $R_f$ | Sovereign Benchmark 10-Year Risk-Free Rate | Percentage Rate ($\text{p.a.}$) |
| $ERP$ | Equity Risk Premium ($E[R_m] - R_f$) | Percentage Rate ($\text{p.a.}$) |
| $\beta_L, \beta_U$ | Levered Equity Beta / Asset Unlevered Beta | Dimensionless Coefficient |
| $\tau$ | Marginal Corporate Statutory Tax Rate | Percentage Rate ($\text{p.a.}$) |
| $g_{\infty}$ | Perpetual Terminal Gordon Growth Rate | Percentage Rate ($\text{p.a.}$) |
| $DF_t$ | Mid-Year Fractional Cash Flow Discount Factor | Discount Factor ($0 < DF \le 1$) |
| $TV_N$ | Gordon Growth Perpetual Terminal Value at Year $N$ | Currency ($\text{INR} / \text{USD}$) |
| $\mathbf{\Sigma}$ | 7-Variable Stochastic Covariance Matrix | Covariance Matrix ($\mathbb{R}^{7 \times 7}$) |
| $\mathbf{L}$ | Cholesky Lower Triangular Factorization Matrix | Lower Triangular Matrix ($\mathbf{L} \mathbf{L}^T = \mathbf{\Sigma}$) |
| $\mathbf{Z}$ | Heavy-Tailed Student's $t$ Random Vector | Random Vector ($\nu = 5$) |
| $ICR$ | Operating Interest Coverage Ratio ($\text{EBIT} / \text{Interest Expense}$) | Coverage Multiple ($x\times$) |
| $P_5, P_{95}$ | Empirical Monte Carlo 5th and 95th Percentile Valuations | Currency per Share ($\text{INR} / \text{USD}$) |
