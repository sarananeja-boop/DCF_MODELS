# ValuationLab: Automated DCF & Monte Carlo Engine

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![React](https://img.shields.io/badge/Frontend-React%20%7C%20Vite-61DAFB?logo=react)
![FastAPI](https://img.shields.io/badge/Backend-FastAPI%20%7C%20Python-009688?logo=fastapi)
![Quant](https://img.shields.io/badge/Quant-Monte%20Carlo%20%7C%20SciPy-FF6F00)

ValuationLab is an institutional-grade, full-stack financial valuation platform. It automates the extraction of corporate financial data, computes dynamic intrinsic valuations using Discounted Cash Flow (DCF) mechanics, and maps probability distributions of fair value using a 10,000-iteration Monte Carlo engine.

## 🚀 Key Features

* **Live Financial Scraping**: Automatically fetches normalized historical income statements, balance sheets, and cash flow data using `yfinance`.
* **Dynamic Cost of Capital (WACC)**: Calculates the Weighted Average Cost of Capital in real-time. Uses the Capital Asset Pricing Model (CAPM) driven by live Risk-Free Rates fetched from the **FRED API**.
* **Advanced Monte Carlo Simulation**: Runs 10,000 iterations to build a 90% confidence interval of intrinsic value. Uses **Cholesky decomposition** to ensure random variables (like Revenue Growth and EBIT Margin) adhere to their historical covariance.
* **Intelligent Edge-Case Handling**: Automatically interpolates negative historical margins toward profitability, maps complex EV-to-Equity bridges (including capital leases and marketable securities), and uses mathematical floors to safely value deeply leveraged companies.
* **AI-Powered Insights**: Integrates with LLMs to automatically generate executive valuation summaries and highlight fundamental business risks.
* **Interactive UI**: A sleek, dark-mode React dashboard with real-time assumption sliders, sensitivity heatmaps, and dynamic Recharts histograms.

## 🛠 Tech Stack

**Frontend:**
* React 18 / Vite
* Tailwind CSS
* Recharts (Data Visualization)
* Axios & React-Hot-Toast

**Backend:**
* Python 3 / FastAPI
* NumPy, SciPy, Pandas (Quantitative Math & Statistics)
* yFinance, FRED API (Data Pipelines)
* Groq / OpenAI (LLM Integration)

## 📐 Quantitative Methodology
For an in-depth look at the mathematical pipelines, terminal value formulas, and the Monte Carlo rejection sampling algorithms used in this engine, please refer to the [DCF Methodology Guide](DCF_Methodology_Guide.md).

## 💻 Local Setup & Installation

### 1. Clone the repository
```bash
git clone https://github.com/sarananeja-boop/DCF_MODELS.git
cd DCF_MODELS
```

### 2. Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the `backend/` directory:
```ini
FRED_API_KEY=your_fred_api_key_here
GROQ_API_KEY=your_groq_api_key_here
```

Start the FastAPI server:
```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### 3. Frontend Setup
Open a new terminal window:
```bash
cd frontend
npm install
npm run dev
```
Navigate to `http://localhost:5173` in your browser.

## ⚠️ Disclaimer
*This platform is for educational and portfolio demonstration purposes only. It does not constitute financial advice, investment recommendations, or an endorsement of any particular security. Always conduct your own due diligence.*
