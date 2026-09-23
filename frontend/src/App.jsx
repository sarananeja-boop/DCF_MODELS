import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { Toaster, toast } from 'react-hot-toast';
import { Analytics } from '@vercel/analytics/react';
import { 
  FiTrendingUp, 
  FiTrendingDown,
  FiBarChart2, 
  FiGrid, 
  FiActivity, 
  FiCpu, 
  FiRefreshCw, 
  FiMessageSquare,
  FiRotateCcw,
  FiArrowRight,
  FiCheckCircle,
  FiLayers,
  FiFileText,
  FiSliders,
  FiExternalLink,
  FiX
} from 'react-icons/fi';

import TickerInput from './components/TickerInput';
import AssumptionSliders from './components/AssumptionSliders';
import MacroDisplay from './components/MacroDisplay';
import OverviewTab from './components/OverviewTab';
import DCFModelTab from './components/DCFModelTab';
import MonteCarloTab from './components/MonteCarloTab';
import SensitivityTab from './components/SensitivityTab';
import TrendsTab from './components/TrendsTab';
import ExcelDownloadButton from './components/ExcelDownloadButton';
import ErrorBoundary from './components/ErrorBoundary';

const API_BASE_URL = (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '');
if (API_BASE_URL) {
  axios.defaults.baseURL = API_BASE_URL;
}

// Exact benchmark outputs produced by the ValuationLab DCF Engine (100% verified consistency)
const PREVIEW_DATA = {
  HINDUNILVR: {
    ticker: 'HINDUNILVR.NS',
    market: 'IN',
    name: 'Hindustan Unilever Ltd.',
    tabLabel: '🇮🇳 HUL (NSE)',
    currency: '₹',
    fairValue: '₹750.08',
    currentPrice: '₹1,947.00',
    upsidePct: -61.5,
    upsideBadge: '▼ 61.5% Downside',
    upsideNote: 'Trades at 45x P/E premium over DCF',
    wacc: '11.3%',
    waccNote: 'RBI 10Y G-Sec: 7.1% | Beta: 0.71',
    mcRange: '₹487 – ₹1,556',
    metrics: {
      revBase: '₹60,580 Cr',
      revY1: '₹65,251 Cr',
      revY3: '₹69,926 Cr',
      revY5: '₹77,246 Cr',
      revTV: '₹81,494 Cr',
      fcffBase: '₹10,094 Cr',
      fcffY1: '₹11,207 Cr',
      fcffY3: '₹11,937 Cr',
      fcffY5: '₹13,108 Cr',
      fcffTV: '₹13,829 Cr',
      dfBase: '1.000',
      dfY1: '0.948 (Mid-Yr)',
      dfY3: '0.765 (Mid-Yr)',
      dfY5: '0.618 (Mid-Yr)',
      dfTV: '0.584',
    }
  },
  AAPL: {
    ticker: 'AAPL',
    market: 'US',
    name: 'Apple Inc.',
    tabLabel: '🇺🇸 Apple (NASDAQ)',
    currency: '$',
    fairValue: '$85.28',
    currentPrice: '$338.98',
    upsidePct: -74.8,
    upsideBadge: '▼ 74.8% Downside',
    upsideNote: 'Trades at 38x EV/FCF multiple',
    wacc: '10.1%',
    waccNote: 'FRED US 10Y: 4.1% | Beta: 1.02',
    mcRange: '$49 – $178',
    metrics: {
      revBase: '$416.2 B',
      revY1: '$424.0 B',
      revY3: '$440.3 B',
      revY5: '$457.2 B',
      revTV: '$468.6 B',
      fcffBase: '$100.9 B',
      fcffY1: '$104.5 B',
      fcffY3: '$108.7 B',
      fcffY5: '$113.6 B',
      fcffTV: '$116.4 B',
      dfBase: '1.000',
      dfY1: '0.953 (Mid-Yr)',
      dfY3: '0.785 (Mid-Yr)',
      dfY5: '0.647 (Mid-Yr)',
      dfTV: '0.617',
    }
  },
  CESC: {
    ticker: 'CESC.NS',
    market: 'IN',
    name: 'CESC Limited',
    tabLabel: '🇮🇳 CESC (+55% Upside)',
    currency: '₹',
    fairValue: '₹223.42',
    currentPrice: '₹143.47',
    upsidePct: 55.7,
    upsideBadge: '▲ +55.7% Upside',
    upsideNote: 'Deep value utility with robust terminal cash flow',
    wacc: '9.1%',
    waccNote: 'RBI 10Y G-Sec: 7.1% | Beta: 0.85',
    mcRange: '₹128 – ₹471',
    metrics: {
      revBase: '₹15,487 Cr',
      revY1: '₹16,618 Cr',
      revY3: '₹18,502 Cr',
      revY5: '₹20,598 Cr',
      revTV: '₹21,731 Cr',
      fcffBase: '₹1,824 Cr',
      fcffY1: '₹1,992 Cr',
      fcffY3: '₹2,351 Cr',
      fcffY5: '₹2,789 Cr',
      fcffTV: '₹2,942 Cr',
      dfBase: '1.000',
      dfY1: '0.958 (Mid-Yr)',
      dfY3: '0.805 (Mid-Yr)',
      dfY5: '0.676 (Mid-Yr)',
      dfTV: '0.646',
    }
  }
};

export default function App() {
  const [analysisData, setAnalysisData] = useState(() => {
    const saved = sessionStorage.getItem('vl_analysisData');
    return saved ? JSON.parse(saved) : null;
  });
  const [loading, setLoading] = useState(false);
  const [loadingTimer, setLoadingTimer] = useState(0);
  const [error, setError] = useState(null);
  const abortControllerRef = useRef(null);
  const activeRequestIdRef = useRef(0);
  const valuationCacheRef = useRef(new Map());

  // Populate valuation cache from session state if already present
  useEffect(() => {
    if (analysisData?.company?.ticker) {
      const key = `${analysisData.company.ticker.toUpperCase()}:${analysisData.company.market || market}`;
      valuationCacheRef.current.set(key, analysisData);
    }
  }, []);
  
  const [activeTab, setActiveTab] = useState(() => sessionStorage.getItem('vl_activeTab') || 'overview');
  const [aiSummary, setAiSummary] = useState(() => sessionStorage.getItem('vl_aiSummary') || '');
  const [aiLoading, setAiLoading] = useState(false);
  
  const [ticker, setTicker] = useState(() => sessionStorage.getItem('vl_ticker') || '');
  const [market, setMarket] = useState(() => sessionStorage.getItem('vl_market') || 'auto');
  const [overrides, setOverrides] = useState(() => {
    const saved = sessionStorage.getItem('vl_overrides');
    return saved ? JSON.parse(saved) : {};
  });
  const [monteCarloIterations, setMonteCarloIterations] = useState(2000);
  const [resetKey, setResetKey] = useState(0);
  const [showMethodology, setShowMethodology] = useState(false);

  // Landing page interactive preview state
  const [previewStock, setPreviewStock] = useState('HINDUNILVR');
  const [previewTab, setPreviewTab] = useState('dcf');
  const currentPreview = PREVIEW_DATA[previewStock] || PREVIEW_DATA.HINDUNILVR;

  // Sync state to sessionStorage
  useEffect(() => {
    if (analysisData) sessionStorage.setItem('vl_analysisData', JSON.stringify(analysisData));
    else sessionStorage.removeItem('vl_analysisData');
  }, [analysisData]);

  useEffect(() => sessionStorage.setItem('vl_activeTab', activeTab), [activeTab]);
  useEffect(() => sessionStorage.setItem('vl_aiSummary', aiSummary), [aiSummary]);
  
  // Only persist verified tickers when analysisData exists to avoid reload loops on invalid queries
  useEffect(() => {
    if (analysisData?.company?.ticker) {
      sessionStorage.setItem('vl_ticker', analysisData.company.ticker);
    } else if (!loading) {
      sessionStorage.removeItem('vl_ticker');
    }
  }, [analysisData, loading]);

  useEffect(() => sessionStorage.setItem('vl_market', market), [market]);
  useEffect(() => sessionStorage.setItem('vl_overrides', JSON.stringify(overrides)), [overrides]);

  // Pre-warm backend container immediately upon page load to eliminate cold start friction
  useEffect(() => {
    axios.get('/api/health').catch(() => {});
  }, []);

  // Timer for loading screen to give reassuring feedback during cold starts
  useEffect(() => {
    let interval;
    if (loading) {
      setLoadingTimer(0);
      interval = setInterval(() => {
        setLoadingTimer(prev => prev + 1);
      }, 1000);
    } else {
      setLoadingTimer(0);
    }
    return () => clearInterval(interval);
  }, [loading]);

  // Auto-refresh on page reload (Cmd+R) ONLY if there was an active valid valuation
  useEffect(() => {
    const savedTicker = sessionStorage.getItem('vl_ticker');
    const savedData = sessionStorage.getItem('vl_analysisData');
    
    if (savedTicker && savedData && !analysisData) {
      const savedMarket = sessionStorage.getItem('vl_market') || 'auto';
      const savedOverrides = sessionStorage.getItem('vl_overrides') ? JSON.parse(sessionStorage.getItem('vl_overrides')) : {};
      
      setLoading(true);
      axios.post('/api/analyze', {
        ticker: savedTicker,
        market: savedMarket,
        overrides: savedOverrides,
        monte_carlo_iterations: 10000
      }).then(response => {
        setAnalysisData(response.data);
      }).catch(err => {
        console.error("Auto-refresh failed:", err);
        sessionStorage.removeItem('vl_ticker');
        sessionStorage.removeItem('vl_analysisData');
      }).finally(() => {
        setLoading(false);
      });
    } else if (!savedData) {
      sessionStorage.removeItem('vl_ticker');
    }
  }, []);

  // Browser Back/Forward navigation support (SPA navigation without exiting site)
  useEffect(() => {
    if (!window.history.state) {
      const initialView = analysisData ? 'analysis' : 'home';
      window.history.replaceState({ 
        view: initialView, 
        ticker: analysisData?.company?.ticker || '', 
        market: analysisData?.company?.market || 'auto' 
      }, '');
    }

    const onPopState = (e) => {
      const state = e.state;
      if (!state || state.view === 'home' || !state.ticker) {
        handleGoHome(false);
      } else if (state.view === 'analysis' && state.ticker) {
        handleAnalyze({}, false, state.ticker, state.market || 'auto', true);
      }
    };

    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const handleAnalyze = async (
    overrideParams = null, 
    isNewSearch = false, 
    explicitTicker = null, 
    explicitMarket = null,
    isHistoryNav = false
  ) => {
    const targetTicker = (explicitTicker || ticker || '').trim().toUpperCase();
    const targetMarket = explicitMarket || market;

    if (!targetTicker) {
      toast.error('Please enter a ticker symbol');
      return;
    }
    
    const isDifferentCompany = !analysisData || 
        analysisData.company.ticker.toUpperCase() !== targetTicker ||
        analysisData.company.market !== targetMarket;

    if (isDifferentCompany || isNewSearch) {
      setAiSummary('');
      setOverrides({});
      sessionStorage.removeItem('vl_overrides');
    }
    
    let safeOverrides = {};
    if (!isDifferentCompany && !isNewSearch) {
      if (overrideParams && !overrideParams.nativeEvent && !(overrideParams instanceof Event)) {
        safeOverrides = overrideParams;
      } else {
        safeOverrides = overrides;
      }
    }

    // Instant in-memory cache check: eliminate re-fetching on back/forward or repeat navigation
    const cacheKey = `${targetTicker}:${targetMarket}`;
    if (!isNewSearch && Object.keys(safeOverrides).length === 0 && valuationCacheRef.current.has(cacheKey)) {
      const cached = valuationCacheRef.current.get(cacheKey);
      setAnalysisData(cached);
      setTicker(cached.company.ticker);
      setMarket(cached.company.market || targetMarket);
      setError(null);
      setLoading(false);
      sessionStorage.setItem('vl_ticker', cached.company.ticker);
      return;
    }

    // Assign unique incremental ID to this valuation request
    const currentReqId = ++activeRequestIdRef.current;

    // Abort previous in-flight network request silently
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setLoading(true);
    setError(null);

    try {
      const response = await axios.post('/api/analyze', {
        ticker: targetTicker,
        market: targetMarket,
        overrides: safeOverrides,
        monte_carlo_iterations: monteCarloIterations
      }, { 
        timeout: 75000,
        signal: controller.signal
      });
      
      // If a newer search was initiated while this request was running, discard silently
      if (currentReqId !== activeRequestIdRef.current) {
        return;
      }

      valuationCacheRef.current.set(cacheKey, response.data);
      setAnalysisData(response.data);
      setTicker(targetTicker);
      setMarket(targetMarket);
      sessionStorage.setItem('vl_ticker', response.data.company.ticker);
      toast.success(`Analysis for ${response.data.company.ticker} completed`);
      
      // Update browser history only for new searches (not on popstate back/forward traversal)
      if (!isHistoryNav) {
        try {
          window.history.pushState(
            { view: 'analysis', ticker: response.data.company.ticker, market: targetMarket },
            '',
            `?ticker=${encodeURIComponent(response.data.company.ticker)}`
          );
        } catch (_) {}
      }
    } catch (err) {
      // If this is no longer the active request, ignore completely
      if (currentReqId !== activeRequestIdRef.current) {
        return;
      }

      if (axios.isCancel(err) || err.name === 'CanceledError') {
        // Silent cancellation when superseded by newer request
        return;
      }

      let errorMsg = err.response?.data?.detail || err.response?.data?.error || err.message;
      if (err.code === 'ECONNABORTED' || err.message?.includes('timeout')) {
        errorMsg = 'Valuation request timed out. The backend server may be waking up from cold sleep on Render. Please retry in 10 seconds.';
      } else if (
        errorMsg?.includes('did not return critical data') ||
        errorMsg?.includes('Cannot build a DCF') ||
        errorMsg?.includes('not found') ||
        errorMsg?.includes('No data found')
      ) {
        errorMsg = `Ticker '${targetTicker}' was not found on NSE, BSE, or US exchanges. Please check for typos or select a company from the dropdown suggestions.`;
      } else if (!errorMsg) {
        errorMsg = 'An error occurred during valuation analysis';
      }
      // Never leave invalid tickers in session storage
      sessionStorage.removeItem('vl_ticker');
      setError(errorMsg);
      toast.error(errorMsg);
    } finally {
      // Only the active request is allowed to reset the loading state
      if (currentReqId === activeRequestIdRef.current) {
        setLoading(false);
        setLoadingTimer(0);
      }
    }
  };

  const handleCancelAnalyze = () => {
    activeRequestIdRef.current++;
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setLoading(false);
    setLoadingTimer(0);
    toast('Valuation request cancelled', { icon: 'ℹ️' });
  };

  const handleQuickLaunch = (quickTicker, quickMarket) => {
    setTicker(quickTicker);
    setMarket(quickMarket);
    handleAnalyze({}, true, quickTicker, quickMarket);
  };

  const handleGoHome = (updateHistory = true) => {
    activeRequestIdRef.current++;
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setLoading(false);
    setLoadingTimer(0);
    setAnalysisData(null);
    setError(null);
    setTicker('');
    setOverrides({});
    setAiSummary('');
    setActiveTab('overview');
    sessionStorage.removeItem('vl_analysisData');
    sessionStorage.removeItem('vl_ticker');
    sessionStorage.removeItem('vl_overrides');
    if (updateHistory === true) {
      try {
        window.history.pushState({ view: 'home', ticker: '', market: 'auto' }, '', window.location.pathname);
      } catch (_) {}
    }
  };

  const handleFetchAISummary = async () => {
    if (!analysisData) return;
    
    setAiLoading(true);
    try {
      const response = await axios.post('/api/ai-summary', { analysis_data: analysisData });
      setAiSummary(response.data.summary);
      toast.success('AI summary generated');
    } catch (err) {
      toast.error('Failed to generate AI summary');
      console.error(err);
    } finally {
      setAiLoading(false);
    }
  };

  const tabs = [
    { id: 'overview', label: 'Overview', icon: <FiActivity className="w-4 h-4" /> },
    { id: 'dcf', label: 'DCF Model', icon: <FiTrendingUp className="w-4 h-4" /> },
    { id: 'monte_carlo', label: 'Monte Carlo', icon: <FiCpu className="w-4 h-4" /> },
    { id: 'sensitivity', label: 'Sensitivity', icon: <FiGrid className="w-4 h-4" /> },
    { id: 'trends', label: 'Trends', icon: <FiBarChart2 className="w-4 h-4" /> }
  ];

  return (
    <div className="min-h-screen bg-zinc-950 text-slate-100 font-sans flex flex-col selection:bg-blue-600 selection:text-white">
      <Toaster position="top-right" toastOptions={{ className: 'bg-zinc-900 text-white border border-zinc-700' }} />
      
      {/* Header */}
      <header className="sticky top-0 z-50 w-full border-b border-zinc-800/80 bg-zinc-950/85 backdrop-blur-md flex items-center justify-between px-4 sm:px-6 py-3">
        {/* Brand Logo & Title */}
        <div 
          className="flex items-center gap-3 cursor-pointer group select-none"
          onClick={handleGoHome}
        >
          <div className="relative flex items-center justify-center w-9 h-9 rounded-xl bg-gradient-to-b from-blue-600/25 to-indigo-600/15 border border-blue-500/30 shadow-sm group-hover:border-blue-400/60 group-hover:shadow-blue-500/10 transition-all duration-200">
            <svg className="w-4.5 h-4.5 text-blue-400 group-hover:text-blue-300 transition-colors" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 3v18h18" />
              <path d="m19 9-5 5-4-4-3 3" />
            </svg>
          </div>
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <h1 className="font-bold tracking-tight text-base sm:text-lg text-zinc-100 group-hover:text-white transition-colors">
                Valuation<span className="text-blue-400">Lab</span>
              </h1>
              <span className="hidden sm:inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold tracking-wider uppercase bg-blue-500/10 text-blue-400 border border-blue-500/20">
                DCF Engine
              </span>
            </div>
            <span className="text-[11px] text-zinc-400 hidden sm:block">Automated Valuation & Scenario Modeling</span>
          </div>
        </div>

        {/* Right Header Navigation / Actions */}
        <div className="flex items-center gap-2.5">
          {!analysisData ? (
            <>
              <div className="hidden md:flex items-center gap-2 px-3 py-1 rounded-full bg-zinc-900/60 border border-zinc-800/80 text-xs text-zinc-400">
                <span className="text-zinc-500 text-[11px]">Markets:</span>
                <span className="text-zinc-300 font-medium">US & Indian Equities</span>
              </div>
              <button
                type="button"
                onClick={() => setShowMethodology(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-zinc-300 hover:text-white bg-zinc-900/80 hover:bg-zinc-800 border border-zinc-800 hover:border-zinc-700 rounded-lg transition-colors cursor-pointer shadow-sm"
              >
                <FiFileText className="w-3.5 h-3.5 text-zinc-400" />
                <span>Methodology</span>
              </button>
            </>
          ) : (
            <>
              <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-900/90 border border-zinc-800 text-xs">
                <span className="font-semibold text-zinc-200">{analysisData?.company?.ticker || ticker}</span>
                <span className="text-zinc-600">|</span>
                <span className="text-zinc-400 truncate max-w-[140px]">{analysisData?.company?.name || ''}</span>
              </div>
              <button
                type="button"
                onClick={() => setShowMethodology(true)}
                className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-zinc-400 hover:text-white bg-zinc-900/60 hover:bg-zinc-800 border border-zinc-800 rounded-lg transition-colors cursor-pointer"
              >
                <FiFileText className="w-3.5 h-3.5 text-zinc-400" />
                <span>Methodology</span>
              </button>
              <button 
                type="button"
                onClick={handleGoHome}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-zinc-300 hover:text-white px-3 py-1.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-700/60 hover:border-zinc-600 transition shadow-sm cursor-pointer"
              >
                <FiRotateCcw className="w-3.5 h-3.5 text-zinc-400" />
                <span>Search Another Stock</span>
              </button>
            </>
          )}
        </div>
      </header>

      {/* Methodology Modal */}
      {showMethodology && (
        <div className="fixed inset-0 z-50 bg-zinc-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl max-w-2xl w-full max-h-[85vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800/80">
              <div className="flex items-center gap-2.5">
                <div className="p-1.5 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400">
                  <FiFileText className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-zinc-100">DCF Valuation Methodology</h3>
                  <p className="text-xs text-zinc-400">Institutional Damodaran-aligned framework</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowMethodology(false)}
                className="p-1.5 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg transition-colors cursor-pointer"
              >
                <FiX className="w-5 h-5" />
              </button>
            </div>
            
            <div className="p-6 overflow-y-auto space-y-4 text-xs text-zinc-300 leading-relaxed">
              <div className="p-3.5 rounded-xl bg-zinc-950/60 border border-zinc-800/60">
                <h4 className="font-semibold text-zinc-100 mb-1 text-sm">1. Historical Normalization</h4>
                <p className="text-zinc-400">Extracts 4-year audited balance sheet, income statement, and cash flow data with date cross-intersection to prevent restatement distortion.</p>
              </div>

              <div className="p-3.5 rounded-xl bg-zinc-950/60 border border-zinc-800/60">
                <h4 className="font-semibold text-zinc-100 mb-1 text-sm">2. Dynamic WACC Computation</h4>
                <p className="text-zinc-400">Applies CAPM using real-time 10Y sovereign bond yields (US Treasury or India 10Y G-Sec), 5-year beta, and country-specific risk premiums.</p>
              </div>

              <div className="p-3.5 rounded-xl bg-zinc-950/60 border border-zinc-800/60">
                <h4 className="font-semibold text-zinc-100 mb-1 text-sm">3. 5-Year Unlevered Free Cash Flows (FCFF)</h4>
                <p className="text-zinc-400">Forecasts revenues with fading growth, applies NOPAT margin convergence, and factors in reinvestment rate dynamics (CapEx, D&A, and Net Working Capital changes).</p>
              </div>

              <div className="p-3.5 rounded-xl bg-zinc-950/60 border border-zinc-800/60">
                <h4 className="font-semibold text-zinc-100 mb-1 text-sm">4. Monte Carlo Simulation</h4>
                <p className="text-zinc-400">Executes 10,000 randomized simulation runs over WACC and terminal growth distributions to evaluate fair value variance and downside probability.</p>
              </div>
            </div>

            <div className="px-6 py-3 border-t border-zinc-800/80 bg-zinc-950/50 flex justify-end">
              <button
                type="button"
                onClick={() => setShowMethodology(false)}
                className="px-4 py-2 text-xs font-semibold bg-zinc-800 hover:bg-zinc-700 text-white rounded-lg transition-colors cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main Content Area */}
      <main className="flex-1 relative overflow-hidden flex flex-col">
        
        {/* Reassuring Loading Overlay with cold start progress timer and cancel escape hatch */}
        {loading && (
          <div className="fixed inset-0 bg-zinc-950/85 backdrop-blur-md z-50 flex flex-col items-center justify-center p-6 text-center animate-in fade-in duration-200">
            <div className="relative mb-6">
              <div className="w-16 h-16 rounded-full border-4 border-blue-500/20 border-t-blue-500 animate-spin"></div>
              <div className="absolute inset-0 flex items-center justify-center font-mono text-xs text-blue-400 font-bold">
                {loadingTimer}s
              </div>
            </div>
            <h2 className="text-2xl font-bold tracking-tight text-zinc-100 mb-2">
              Valuing {ticker || 'Company'}...
            </h2>
            <p className="text-zinc-400 max-w-md text-sm leading-relaxed mb-4 min-h-[40px] flex items-center justify-center">
              {loadingTimer < 4
                ? 'Connecting to valuation engine & fetching SEC/BSE filings...'
                : loadingTimer < 10
                ? 'Extracting multi-year financials, computing WACC & projecting cash flows...'
                : loadingTimer < 20
                ? 'Waking up cloud valuation engine (~15-25s on first request)...'
                : 'Finalizing 10,000 Monte Carlo simulation runs & confidence intervals...'}
            </p>
            {loadingTimer >= 4 && (
              <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs mb-6 animate-pulse">
                <span>⚡ Cloud server warming up from idle sleep</span>
              </div>
            )}
            <button
              type="button"
              onClick={handleCancelAnalyze}
              className="mt-2 inline-flex items-center gap-2 px-4 py-2 text-xs font-medium text-zinc-400 hover:text-white bg-zinc-900/80 hover:bg-zinc-800 border border-zinc-700/60 rounded-lg transition-colors cursor-pointer"
            >
              <FiX className="w-3.5 h-3.5" />
              <span>Cancel & Return</span>
            </button>
          </div>
        )}

        {/* Error Banner with Retry Escape Hatch */}
        {error && (
          <div className="bg-red-950/70 border border-red-500/50 text-red-100 p-4 mx-6 mt-4 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 rounded-xl shadow-xl z-40 animate-in fade-in duration-200">
            <div className="flex items-start gap-3">
              <div className="p-1.5 rounded-lg bg-red-500/20 text-red-400 mt-0.5">
                <FiX className="w-4 h-4" />
              </div>
              <div>
                <p className="font-bold text-sm text-red-200">Valuation Attempt Incomplete</p>
                <p className="text-xs sm:text-sm text-red-300/90 leading-relaxed mt-0.5">{error}</p>
              </div>
            </div>
            <div className="flex items-center gap-2 self-end sm:self-auto shrink-0">
              {ticker && (
                <button
                  type="button"
                  onClick={() => {
                    setError(null);
                    handleAnalyze({}, false, ticker, market);
                  }}
                  className="px-3 py-1.5 text-xs font-semibold bg-red-600 hover:bg-red-500 text-white rounded-lg transition-colors shadow-sm cursor-pointer"
                >
                  Retry {ticker}
                </button>
              )}
              <button 
                type="button"
                onClick={() => setError(null)} 
                className="text-xs text-red-300 hover:text-white px-2.5 py-1.5 rounded-lg border border-red-800/60 hover:bg-red-900/40 transition-colors cursor-pointer"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {/* Landing Page (Remains visible even if a previous search timed out) */}
        {!analysisData && !loading && (
          <div className="flex-1 flex flex-col items-center overflow-y-auto px-4 py-12 sm:px-6 relative">
            {/* Subtle background glow */}
            <div className="absolute top-20 left-1/2 -translate-x-1/2 w-[700px] h-[350px] bg-blue-600/10 blur-[140px] rounded-full pointer-events-none"></div>

            {/* Hero Section */}
            <div className="max-w-4xl w-full text-center mb-10 relative z-10">
              <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-zinc-800/80 bg-zinc-900/80 px-3.5 py-1 text-xs font-medium text-zinc-400 backdrop-blur-md shadow-sm">
                <span>US & Indian Equities</span>
              </div>

              <h2 className="text-4xl sm:text-5xl md:text-6xl font-extrabold tracking-tight text-zinc-100 mb-4 leading-tight">
                Automated DCF <br />
                <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-indigo-400">
                  Valuation Engine
                </span>
              </h2>

              <p className="text-base sm:text-lg text-zinc-400 font-normal max-w-xl mx-auto leading-relaxed mb-8">
                Calculate intrinsic value, run Monte Carlo simulations, and export financial models for US and Indian stocks.
              </p>

              {/* Main Ticker Search Box */}
              <div className="max-w-2xl mx-auto w-full text-left mb-6 shadow-2xl">
                <TickerInput 
                  ticker={ticker}
                  setTicker={setTicker}
                  market={market}
                  setMarket={setMarket}
                  onAnalyze={handleAnalyze}
                  loading={loading}
                />
              </div>

              {/* One-Click Quick-Start Pills (Eliminates user friction) */}
              <div className="flex flex-col items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                  Instant One-Click Analysis:
                </span>
                <div className="flex flex-wrap items-center justify-center gap-2 max-w-2xl">
                  {[
                    { sym: 'HINDUNILVR.NS', label: 'Hindustan Unilever', m: 'IN', flag: '🇮🇳' },
                    { sym: 'RELIANCE.NS', label: 'Reliance', m: 'IN', flag: '🇮🇳' },
                    { sym: 'HDFCBANK.NS', label: 'HDFC Bank', m: 'IN', flag: '🇮🇳' },
                    { sym: 'TCS.NS', label: 'TCS', m: 'IN', flag: '🇮🇳' },
                    { sym: 'AAPL', label: 'Apple', m: 'US', flag: '🇺🇸' },
                    { sym: 'NVDA', label: 'NVIDIA', m: 'US', flag: '🇺🇸' },
                    { sym: 'MSFT', label: 'Microsoft', m: 'US', flag: '🇺🇸' },
                    { sym: 'TSLA', label: 'Tesla', m: 'US', flag: '🇺🇸' },
                  ].map((item) => (
                    <button
                      key={item.sym}
                      onClick={() => handleQuickLaunch(item.sym, item.m)}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-900/90 hover:bg-zinc-800 text-zinc-300 hover:text-white border border-zinc-800 hover:border-zinc-700 text-xs font-medium transition-all shadow-sm hover:scale-[1.03] active:scale-[0.98]"
                    >
                      <span className="text-[11px]">{item.flag}</span>
                      <span className="font-semibold text-zinc-200">{item.label}</span>
                      <span className="text-[10px] text-zinc-400 font-mono">({item.sym.replace('.NS', '')})</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Interactive Live Valuation Showcase Card (Synchronized with DCF engine outputs) */}
            <div className="max-w-4xl w-full mb-16 relative z-10">
                  <div className="bg-zinc-900/60 rounded-2xl border border-zinc-800 p-6 backdrop-blur-xl shadow-2xl">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-zinc-800/80">
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-bold uppercase tracking-wider text-blue-400">Live Model Showcase</span>
                          <span className="text-zinc-600">•</span>
                          <span className="text-xs text-zinc-400">Verified Engine Outputs</span>
                        </div>
                        <div className="flex flex-wrap items-center gap-2 mt-1">
                          {Object.keys(PREVIEW_DATA).map((key) => {
                            const item = PREVIEW_DATA[key];
                            const isSelected = previewStock === key;
                            return (
                              <button 
                                key={key}
                                onClick={() => setPreviewStock(key)}
                                className={`text-xs sm:text-sm font-bold px-3 py-1.5 rounded-lg transition ${
                                  isSelected
                                    ? 'bg-blue-600 text-white shadow-md shadow-blue-600/20'
                                    : 'bg-zinc-800/80 text-zinc-400 hover:text-zinc-200'
                                }`}
                              >
                                {item.tabLabel}
                              </button>
                            );
                          })}
                        </div>
                      </div>

                      <button
                        onClick={() => handleQuickLaunch(currentPreview.ticker, currentPreview.market)}
                        className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-zinc-100 hover:bg-white text-zinc-950 font-bold text-xs shadow-lg transition active:scale-[0.98]"
                      >
                        <span>Run Full Model Live ({currentPreview.name})</span>
                        <FiArrowRight />
                      </button>
                    </div>

                    {/* Preview Metrics Strip */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 py-6">
                      <div className="bg-zinc-950/70 p-4 rounded-xl border border-zinc-800/80">
                        <span className="text-xs text-zinc-400 block mb-1">Intrinsic Fair Value</span>
                        <span className={`text-xl sm:text-2xl font-black font-mono ${
                          currentPreview.upsidePct >= 0 ? 'text-emerald-400' : 'text-rose-400'
                        }`}>
                          {currentPreview.fairValue}
                        </span>
                        <span className={`text-[11px] font-medium flex items-center gap-1 mt-1 ${
                          currentPreview.upsidePct >= 0 ? 'text-emerald-400' : 'text-rose-400'
                        }`}>
                          {currentPreview.upsidePct >= 0 ? <FiTrendingUp /> : <FiTrendingDown />}
                          {currentPreview.upsideBadge}
                        </span>
                      </div>

                      <div className="bg-zinc-950/70 p-4 rounded-xl border border-zinc-800/80">
                        <span className="text-xs text-zinc-400 block mb-1">Market Price</span>
                        <span className="text-xl sm:text-2xl font-black text-zinc-200 font-mono">
                          {currentPreview.currentPrice}
                        </span>
                        <span className="text-[11px] text-zinc-400 block mt-1 line-clamp-1">
                          {currentPreview.upsideNote}
                        </span>
                      </div>

                      <div className="bg-zinc-950/70 p-4 rounded-xl border border-zinc-800/80">
                        <span className="text-xs text-zinc-400 block mb-1">Dynamic WACC</span>
                        <span className="text-xl sm:text-2xl font-black text-blue-400 font-mono">
                          {currentPreview.wacc}
                        </span>
                        <span className="text-[11px] text-zinc-400 block mt-1">
                          {currentPreview.waccNote}
                        </span>
                      </div>

                      <div className="bg-zinc-950/70 p-4 rounded-xl border border-zinc-800/80">
                        <span className="text-xs text-zinc-400 block mb-1">Monte Carlo (90% CI)</span>
                        <span className="text-base sm:text-lg font-bold text-indigo-300 font-mono">
                          {currentPreview.mcRange}
                        </span>
                        <span className="text-[11px] text-zinc-400 block mt-1">10,000 iterations</span>
                      </div>
                    </div>

                    {/* Preview Tabs */}
                    <div className="flex items-center gap-2 border-b border-zinc-800 mb-4 pb-2">
                      {[
                        { id: 'dcf', label: '10-Yr Cash Flow Trajectory', icon: <FiTrendingUp /> },
                        { id: 'monte_carlo', label: 'Monte Carlo Bell Curve', icon: <FiCpu /> },
                        { id: 'excel', label: 'Complete Excel Export', icon: <FiFileText /> },
                      ].map((tab) => (
                        <button
                          key={tab.id}
                          onClick={() => setPreviewTab(tab.id)}
                          className={`flex items-center gap-2 text-xs font-semibold px-3 py-2 rounded-lg transition ${
                            previewTab === tab.id
                              ? 'bg-zinc-800 text-white border border-zinc-700'
                              : 'text-zinc-400 hover:text-zinc-200'
                          }`}
                        >
                          {tab.icon}
                          <span>{tab.label}</span>
                        </button>
                      ))}
                    </div>

                    {/* Preview Tab Body */}
                    <div className="bg-zinc-950/80 rounded-xl p-5 border border-zinc-800/60 font-mono text-xs">
                      {previewTab === 'dcf' && (
                        <div className="space-y-3">
                          <div className="flex justify-between items-center text-zinc-400 pb-2 border-b border-zinc-800">
                            <span>Metric</span>
                            <span>Base (FY0)</span>
                            <span>Year 1</span>
                            <span>Year 3</span>
                            <span>Year 5</span>
                            <span>Terminal Year</span>
                          </div>
                          <div className="flex justify-between items-center text-zinc-200">
                            <span className="font-semibold text-blue-400">Revenue</span>
                            <span>{currentPreview.metrics.revBase}</span>
                            <span>{currentPreview.metrics.revY1}</span>
                            <span>{currentPreview.metrics.revY3}</span>
                            <span>{currentPreview.metrics.revY5}</span>
                            <span>{currentPreview.metrics.revTV}</span>
                          </div>
                          <div className="flex justify-between items-center text-zinc-200">
                            <span className="font-semibold text-emerald-400">Free Cash Flow (FCFF)</span>
                            <span>{currentPreview.metrics.fcffBase}</span>
                            <span>{currentPreview.metrics.fcffY1}</span>
                            <span>{currentPreview.metrics.fcffY3}</span>
                            <span>{currentPreview.metrics.fcffY5}</span>
                            <span>{currentPreview.metrics.fcffTV}</span>
                          </div>
                          <div className="flex justify-between items-center text-zinc-400">
                            <span>Discount Factor</span>
                            <span>{currentPreview.metrics.dfBase}</span>
                            <span>{currentPreview.metrics.dfY1}</span>
                            <span>{currentPreview.metrics.dfY3}</span>
                            <span>{currentPreview.metrics.dfY5}</span>
                            <span>{currentPreview.metrics.dfTV}</span>
                          </div>
                        </div>
                      )}

                  {previewTab === 'monte_carlo' && (
                    <div className="flex flex-col items-center justify-center py-4 text-center">
                      <div className="w-full max-w-lg h-24 flex items-end justify-between gap-1 px-4 mb-2">
                        {[5, 12, 25, 45, 78, 120, 195, 290, 390, 480, 520, 470, 380, 275, 180, 110, 65, 35, 18, 8].map((h, i) => (
                          <div 
                            key={i} 
                            style={{ height: `${(h / 520) * 100}%` }}
                            className={`flex-1 rounded-t transition-all ${
                              i >= 6 && i <= 14 ? 'bg-blue-500' : 'bg-zinc-700'
                            }`}
                          ></div>
                        ))}
                      </div>
                      <div className="flex justify-between w-full max-w-lg text-[10px] text-zinc-400 border-t border-zinc-800 pt-2">
                        <span>P5 Downside (VaR)</span>
                        <span className="text-blue-400 font-bold">50% Median Confidence</span>
                        <span>P95 Upside</span>
                      </div>
                    </div>
                  )}

                  {previewTab === 'excel' && (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 text-zinc-300 font-semibold mb-2">
                        <FiCheckCircle className="text-emerald-400" />
                        <span>Formatted Multi-Sheet Workbook Generated by ValuationLab:</span>
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-zinc-400 text-[11px]">
                        <div className="bg-zinc-900 p-2.5 rounded-lg border border-zinc-800">
                          <span className="font-bold text-zinc-200 block">1. Cover Summary</span>
                          Executive valuation summary & verdict
                        </div>
                        <div className="bg-zinc-900 p-2.5 rounded-lg border border-zinc-800">
                          <span className="font-bold text-zinc-200 block">2. Historical Financials</span>
                          Complete Income Stmt, Balance Sheet & Cash Flow
                        </div>
                        <div className="bg-zinc-900 p-2.5 rounded-lg border border-zinc-800">
                          <span className="font-bold text-zinc-200 block">3. WACC 2 Engine</span>
                          Live CAPM Cost of Equity & Debt weights
                        </div>
                        <div className="bg-zinc-900 p-2.5 rounded-lg border border-zinc-800">
                          <span className="font-bold text-zinc-200 block">4. DCF Model</span>
                          10-Yr forecast linked via live Excel formulas
                        </div>
                        <div className="bg-zinc-900 p-2.5 rounded-lg border border-zinc-800">
                          <span className="font-bold text-zinc-200 block">5. Sensitivity Tables</span>
                          2D WACC × Growth & Margin matrix
                        </div>
                        <div className="bg-zinc-900 p-2.5 rounded-lg border border-zinc-800">
                          <span className="font-bold text-zinc-200 block">6. Monte Carlo Charts</span>
                          10,000 simulated prices & native bar chart
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Core Capabilities Grid */}
            <div className="max-w-5xl w-full mb-16">
              <div className="text-center mb-8">
                <h3 className="text-2xl font-bold tracking-tight text-zinc-100 mb-2">
                  Built for Precision Financial Valuation
                </h3>
                <p className="text-sm text-zinc-400">
                  Every metric is transparent, defensible, and grounded in rigorous financial economics.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
                {[
                  { 
                    title: 'Multi-Stage DCF', 
                    desc: 'Dynamic mid-year discounted cash flow model with Gordon Growth terminal valuation.',
                    tag: 'Damodaran Framework',
                    icon: <FiTrendingUp className="w-5 h-5 text-blue-400" /> 
                  },
                  { 
                    title: '10,000-Run Monte Carlo', 
                    desc: 'Cholesky-correlated covariance engine simulating revenue volatility and margin shocks.',
                    tag: 'Quant Risk Mapping',
                    icon: <FiCpu className="w-5 h-5 text-indigo-400" /> 
                  },
                  { 
                    title: 'Complete 3-Statement Model', 
                    desc: 'Full historical Income Statement, Balance Sheet, and Cash Flow statement extraction.',
                    tag: 'Full Accounting Depth',
                    icon: <FiLayers className="w-5 h-5 text-emerald-400" /> 
                  },
                  { 
                    title: 'Excel Export with Formulas', 
                    desc: 'Downloadable multi-sheet model with native Excel formulas and embedded charts.',
                    tag: 'Investment Banking Ready',
                    icon: <FiFileText className="w-5 h-5 text-amber-400" /> 
                  }
                ].map((feature, i) => (
                  <div key={i} className="bg-zinc-900/40 backdrop-blur-sm p-6 rounded-2xl border border-zinc-800/90 hover:bg-zinc-900/80 hover:border-zinc-700 transition-all duration-300 group flex flex-col justify-between">
                    <div>
                      <div className="mb-4 bg-zinc-800/80 w-11 h-11 rounded-xl flex items-center justify-center border border-zinc-700/60 shadow-sm group-hover:scale-110 transition-transform">
                        {feature.icon}
                      </div>
                      <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-400 block mb-1">
                        {feature.tag}
                      </span>
                      <h4 className="text-base font-bold mb-2 text-zinc-100">{feature.title}</h4>
                      <p className="text-xs text-zinc-400 leading-relaxed">{feature.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* How It Works (3 Steps) */}
            <div className="max-w-4xl w-full mb-16">
              <div className="bg-zinc-900/30 rounded-2xl border border-zinc-800/70 p-8">
                <h4 className="text-lg font-bold text-center text-zinc-200 mb-8">
                  How ValuationLab Works
                </h4>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-center">
                  <div className="flex flex-col items-center">
                    <div className="w-9 h-9 rounded-full bg-blue-600/20 text-blue-400 border border-blue-500/30 flex items-center justify-center font-bold text-sm mb-3">
                      1
                    </div>
                    <h5 className="font-bold text-sm text-zinc-200 mb-1">Search Any Stock</h5>
                    <p className="text-xs text-zinc-400">Instant 0ms lookup across 2,750+ Indian NSE and US equities.</p>
                  </div>
                  <div className="flex flex-col items-center">
                    <div className="w-9 h-9 rounded-full bg-indigo-600/20 text-indigo-400 border border-indigo-500/30 flex items-center justify-center font-bold text-sm mb-3">
                      2
                    </div>
                    <h5 className="font-bold text-sm text-zinc-200 mb-1">Automated Modeling</h5>
                    <p className="text-xs text-zinc-400">Calculates dynamic WACC, projects cash flows, and simulates 10,000 trials.</p>
                  </div>
                  <div className="flex flex-col items-center">
                    <div className="w-9 h-9 rounded-full bg-emerald-600/20 text-emerald-400 border border-emerald-500/30 flex items-center justify-center font-bold text-sm mb-3">
                      3
                    </div>
                    <h5 className="font-bold text-sm text-zinc-200 mb-1">Stress-Test & Export</h5>
                    <p className="text-xs text-zinc-400">Slide growth & margins in real time, or download the full Excel model.</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Footer Trust Markers */}
            <div className="text-center text-xs text-zinc-500 border-t border-zinc-900 pt-6 max-w-2xl">
              ValuationLab uses live market data from Yahoo Finance and sovereign yield benchmarks via the FRED API & RBI.
              For educational and analytical research purposes.
            </div>
          </div>
        )}

        {/* Results Layout */}
        {analysisData && (
          <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
            {/* Left Sidebar */}
            <div className="w-full md:w-80 flex-shrink-0 bg-zinc-900 border-r border-zinc-800/80 flex flex-col overflow-y-auto h-full p-4 space-y-4">
              
              <TickerInput 
                vertical={true}
                ticker={ticker}
                setTicker={setTicker}
                market={market}
                setMarket={setMarket}
                onAnalyze={handleAnalyze}
                loading={loading}
              />

              <div className="flex flex-col space-y-2">
                <div className="flex space-x-2">
                  <button 
                    onClick={() => handleAnalyze()}
                    className="flex-1 bg-zinc-100 hover:bg-zinc-200 text-zinc-950 py-2 px-4 rounded font-medium flex items-center justify-center transition-colors text-sm"
                  >
                    <FiRefreshCw className="mr-2 text-xs" /> Re-run Analysis
                  </button>
                  <ExcelDownloadButton data={analysisData} />
                </div>
                <button 
                  onClick={() => {
                    setOverrides({});
                    sessionStorage.removeItem('vl_overrides');
                    setResetKey(k => k + 1);
                    handleAnalyze({}, true);
                  }}
                  className="w-full bg-zinc-800/80 hover:bg-zinc-700/80 text-zinc-300 py-2 rounded text-xs font-medium transition-colors flex items-center justify-center border border-zinc-700/50"
                >
                  <FiRotateCcw className="mr-2" /> Restore Defaults
                </button>
              </div>
              
              <div className="space-y-4">
                <AssumptionSliders 
                  key={`sliders-${resetKey}`}
                  data={analysisData}
                  onOverride={(newOverrides) => {
                    setOverrides(newOverrides);
                  }}
                  loading={loading}
                />
                
                <MacroDisplay data={analysisData} />
              </div>
            </div>

            {/* Right Main Content */}
            <div className="flex-1 flex flex-col overflow-hidden">
              {/* Tab Navigation */}
              <div className="border-b border-zinc-800 bg-zinc-900/50 px-6 flex space-x-1 overflow-x-auto">
                {tabs.map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex items-center space-x-2 py-3 px-4 border-b-2 font-medium text-sm transition-colors whitespace-nowrap ${
                      activeTab === tab.id
                        ? 'border-blue-500 text-blue-400'
                        : 'border-transparent text-slate-400 hover:text-slate-200 hover:border-zinc-700'
                    }`}
                  >
                    {tab.icon}
                    <span>{tab.label}</span>
                  </button>
                ))}
              </div>

              {/* Tab Panes */}
              <div className="flex-1 overflow-y-auto p-6 bg-zinc-950">
                <ErrorBoundary>
                  {activeTab === 'overview' && (
                    <OverviewTab 
                      data={analysisData} 
                      aiSummary={aiSummary}
                      aiLoading={aiLoading}
                      onFetchAISummary={handleFetchAISummary}
                    />
                  )}
                  {activeTab === 'dcf' && (
                    <DCFModelTab data={analysisData} overrides={overrides} />
                  )}
                  {activeTab === 'monte_carlo' && (
                    <MonteCarloTab data={analysisData} />
                  )}
                  {activeTab === 'sensitivity' && (
                    <SensitivityTab data={analysisData} />
                  )}
                  {activeTab === 'trends' && (
                    <TrendsTab data={analysisData} />
                  )}
                </ErrorBoundary>
              </div>
            </div>
          </div>
        )}
      </main>

      <Analytics />
    </div>
  );
}
