# ValuationLab: Technical Handover & Deployment Post-Mortem

> **Document Purpose:** This document provides a complete technical handover for the ValuationLab backend. It details the architecture, mathematical pipelines, production deployment topology, root causes of ongoing deployment failures, and step-by-step remediation instructions. Any engineer or AI agent reading this will have complete context to debug, repair, and operate the platform.

---

## 1. Executive Summary & Core Purpose

**ValuationLab** is a full-stack automated financial modeling and equity valuation platform. 

### Core Capabilities:
1. **Automated Financial Ingestion:** Ingests standardized multi-year income statements, balance sheets, and cash flow statements via `yfinance`.
2. **Dynamic Cost of Capital (WACC):** Calculates firm-specific discount rates using the Capital Asset Pricing Model (CAPM), dynamically querying live 10-year sovereign yields from the **FRED API** (Federal Reserve Economic Data).
3. **Multi-Stage DCF Modeling:** Computes Unlevered Free Cash Flows (UFCF), projects mid-year discounted future cash flows, values terminal equity via Gordon Growth, and computes intrinsic equity value per share using a comprehensive Enterprise Value (EV) to Equity bridge.
4. **10,000-Iteration Correlated Monte Carlo Simulation:** Implements a stochastic simulation over historical covariance matrices using **Cholesky decomposition** to evaluate 90% confidence intervals and intrinsic value probability distributions.
5. **Multi-Scenario Sensitivity Matrices:** Generates 2D heatmaps across varying WACC, Terminal Growth rates, and operating margins.
6. **Professional Reporting:** Employs LLMs via the Groq API (`llama3-70b-8192`) for narrative valuation summaries and generates downloadable Excel spreadsheets (`.xlsx`) via `openpyxl`.

---

## 2. Codebase Structure & Architecture

```
automated-dcf-modeller/
├── backend/
│   ├── main.py                    # FastAPI entrypoint, HTTP routing, request/response models, CORS
│   ├── requirements.txt           # Python dependency specifications
│   ├── runtime.txt                # Render Python runtime declaration ("3.11.9")
│   ├── .env                       # Secrets (FRED_API_KEY, GROQ_API_KEY)
│   ├── engine/                    # Core quantitative engine
│   │   ├── data_layer.py          # Data extraction via yfinance, historical metric normalization
│   │   ├── market_config.py       # Sovereign risk profiles, FRED yield fetching, fallback parameters
│   │   ├── dcf_engine.py          # CAPM, WACC, UFCF projections, Gordon Growth, EV-to-Equity bridge
│   │   ├── monte_carlo.py         # 10k Cholesky-correlated simulation & percentile statistics
│   │   ├── sensitivity.py         # 2D parametric sensitivity grids (WACC vs g, WACC vs Margin)
│   │   ├── validators.py          # Financial sanity checks, outlier filters, valuation verdict
│   │   └── trend_analysis.py      # Historical trends (CAGRs, margin expansion/contraction)
│   ├── ai/
│   │   └── summary_generator.py   # Groq API client & prompt engineering for executive reports
│   └── export/
│       └── excel_export.py        # Multi-tab financial workbook generator via openpyxl
└── frontend/
    ├── package.json               # React 18, Vite, Tailwind CSS, Recharts, Axios
    ├── vite.config.js             # Dev server proxy (/api -> http://localhost:8000)
    └── src/                       # Dashboard UI, assumption sliders, interactive charts
```

### Execution Flow: `POST /api/analyze`

```
                      [Client Request]
                             │
                             ▼ POST /api/analyze
                     [backend/main.py]
                             │
       ┌─────────────────────┴─────────────────────┐
       │ 1. Market Detection                       │
       ▼ (US vs IN, ticker suffixes)               ▼
[engine/market_config.py]                 [engine/data_layer.py]
- Queries FRED for 10Y RFR                 - yfinance.Ticker()
  (DGS10 / INDIRLTLT01STM)                 - Financial statement extraction
  with fallback rates                      - Extract currentPrice & sharesOutstanding
                                                   │
       ┌───────────────────────────────────────────┘
       ▼
[engine/dcf_engine.py]
- Cost of Equity: Ke = Rf + Beta * ERP
- WACC calculation
- Multi-year Unlevered FCF: UFCF = EBIT*(1-T) + D&A - Capex - ΔNWC
- Gordon Growth Terminal Value: TV = [FCF_final * (1 + g)] / (WACC - g)
- EV-to-Equity Bridge (+ Cash - Debt - Minority Interest - Preferred)
       │
       ▼
[engine/monte_carlo.py]
- Correlated Gaussian simulation of [Rev Growth, EBIT Margin, WACC]
- Covariance matrix decomposed via Cholesky (L · L^T)
- 10,000 iterations with rejection sampling and percentile statistics
       │
       ▼
[engine/sensitivity.py & validators.py]
- Generates 5x5 WACC vs Growth and WACC vs Margin matrices
- Valuation verdict (Under/Overvalued % margin of safety)
       │
       ▼
[JSON Response returned to client]
```

---

## 3. Production Deployment Topology

* **Service Type:** Web Service on Render (`https://dcf-models.onrender.com`)
* **Runtime:** Python 3.11.9 (declared in `backend/runtime.txt`)
* **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
* **Health Check Probe:** `GET /api/health` (currently returning `200 OK`)
* **Target Consumer:** React Frontend hosted locally or on Vercel connecting over HTTPS.

---

## 4. Root Cause Analysis: The Deployment Failures

While the service boots and responds to `/api/health`, **all calls to `POST /api/analyze` fail with HTTP 500**. The failures are caused by two primary issues and three secondary operational hurdles:

### Blocker 1: Upstream Bug in Pinned `yfinance 0.2.40` (Immediate Fatal Crash)

#### Live Error Traceback from Render:
```
Traceback (most recent call last):
  File "/opt/render/project/src/backend/main.py", line 201, in analyze
    stock_data = fetch_stock_data(ticker, market)
  File "/opt/render/project/src/backend/engine/data_layer.py", line 108, in fetch_stock_data
    info: dict = stock.info
  File "/opt/render/project/src/.venv/lib/python3.11/site-packages/yfinance/ticker.py", line 153, in info
    return self.get_info()
  File "/opt/render/project/src/.venv/lib/python3.11/site-packages/yfinance/scrapers/quote.py", line 635, in _fetch_info
    result = self._fetch(proxy, modules=modules)
  File "/opt/render/project/src/.venv/lib/python3.11/site-packages/yfinance/data.py", line 347, in get
    cookie, crumb, strategy = self._get_cookie_and_crumb()
  File "/opt/render/project/src/.venv/lib/python3.11/site-packages/yfinance/data.py", line 323, in _get_cookie_and_crumb
    cookie, crumb = self._get_cookie_and_crumb_basic(proxy, timeout)
  File "/opt/render/project/src/.venv/lib/python3.11/site-packages/yfinance/data.py", line 213, in _get_cookie_and_crumb_basic
    crumb = self._get_crumb_basic(proxy, timeout)
  File "/opt/render/project/src/.venv/lib/python3.11/site-packages/yfinance/data.py", line 192, in _get_crumb_basic
    'cookies': {cookie.name: cookie.value},
AttributeError: 'str' object has no attribute 'name'
```

#### Technical Cause:
1. In `backend/requirements.txt`, the library was pinned to `yfinance==0.2.40`.
2. In `yfinance 0.2.40`, `_get_cookie_basic()` requests `https://fc.yahoo.com` and sets:
   ```python
   self._cookie = list(response.cookies)[0]
   ```
   In the Python `requests` library, iterating over a `RequestsCookieJar` produces a sequence of cookie **names** (strings, e.g. `'A3'`), not `Cookie` objects.
3. Next, `_get_crumb_basic()` takes `cookie = self._get_cookie_basic()` and attempts:
   ```python
   'cookies': {cookie.name: cookie.value}  # <-- CRASH: cookie is 'A3' (a string)
   ```
4. This bug was tracked upstream in GitHub issue [#2470](https://github.com/ranaroussi/yfinance/issues/2470) and resolved in subsequent releases.

---

### Blocker 2: Datacenter IP Rate-Limiting & Bot Fingerprinting (HTTP 429)

Prior to the cookie crash, requests were failing because Yahoo Finance aggressively blocks requests from shared cloud hosting providers (Render, AWS, GCP, Fly.io, DigitalOcean):
1. **User-Agent Inadequacy:** Injecting a browser `User-Agent` into a standard `requests.Session()` (commit `8f6cf6b`) does not fool Yahoo's bot mitigation.
2. **TLS Client Hello Detection:** Python's standard `requests`/`urllib3` stack uses OpenSSL, which creates a distinct TLS cipher/extension signature (JA3/JA4 fingerprint). Yahoo detects that the request originates from a datacenter IP with a non-browser TLS fingerprint and immediately rejects the connection with HTTP 429 or an empty HTML consent wall.
3. **The Solution Tested:** The developer began testing `curl_cffi` in `backend/patch_test.py` to spoof genuine Chrome TLS handshakes, but had not yet wired it into `engine/data_layer.py`.

---

### Operational Hurdle 3: Dependency Resolution & Wheel Compilation

* During early deploys, Render attempted to build dependencies under Python versions lacking pre-built Linux wheels for `scipy`, `numpy`, and `pandas`, causing build timeouts.
* The developer pinned `runtime.txt` to `3.11.9` and pinned `numpy==1.26.4`, `scipy==1.13.1`, and `pandas==2.2.3`. 
* When rolling back dependencies to achieve a clean build, `yfinance` was accidentally pinned to `0.2.40`, re-introducing Blocker 1.

---

### Operational Hurdle 4: Render Free-Tier Spin-Down (Cold Start)

* Render's free tier spins down containers after 15 minutes of silence.
* Waking up requires **50 to 90 seconds**.
* Standard HTTP client timeouts (often 10–30s) abort with connection errors before Render completes container initialization.

---

### Operational Hurdle 5: FRED SSL Certificate Failures

* In minimal Linux containers, FRED API calls may throw:
  `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate`.
* While `engine/market_config.py` absorbs this via static fallback yields (4.2% US, 7.1% IN), CA certificates should be initialized via `certifi`.

---

## 5. Step-by-Step Remediation Plan

Follow these exact steps to restore full production health:

### Step 1: Update `backend/requirements.txt`
Upgrade `yfinance` to a modern release and add `curl_cffi` alongside certificate management:

```txt
fastapi==0.115.0
uvicorn[standard]==0.30.0
yfinance>=1.4.0
curl_cffi>=0.7.0
pandas==2.2.3
numpy==1.26.4
scipy==1.13.1
openpyxl==3.1.5
fredapi==0.5.2
groq==0.9.0
python-dotenv==1.0.1
pydantic==2.8.0
httpx>=0.27.0
certifi>=2024.7.4
```

### Step 2: Implement Chrome TLS Impersonation in `backend/engine/data_layer.py`
Replace the standard `requests.Session()` with `curl_cffi` to bypass Yahoo's datacenter TLS blocks:

```python
# backend/engine/data_layer.py

from curl_cffi import requests as cffi_requests
import yfinance as yf

class CookieAdapter:
    def __init__(self, curl_cookies):
        self.curl_cookies = curl_cookies
    def __iter__(self):
        class MockCookie:
            def __init__(self, name, value):
                self.name = name
                self.value = value
        for k, v in self.curl_cookies.items():
            yield MockCookie(k, v)

class PatchedCffiSession(cffi_requests.Session):
    @property
    def cookies(self):
        return CookieAdapter(super().cookies)
    @cookies.setter
    def cookies(self, val):
        pass  # Prevent overwrites

def get_impersonated_session():
    return PatchedCffiSession(impersonate="chrome120")
```

In `fetch_stock_data(ticker, market)`:
```python
session = get_impersonated_session()
stock = yf.Ticker(yf_ticker, session=session)
```

### Step 3: Revert Debug Traceback Injection in `backend/main.py`
In `backend/main.py` around line 420:
Replace raw exception formatting with clean HTTP status handling:
```python
except ValueError as exc:
    err_str = str(exc)
    logger.warning("Analyze — bad input: %s", exc)
    if "429" in err_str or "Too Many Requests" in err_str:
        raise HTTPException(
            status_code=429,
            detail="Market data provider is currently rate-limiting requests. Please retry in 5 minutes."
        )
    raise HTTPException(status_code=400, detail=err_str)
except Exception as exc:
    logger.exception("Analyze — unexpected error")
    raise HTTPException(status_code=500, detail=str(exc))
```

### Step 4: Deploy & Verify
Run verification tests against the deployment:
```bash
# 1. Health Probe
curl -i https://dcf-models.onrender.com/api/health

# 2. End-to-end Valuation Pipeline Test
curl -X POST https://dcf-models.onrender.com/api/analyze \
     -H "Content-Type: application/json" \
     -d '{"ticker": "NESTLEIND.NS", "market": "IN", "monte_carlo_iterations": 500}'
```

---

## 6. Hosting Evaluation: Should You Move Away from Render?

| Platform | Suitable for this Project? | Pros & Cons |
| :--- | :--- | :--- |
| **Render (Current)** | **Yes (Stay for now)** | **Pros:** Fully configured, SSL active, zero-cost free tier.<br>**Cons:** 50–90s cold start on spin-down. *(Mitigate by setting a free 10-min ping on UptimeRobot to `/api/health`)*. |
| **Railway** | **Highly Recommended Alternative** | **Pros:** No aggressive 50s cold start, automatic Nixpacks build detects Python 3.11 with zero wheel issues, $5/mo free credit.<br>**Cons:** Requires shifting deployment target. |
| **Dedicated VPS** (Hetzner / DO) | **Best for Scraping Longevity** | **Pros:** Dedicated clean IPv4 address that Yahoo Finance does not flag, no cold starts, persistent memory.<br>**Cons:** Requires manual Linux/Nginx management. |
| **Serverless (Vercel / AWS Lambda)** | ❌ **Strictly NOT Recommended** | **Why:** Scientific Python packages (`numpy`, `scipy`, `pandas`) exceed the 250MB bundle size limit, and 10k Monte Carlo iterations risk function execution timeouts. |

---
*End of Technical Handover Document.*
