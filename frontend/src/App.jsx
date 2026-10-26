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
  FiRotateCcw,
  FiArrowRight,
  FiArrowUpRight,
  FiFileText,
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
import stocksData from './data/stocks.json';

const API_BASE_URL = (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '');
if (API_BASE_URL) {
  axios.defaults.baseURL = API_BASE_URL;
}

const PREVIEW_DATA = {
  CESC: {
    ticker: 'CESC.NS',
    market: 'IN',
    name: 'CESC Limited',
    tabLabel: '🇮🇳 CESC (NSE)',
    currency: '₹',
    fairValue: '₹223.42',
    fairValueNum: 223.42,
    currentPrice: '₹143.47',
    currentPriceNum: 143.47,
    upsidePct: 55.7,
    upsideBadge: 'Regulated Utility Model',
    upsideNote: 'Regulated utility cash flows analyzed via cost-plus rate base model',
    wacc: '9.1%',
    waccNote: 'RBI 10Y G-Sec: 7.1% | Beta: 0.85',
    mcRange: '₹128 – ₹471',
    p5Num: 128,
    p95Num: 471,
  },
  HINDUNILVR: {
    ticker: 'HINDUNILVR.NS',
    market: 'IN',
    name: 'Hindustan Unilever Ltd.',
    tabLabel: '🇮🇳 HUL (NSE)',
    currency: '₹',
    fairValue: '₹750.08',
    fairValueNum: 750.08,
    currentPrice: '₹1,947.00',
    currentPriceNum: 1947.00,
    upsidePct: -61.5,
    upsideBadge: '▼ 61.5% Above DCF',
    upsideNote: 'Trades at 45x P/E quality & scarcity premium over baseline DCF',
    wacc: '11.3%',
    waccNote: 'RBI 10Y G-Sec: 7.1% | Beta: 0.71',
    mcRange: '₹487 – ₹1,556',
    p5Num: 487,
    p95Num: 1556,
  },
  AAPL: {
    ticker: 'AAPL',
    market: 'US',
    name: 'Apple Inc.',
    tabLabel: '🇺🇸 Apple (NASDAQ)',
    currency: '$',
    fairValue: '$85.28',
    fairValueNum: 85.28,
    currentPrice: '$338.98',
    currentPriceNum: 338.98,
    upsidePct: -74.8,
    upsideBadge: '▼ 74.8% Above DCF',
    upsideNote: 'Trades at 38x EV/FCF multiple; market prices in multi-decade AI ecosystem growth',
    wacc: '10.1%',
    waccNote: 'FRED US 10Y: 4.1% | Beta: 1.02',
    mcRange: '$49 – $178',
    p5Num: 49,
    p95Num: 178,
  }
};

// Helper function to format company names cleanly and prevent cutoff or raw ticker display
function formatCompanyName(name, tickerSymbol = '') {
  if (!name && !tickerSymbol) return '';
  let n = String(name || tickerSymbol).trim();
  const cleanSym = String(tickerSymbol || n).replace(/\.(NS|BO)$/i, '').toUpperCase();

  // If name looks like a raw ticker with .NS / .BO (e.g., "Jmfinancil.ns"), resolve from stocks.json
  if (/\.(ns|bo)$/i.test(n) || n.toUpperCase() === cleanSym) {
    const match = Array.isArray(stocksData)
      ? stocksData.find((s) => s.s && s.s.replace(/\.(NS|BO)$/i, '').toUpperCase() === cleanSym)
      : null;
    if (match && match.n) {
      n = match.n;
    } else {
      n = n.replace(/\.(ns|bo)$/i, '').toUpperCase();
    }
  }

  n = n.replace(/\bL\.?$/i, 'Ltd');
  return n;
}

const TypewriterHeadline = ({ fullText = "Intrinsic value, grounded\nin real cash flows", speed = 38, delay = 200 }) => {
  const [displayedText, setDisplayedText] = useState('');
  const [isDone, setIsDone] = useState(false);

  useEffect(() => {
    let index = 0;
    setDisplayedText('');
    setIsDone(false);

    let interval;
    const startTimeout = setTimeout(() => {
      interval = setInterval(() => {
        index++;
        setDisplayedText(fullText.slice(0, index));
        if (index >= fullText.length) {
          clearInterval(interval);
          setIsDone(true);
        }
      }, speed);
    }, delay);

    return () => {
      clearTimeout(startTimeout);
      if (interval) clearInterval(interval);
    };
  }, [fullText, speed, delay]);

  const lines = displayedText.split('\n');

  return (
    <h1 className="font-heromono text-3xl sm:text-5xl md:text-[54px] font-medium tracking-tight text-[#f4eedf] leading-[1.15] drop-shadow-[0_4px_24px_rgba(6,15,32,0.65)] min-h-[72px] sm:min-h-[115px] md:min-h-[125px]">
      {lines[0]}
      {lines.length > 1 && (
        <>
          <br />
          {lines[1]}
        </>
      )}
      <span className={`inline-block w-2 sm:w-2.5 h-6 sm:h-10 md:h-11 ml-1.5 align-middle bg-[#e3b23c] ${isDone ? 'animate-pulse opacity-50' : 'animate-pulse'}`} />
    </h1>
  );
};

export default function App() {
  const [analysisData, setAnalysisData] = useState(() => {
    sessionStorage.removeItem('vl_analysisData'); // Clear stale legacy cache
    const saved = sessionStorage.getItem('vl_analysisData_v2');
    if (!saved) return null;
    try {
      const parsed = JSON.parse(saved);
      if (parsed?.company?.name && /\.(ns|bo)$/i.test(parsed.company.name)) {
        sessionStorage.removeItem('vl_analysisData_v2');
        return null;
      }
      return parsed;
    } catch (_) {
      return null;
    }
  });
  const [loading, setLoading] = useState(false);
  const [loadingTimer, setLoadingTimer] = useState(0);
  const [serverAwake, setServerAwake] = useState(false);
  const [error, setError] = useState(null);
  const abortControllerRef = useRef(null);
  const activeRequestIdRef = useRef(0);
  const valuationCacheRef = useRef(new Map());
  
  const [activeTab, setActiveTab] = useState(() => sessionStorage.getItem('vl_activeTab') || 'overview');
  const [aiSummary, setAiSummary] = useState(() => sessionStorage.getItem('vl_aiSummary') || '');
  const [aiLoading, setAiLoading] = useState(false);
  
  const [ticker, setTicker] = useState(() => sessionStorage.getItem('vl_ticker') || '');
  const [market, setMarket] = useState(() => sessionStorage.getItem('vl_market') || 'auto');
  const [overrides, setOverrides] = useState(() => {
    const saved = sessionStorage.getItem('vl_overrides');
    return saved ? JSON.parse(saved) : {};
  });
  const [monteCarloIterations] = useState(10000);
  const [resetKey, setResetKey] = useState(0);
  const [showMethodology, setShowMethodology] = useState(false);

  const [previewStock, setPreviewStock] = useState('CESC');
  const currentPreview = PREVIEW_DATA[previewStock] || PREVIEW_DATA.CESC;

  useEffect(() => {
    if (analysisData) sessionStorage.setItem('vl_analysisData_v2', JSON.stringify(analysisData));
    else sessionStorage.removeItem('vl_analysisData_v2');
  }, [analysisData]);

  useEffect(() => sessionStorage.setItem('vl_activeTab', activeTab), [activeTab]);
  useEffect(() => sessionStorage.setItem('vl_aiSummary', aiSummary), [aiSummary]);
  
  useEffect(() => {
    if (analysisData?.company?.ticker) {
      sessionStorage.setItem('vl_ticker', analysisData.company.ticker);
    } else if (!loading) {
      sessionStorage.removeItem('vl_ticker');
    }
  }, [analysisData, loading]);

  useEffect(() => sessionStorage.setItem('vl_market', market), [market]);
  useEffect(() => sessionStorage.setItem('vl_overrides', JSON.stringify(overrides)), [overrides]);

  useEffect(() => {
    axios.get('/api/health').then(() => setServerAwake(true)).catch(() => {});
  }, []);

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

  useEffect(() => {
    const savedTicker = sessionStorage.getItem('vl_ticker');
    
    if (savedTicker) {
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
        sessionStorage.removeItem('vl_analysisData_v2');
      }).finally(() => {
        setLoading(false);
      });
    }
  }, []);

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

    const currentReqId = ++activeRequestIdRef.current;

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
      
      if (currentReqId !== activeRequestIdRef.current) {
        return;
      }

      const resolvedTicker = response.data?.company?.ticker || targetTicker;
      const resolvedMarket = response.data?.company?.market || targetMarket;
      const redirectNote = response.data?.company?.redirect_note;

      if (Object.keys(safeOverrides).length === 0) {
        valuationCacheRef.current.set(cacheKey, response.data);
      }
      setServerAwake(true);
      setAnalysisData(response.data);
      setTicker(resolvedTicker);
      setMarket(resolvedMarket);
      sessionStorage.setItem('vl_ticker', resolvedTicker);
      if (redirectNote) {
        toast.success(redirectNote, { duration: 6000 });
      } else {
        toast.success(`Valuation for ${resolvedTicker} ready`);
      }
      
      if (!isHistoryNav) {
        try {
          window.history.pushState(
            { view: 'analysis', ticker: resolvedTicker, market: resolvedMarket },
            '',
            `?ticker=${encodeURIComponent(resolvedTicker)}`
          );
        } catch (_) {}
      }
    } catch (err) {
      if (currentReqId !== activeRequestIdRef.current) {
        return;
      }

      if (axios.isCancel(err) || err.name === 'CanceledError') {
        return;
      }

      let errorMsg = err.response?.data?.detail || err.response?.data?.error || err.message;
      if (err.code === 'ECONNABORTED' || err.message?.includes('timeout')) {
        errorMsg = 'Valuation request timed out. The backend server may be waking up from cold sleep. Please retry in 10 seconds.';
      } else if (errorMsg?.includes('not supported for DCF')) {
        // Keep ETF/REIT explanation
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
      sessionStorage.removeItem('vl_ticker');
      setError(errorMsg);
      toast.error(errorMsg, { duration: 6000 });
    } finally {
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
    sessionStorage.removeItem('vl_analysisData_v2');
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
      toast.success('Research memo generated');
    } catch (err) {
      toast.error('Failed to generate AI summary');
      console.error(err);
    } finally {
      setAiLoading(false);
    }
  };

  const scrollToSection = (id) => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth' });
  };

  const tabs = [
    { id: 'overview', label: 'Valuation Overview', icon: <FiActivity className="w-4 h-4" /> },
    { id: 'dcf', label: 'DCF Cash Flow Model', icon: <FiTrendingUp className="w-4 h-4" /> },
    { id: 'monte_carlo', label: 'Monte Carlo (10k Runs)', icon: <FiCpu className="w-4 h-4" /> },
    { id: 'sensitivity', label: 'Sensitivity Matrix', icon: <FiGrid className="w-4 h-4" /> },
    { id: 'trends', label: 'Historical Trends', icon: <FiBarChart2 className="w-4 h-4" /> }
  ];

  const prevScaleMax = Math.max(currentPreview.currentPriceNum, currentPreview.fairValueNum, currentPreview.p95Num) * 1.15;
  const prevFairPct = Math.min(92, Math.max(8, (currentPreview.fairValueNum / prevScaleMax) * 100));
  const prevPricePct = Math.min(92, Math.max(8, (currentPreview.currentPriceNum / prevScaleMax) * 100));

  // Workspace Top Highlight Calculations
  const wsSymbol = analysisData?.company?.symbol || (analysisData?.company?.currency === 'INR' ? '₹' : '$');
  const wsCurrentPrice = Number(analysisData?.market_data?.current_price || 1);
  const wsFairValue = Number(analysisData?.dcf_result?.implied_price || 0);
  const wsMcMedian = Number(analysisData?.monte_carlo?.stats?.median || wsFairValue);
  const wsP5 = Number(analysisData?.monte_carlo?.stats?.p5 || wsFairValue * 0.65);
  const wsP95 = Number(analysisData?.monte_carlo?.stats?.p95 || wsFairValue * 1.45);
  const wsUpsidePct = ((wsFairValue / wsCurrentPrice) - 1) * 100;
  const wsIsUndervalued = wsUpsidePct >= 0;

  return (
    <div className="min-h-screen bg-[#0c1017] text-[#f4eedf] font-sans flex flex-col selection:bg-[#e3b23c] selection:text-[#0f141c]">
      <Toaster position="top-right" toastOptions={{ className: 'bg-[#141b26] text-[#f4eedf] border border-[#f4eedf]/15 font-sans text-xs font-semibold' }} />
      
      {/* Workspace Sticky Header (Shown ONLY when inside Valuation Workspace) */}
      {analysisData && (
        <header className="sticky top-0 z-50 w-full border-b border-[#f4eedf]/10 bg-[#0c1017]/95 backdrop-blur-md">
          <div className="max-w-[1680px] mx-auto flex flex-wrap items-center justify-between gap-4 px-4 sm:px-6 py-3">
            {/* Brand Logo */}
            <div 
              className="flex items-center gap-3 cursor-pointer group select-none shrink-0"
              onClick={() => handleGoHome(true)}
            >
              <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-[#141b26] border border-[#f4eedf]/12 group-hover:border-[#e3b23c]/50 transition-all">
                <svg className="w-4 h-4 text-[#e3b23c]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 3v18h18" />
                  <path d="m19 9-5 5-4-4-3 3" />
                </svg>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-display text-lg font-bold tracking-tight text-[#f4eedf]">
                  Valuation<span className="text-[#e3b23c]">Lab</span>
                </span>
              </div>
            </div>

            {/* Center: Wide Search Bar */}
            <div className="flex-1 flex justify-center min-w-[280px] max-w-2xl mx-auto">
              <TickerInput
                compact={true}
                ticker={ticker}
                setTicker={setTicker}
                market={market}
                setMarket={setMarket}
                onAnalyze={handleAnalyze}
                loading={loading}
              />
            </div>

            {/* Right Actions */}
            <div className="flex items-center gap-2.5 shrink-0">
              <ExcelDownloadButton data={analysisData} compact={true} />
              <button
                type="button"
                onClick={() => setShowMethodology(true)}
                className="hidden sm:inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-bold text-[#a6b0c3] hover:text-[#f4eedf] bg-[#141b26] hover:bg-[#1f2937] border border-[#f4eedf]/12 rounded-xl transition-colors cursor-pointer"
              >
                <FiFileText className="w-3.5 h-3.5 text-[#e3b23c]" />
                <span>Methodology</span>
              </button>
              <button 
                type="button"
                onClick={() => handleGoHome(true)}
                className="inline-flex items-center gap-1.5 text-xs font-bold text-[#f4eedf] hover:text-[#e3b23c] px-3.5 py-2 rounded-xl bg-[#141b26] hover:bg-[#1f2937] border border-[#f4eedf]/15 transition cursor-pointer"
              >
                <FiRotateCcw className="w-3.5 h-3.5" />
                <span className="hidden md:inline">Home</span>
              </button>
            </div>
          </div>
        </header>
      )}

      {/* Methodology Modal (Spacious, High-Contrast & Readable) */}
      {showMethodology && (
        <div className="fixed inset-0 z-50 bg-[#080c12]/85 backdrop-blur-md flex items-center justify-center p-4 sm:p-6">
          <div className="bg-[#141b26] border border-[#f4eedf]/20 rounded-3xl max-w-3xl w-full max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-6 py-5 border-b border-[#f4eedf]/12 bg-[#0f1520]">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-[#141b26] border border-[#f4eedf]/12 flex items-center justify-center text-[#e3b23c]">
                  <FiFileText className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="font-display text-lg font-bold text-[#f4eedf] tracking-tight">DCF &amp; Cholesky Monte Carlo Methodology</h3>
                  <p className="text-xs text-[#a6b0c3]">Institutional Damodaran-aligned intrinsic valuation pipeline</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowMethodology(false)}
                className="p-2 text-[#a6b0c3] hover:text-[#f4eedf] hover:bg-[#1f2937] rounded-xl transition-colors cursor-pointer"
              >
                <FiX className="w-5 h-5" />
              </button>
            </div>
            
            <div className="p-6 sm:p-7 overflow-y-auto space-y-4 text-sm text-[#f4eedf]/90 leading-relaxed">
              <div className="bg-[#0d121a] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2.5">
                    <span className="font-display text-xs font-bold text-[#e3b23c] font-mono">01.</span>
                    <h4 className="font-display font-bold text-base text-[#f4eedf]">Linear Growth Fade &amp; Operating Margin Convergence</h4>
                  </div>
                  <span className="font-display text-xs text-[#e3b23c] font-semibold bg-[#141b26] px-2.5 py-1 rounded-lg border border-[#f4eedf]/10">
                    FCFF = NOPAT + D&amp;A − CapEx − ΔNWC
                  </span>
                </div>
                <p className="text-[#c5cedd] text-sm leading-relaxed mt-2">
                  Year-1 revenue growth fades linearly toward the long-run nominal GDP terminal rate over 5 years. Operating EBIT margin converges toward sustainable target/historical margins, computing Unlevered Free Cash Flow available to all capital providers.
                </p>
              </div>

              <div className="bg-[#0d121a] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2.5">
                    <span className="font-display text-xs font-bold px-2 py-0.5 rounded-md bg-[#5b8fd9]/15 text-[#8ab4f8] border border-[#5b8fd9]/30">02</span>
                    <h4 className="font-display font-bold text-base text-[#f4eedf]">Dynamic Cost of Capital (WACC, CAPM &amp; Mid-Year Convention)</h4>
                  </div>
                  <span className="font-display text-xs text-[#8ab4f8] font-semibold bg-[#141b26] px-2.5 py-1 rounded-lg border border-[#f4eedf]/10">
                    Ke = Rf + β × ERP &nbsp;|&nbsp; t = 0.5, 1.5 …
                  </span>
                </div>
                <p className="text-[#c5cedd] text-sm leading-relaxed mt-2">
                  Cost of Equity (<strong className="text-[#f4eedf]">Ke</strong>) is anchored to live 10-year sovereign bond yields (India 10Y G-Sec via RBI or US FRED Treasury), blended with after-tax debt cost via synthetic interest-coverage ratings. Cash flows are discounted using the Mid-Year convention (<span className="text-[#f4eedf]">t − 0.5</span>) because earnings accrue evenly throughout the year.
                </p>
              </div>

              <div className="bg-[#0d121a] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2.5">
                    <span className="font-display text-xs font-bold px-2 py-0.5 rounded-md bg-[#34b38a]/15 text-[#34b38a] border border-[#34b38a]/30">03</span>
                    <h4 className="font-display font-bold text-base text-[#f4eedf]">Cholesky Decomposition (Σ = L·Lᵀ) &amp; Fat-Tailed Monte Carlo</h4>
                  </div>
                  <span className="font-display text-xs text-[#34b38a] font-semibold bg-[#141b26] px-2.5 py-1 rounded-lg border border-[#f4eedf]/10">
                    10,000 Runs &nbsp;|&nbsp; df = 5 &nbsp;|&nbsp; 3× Oversampled
                  </span>
                </div>
                <p className="text-[#c5cedd] text-sm leading-relaxed mt-2">
                  Factors a 7×7 empirical correlation matrix (linking Revenue Growth, EBIT Margin, Risk-Free Rate, Beta, ERP, and Debt Costs). Draws 3× oversampled heavy-tailed shocks from Student&apos;s t-distribution (<span className="text-[#f4eedf]">df = 5</span>), rejects invalid economic states (WACC ≤ g), and outputs the 10,000-trial probability distribution (P5 Bear, P50 Median, P95 Bull).
                </p>
              </div>

              <div className="bg-[#0d121a] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2.5">
                    <span className="font-display text-xs font-bold px-2 py-0.5 rounded-md bg-[#e07a5f]/15 text-[#e07a5f] border border-[#e07a5f]/30">04</span>
                    <h4 className="font-display font-bold text-base text-[#f4eedf]">Bank &amp; Financial Institution Auto-Switch (FCFE &amp; Justified P/B)</h4>
                  </div>
                  <span className="font-display text-xs text-[#e07a5f] font-semibold bg-[#141b26] px-2.5 py-1 rounded-lg border border-[#f4eedf]/10">
                    Tier-1 Capital &nbsp;|&nbsp; Direct-to-Equity FCFE
                  </span>
                </div>
                <p className="text-[#c5cedd] text-sm leading-relaxed mt-2">
                  For banks and NBFCs, customer deposits and borrowings are operational working capital rather than debt. The engine automatically switches to a 100%-equity Tier-1 Regulatory Capital FCFE model where terminal equity value is validated through Justified Price-to-Book: <span className="text-[#f4eedf]">P/B = (ROE − g) / (Ke − g)</span>.
                </p>
              </div>

              <div className="bg-[#0d121a] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2.5">
                    <span className="font-display text-xs font-bold px-2 py-0.5 rounded-md bg-[#e3b23c]/15 text-[#e3b23c] border border-[#e3b23c]/30">05</span>
                    <h4 className="font-display font-bold text-base text-[#f4eedf]">Model Validation, Multiples Cross-Check &amp; Distress Logic</h4>
                  </div>
                  <span className="font-display text-xs text-[#e3b23c] font-semibold bg-[#141b26] px-2.5 py-1 rounded-lg border border-[#f4eedf]/10">
                    EV/EBITDA &nbsp;|&nbsp; P/B &nbsp;|&nbsp; Distress Guardrails
                  </span>
                </div>
                <p className="text-[#c5cedd] text-sm leading-relaxed mt-2">
                  Every DCF valuation is cross-checked against market multiples (<strong className="text-[#f4eedf]">EV/EBITDA</strong> for profitable corporates, <strong className="text-[#f4eedf]">EV/Sales</strong> when trailing EBITDA ≤ 0, and <strong className="text-[#f4eedf]">P/B vs. Justified P/B</strong> for Banks/NBFCs) using the divergence formula <span className="text-[#f4eedf]">|Model Multiple − Market Multiple| / Market Multiple</span>:
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 mt-3 text-xs">
                  <div className="bg-[#141b26] p-3 rounded-xl border border-[#f4eedf]/8">
                    <div className="font-display font-bold text-[#34b38a] mb-0.5">✓ VERIFIED (&lt; 50% Divergence Gap)</div>
                    <p className="text-[#a6b0c3] leading-relaxed">
                      DCF implied multiple is within 50% of the current market multiple, confirming baseline cash-flow projections align with peer market pricing.
                    </p>
                  </div>
                  <div className="bg-[#141b26] p-3 rounded-xl border border-[#f4eedf]/8">
                    <div className="font-display font-bold text-[#e3b23c] mb-0.5">⚠️ WARNING (50% – 80% Divergence Gap)</div>
                    <p className="text-[#a6b0c3] leading-relaxed">
                      Moderate divergence between DCF and market multiple (or Terminal Value &gt; 75% of EV). Signals that the market is pricing in higher growth/margins than historical baseline.
                    </p>
                  </div>
                  <div className="bg-[#141b26] p-3 rounded-xl border border-[#f4eedf]/8">
                    <div className="font-display font-bold text-[#e07a5f] mb-0.5">⚠️ FLAGGED (&gt; 80% Divergence Gap)</div>
                    <p className="text-[#a6b0c3] leading-relaxed">
                      Extreme valuation disconnect (&gt;80% gap) or negative operating EBITDA, indicating the stock trades on aggressive future turnaround/growth expectations.
                    </p>
                  </div>
                  <div className="bg-[#141b26] p-3 rounded-xl border border-[#f4eedf]/8">
                    <div className="font-display font-bold text-[#e07a5f] mb-0.5">🚨 DCF UNRELIABLE / DISTRESSED</div>
                    <p className="text-[#a6b0c3] leading-relaxed">
                      Triggered when Balance Sheet Debt exceeds Implied Enterprise Value (<span className="text-[#f4eedf]">Equity Value ≤ 0</span>), when Year-5 FCF is negative (<span className="text-[#f4eedf]">TV = 0</span>), or when &gt;20% of Monte Carlo trials result in equity wipeout.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            <div className="px-6 py-4 border-t border-[#f4eedf]/12 bg-[#0f1520] flex justify-end">
              <button
                type="button"
                onClick={() => setShowMethodology(false)}
                className="px-5 py-2.5 text-xs font-bold bg-[#e3b23c] hover:bg-[#ecc052] text-[#0f141c] rounded-xl transition cursor-pointer shadow-md"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main Content Area */}
      <main className="flex-1 relative flex flex-col">
        
        {/* Loading Overlay */}
        {loading && (
          <div className="fixed inset-0 bg-[#0c1017]/90 backdrop-blur-md z-50 flex flex-col items-center justify-center p-6 text-center">
            <div className="relative mb-6">
              <div className="w-16 h-16 rounded-full border-4 border-[#e3b23c]/20 border-t-[#e3b23c] animate-spin"></div>
              <div className="absolute inset-0 flex items-center justify-center font-display text-xs text-[#e3b23c] font-bold">
                {loadingTimer}s
              </div>
            </div>
            <h2 className="font-display text-2xl sm:text-3xl font-bold text-[#f4eedf] tracking-tight mb-2">
              Valuating {ticker || 'Company'}...
            </h2>
            <p className="text-[#a6b0c3] max-w-md text-xs sm:text-sm leading-relaxed mb-4 min-h-[40px] flex items-center justify-center">
              {loadingTimer < 2
                ? 'Extracting audited SEC / NSE financial statements & market data...'
                : loadingTimer < 5
                ? 'Computing CAPM WACC, 5-year FCFF & 10,000 Cholesky Monte Carlo runs...'
                : !serverAwake && loadingTimer >= 8
                ? 'Waking up cloud valuation engine (~15-25s on cold start)...'
                : 'Finalizing sensitivity matrices & valuation diagnostics...'}
            </p>
            <button
              type="button"
              onClick={handleCancelAnalyze}
              className="mt-2 inline-flex items-center gap-2 px-4 py-2 text-xs font-bold text-[#a6b0c3] hover:text-[#f4eedf] bg-[#141b26] border border-[#f4eedf]/15 rounded-xl transition-colors cursor-pointer"
            >
              <FiX className="w-3.5 h-3.5" />
              <span>Cancel &amp; Return</span>
            </button>
          </div>
        )}

        {/* Error Banner */}
        {error && (
          <div className="bg-[#2c1618] border border-[#e07a5f]/50 text-[#f4eedf] p-4 mx-auto max-w-5xl w-full mt-4 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 rounded-xl shadow-xl z-40">
            <div className="flex items-start gap-3">
              <div className="p-1.5 rounded-lg bg-[#e07a5f]/20 text-[#e07a5f] mt-0.5">
                <FiX className="w-4 h-4" />
              </div>
              <div>
                <p className="font-display font-bold text-base text-[#f4eedf]">Valuation Attempt Incomplete</p>
                <p className="text-xs sm:text-sm text-[#f4eedf]/80 leading-relaxed mt-0.5">{error}</p>
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
                  className="px-3 py-1.5 text-xs font-bold bg-[#e07a5f] text-[#0f141c] rounded-lg transition-colors cursor-pointer"
                >
                  Retry {ticker}
                </button>
              )}
              <button 
                type="button"
                onClick={() => setError(null)} 
                className="text-xs text-[#f4eedf]/80 hover:text-[#f4eedf] px-2.5 py-1.5 rounded-lg border border-[#f4eedf]/20 transition-colors cursor-pointer"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {/* ===================================================================== */}
        {/* LANDING PAGE: PAINTERLY BSE HERO + METHODOLOGY & VISUAL DIAGRAMS      */}
        {/* (All Educational Explanations Live Here, NOT on the Analysis Page!)   */}
        {/* ===================================================================== */}
        {!analysisData && !loading && (
          <div className="flex-1 flex flex-col">
            
            {/* 1. FULL-BLEED PAINTERLY HERO SECTION */}
            <section className="relative min-h-[88vh] w-full flex flex-col justify-between select-none">
              {/* Background Artwork Layer (Scoped overflow-hidden so scaled artwork stays contained without clipping dropdowns) */}
              <div className="absolute inset-0 overflow-hidden pointer-events-none">
                <img
                  src="/bse_acrylic_hero.jpg"
                  alt="Acrylic painting of the Bombay Stock Exchange tower across a sunlit meadow under a deep Prussian-blue sky"
                  className="w-full h-full object-cover scale-[1.32] translate-x-[-3%] translate-y-[-6%] origin-[60%_65%] transition-transform duration-700 ease-out"
                />
                <div className="absolute inset-0 bg-gradient-to-b from-[#071124]/35 via-transparent to-[#0c1017]/95" />
              </div>

              {/* Top-Center Floating Solid Pill Navbar */}
              <div className="relative z-20 pt-6 sm:pt-8 px-4 flex justify-center">
                <nav className="bg-[#141b26]/90 border border-[#f4eedf]/12 rounded-2xl px-4 py-2 flex items-center gap-4 sm:gap-6 shadow-2xl backdrop-blur-md">
                  <button
                    type="button"
                    onClick={() => handleGoHome(true)}
                    className="w-8 h-8 rounded-lg bg-[#f4eedf]/10 border border-[#f4eedf]/15 flex items-center justify-center text-[#f4eedf] hover:bg-[#f4eedf]/20 transition cursor-pointer"
                    title="ValuationLab"
                  >
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M3 3v18h18" />
                      <path d="m19 9-5 5-4-4-3 3" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    onClick={() => scrollToSection('dcf-explainer')}
                    className="text-xs sm:text-sm font-medium text-[#f4eedf]/90 hover:text-white transition cursor-pointer"
                  >
                    Methodology
                  </button>
                  <button
                    type="button"
                    onClick={() => scrollToSection('cholesky-section')}
                    className="text-xs sm:text-sm font-medium text-[#f4eedf]/90 hover:text-white transition cursor-pointer"
                  >
                    Cholesky &amp; WACC
                  </button>
                  <button
                    type="button"
                    onClick={() => scrollToSection('portfolio-guide')}
                    className="text-xs sm:text-sm font-medium text-[#f4eedf]/90 hover:text-white transition cursor-pointer"
                  >
                    Portfolio Guide
                  </button>
                  <button
                    type="button"
                    onClick={() => scrollToSection('live-showcase')}
                    className="text-xs sm:text-sm font-medium text-[#f4eedf]/90 hover:text-white transition cursor-pointer"
                  >
                    Live Models
                  </button>
                </nav>
              </div>

              {/* Upper-Sky Headline (Live Typewriter Effect on Refresh / Mount) */}
              <div className="relative z-20 max-w-4xl mx-auto text-center px-4 mt-6 sm:mt-10 mb-auto">
                <TypewriterHeadline />
              </div>

              {/* Bottom Hero Split: Left Narrative Card + Right Interactive Valuation Search */}
              <div className="relative z-20 max-w-7xl w-full mx-auto px-4 sm:px-8 pb-14 sm:pb-16 pt-12 sm:pt-16 grid grid-cols-1 lg:grid-cols-12 gap-5 items-stretch">
                <div className="lg:col-span-5 bg-[#141b26]/95 border border-[#f4eedf]/12 rounded-2xl p-5 sm:p-6 shadow-2xl backdrop-blur-md flex flex-col justify-between text-left">
                  <p className="text-xs sm:text-sm text-[#f4eedf]/95 leading-relaxed mb-5">
                    Value any Indian or US company from first principles. Extract audited financial statements, discount future cash flows with live sovereign yields, and stress-test fair value across 10,000 Cholesky-correlated Monte Carlo simulations.
                  </p>
                  <div className="flex flex-wrap items-center gap-6 text-xs sm:text-sm font-semibold">
                    <button
                      type="button"
                      onClick={() => scrollToSection('dcf-explainer')}
                      className="inline-flex items-center gap-1.5 text-[#f4eedf] hover:text-[#e3b23c] underline underline-offset-4 decoration-[#f4eedf]/60 hover:decoration-[#e3b23c] transition cursor-pointer"
                    >
                      <span>How DCF works</span>
                      <FiArrowUpRight className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => scrollToSection('portfolio-guide')}
                      className="wavy-link text-[#f4eedf] cursor-pointer"
                    >
                      Build your portfolio
                    </button>
                  </div>
                </div>

                <div className="lg:col-span-7 bg-[#141b26]/95 border border-[#f4eedf]/12 rounded-2xl p-5 sm:p-6 shadow-2xl backdrop-blur-md flex flex-col justify-between text-left">
                  <TickerInput 
                    heroMode={true}
                    ticker={ticker}
                    setTicker={setTicker}
                    market={market}
                    setMarket={setMarket}
                    onAnalyze={handleAnalyze}
                    loading={loading}
                  />

                  <div className="mt-3.5 pt-3 border-t border-[#f4eedf]/10 flex flex-wrap items-center gap-1.5">
                    <span className="text-[11px] font-semibold text-[#a6b0c3] mr-1">
                      Instant Models:
                    </span>
                    {[
                      { sym: 'HINDUNILVR.NS', label: 'HUL', m: 'IN', flag: '🇮🇳' },
                      { sym: 'RELIANCE.NS', label: 'Reliance', m: 'IN', flag: '🇮🇳' },
                      { sym: 'HDFCBANK.NS', label: 'HDFC Bank', m: 'IN', flag: '🇮🇳' },
                      { sym: 'TCS.NS', label: 'TCS', m: 'IN', flag: '🇮🇳' },
                      { sym: 'CESC.NS', label: 'CESC', m: 'IN', flag: '🇮🇳' },
                      { sym: 'AAPL', label: 'Apple', m: 'US', flag: '🇺🇸' },
                      { sym: 'NVDA', label: 'NVIDIA', m: 'US', flag: '🇺🇸' },
                      { sym: 'MSFT', label: 'Microsoft', m: 'US', flag: '🇺🇸' },
                    ].map((item) => (
                      <button
                        key={item.sym}
                        type="button"
                        onClick={() => handleQuickLaunch(item.sym, item.m)}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#0d121a] hover:bg-[#e3b23c] text-[#f4eedf] hover:text-[#0f141c] border border-[#f4eedf]/10 hover:border-[#e3b23c] text-xs font-semibold transition-all cursor-pointer"
                      >
                        <span className="text-[10px]">{item.flag}</span>
                        <span>{item.label}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </section>

            {/* ===================================================================== */}
            {/* BELOW THE HERO: METHODOLOGY & PORTFOLIO GUIDE                         */}
            {/* ===================================================================== */}
            <div className="max-w-[1560px] w-full mx-auto px-6 lg:px-12 py-20 grid grid-cols-1 lg:grid-cols-12 gap-12 xl:gap-16 items-start">
              
              {/* STICKY LEFT-HAND READING GUIDE RAIL (Spacious, Clear & Open) */}
              <aside className="hidden lg:block lg:col-span-4 sticky top-12 pr-6 border-r border-[#f4eedf]/10 space-y-8">
                <div>
                  <span className="text-xs font-display uppercase tracking-[0.22em] text-[#e3b23c] block mb-3 font-bold">
                    Methodology Guide
                  </span>
                  <h3 className="font-display text-2xl font-bold text-[#f4eedf] tracking-tight mb-3">
                    How Our Valuation Engine Works
                  </h3>
                  <p className="text-sm text-[#a6b0c3] leading-relaxed">
                    Walk through the exact mathematical pipeline we run when you analyze a stock—from operating margins and discount rates to Cholesky Monte Carlo simulations.
                  </p>
                </div>

                <nav className="space-y-3">
                  {[
                    { id: 'dcf-explainer', num: '01', title: 'Operating Margin & Free Cash Flow (FCFF)', subtitle: 'Linear growth fade & revenue-to-FCFF waterfall' },
                    { id: 'wacc-section', num: '02', title: 'Discount Rate (WACC, CAPM & Mid-Year)', subtitle: 'Sovereign 10Y yields, synthetic spreads & mid-year discounting' },
                    { id: 'cholesky-section', num: '03', title: 'Cholesky Decomposition & 10,000 Runs', subtitle: '7×7 empirical correlation matrix & Student’s t-shocks' },
                    { id: 'portfolio-guide', num: '04', title: 'Incorporating DCF in Stock Analysis', subtitle: 'Margin of safety, compounders & portfolio sizing' },
                    { id: 'live-showcase', num: '05', title: 'Verified Live Engine Benchmarks', subtitle: 'Sample DCF models & workspace launch' },
                  ].map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => scrollToSection(item.id)}
                      className="w-full text-left p-3.5 rounded-2xl bg-[#141b26]/50 hover:bg-[#141b26] border border-[#f4eedf]/8 hover:border-[#e3b23c]/40 transition-all cursor-pointer group flex items-start gap-3.5 shadow-sm"
                    >
                      <span className="w-8 h-8 rounded-xl bg-[#0d121a] text-[#e3b23c] border border-[#f4eedf]/10 group-hover:bg-[#e3b23c] group-hover:text-[#0f141c] flex items-center justify-center font-display font-bold text-xs shrink-0 transition-colors">
                        {item.num}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="font-display font-bold text-sm text-[#f4eedf] group-hover:text-[#e3b23c] transition-colors leading-snug">
                          {item.title}
                        </div>
                        <div className="text-xs text-[#a6b0c3] mt-1 leading-normal">
                          {item.subtitle}
                        </div>
                      </div>
                    </button>
                  ))}
                </nav>

                {/* Mathematical Guardrails Reference Card */}
                <div className="p-4 rounded-2xl bg-[#0d121a] border border-[#f4eedf]/10 space-y-2.5">
                  <span className="text-[10px] font-display uppercase tracking-wider text-[#e3b23c] font-bold block">
                    Institutional Standards
                  </span>
                  <div className="space-y-2 text-xs">
                    <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                      <span className="text-[#a6b0c3]">Discount Period</span>
                      <span className="font-display font-bold text-[#f4eedf]">Mid-Year (t − 0.5)</span>
                    </div>
                    <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                      <span className="text-[#a6b0c3]">Terminal Anchor</span>
                      <span className="font-display font-bold text-[#f4eedf]">Nominal GDP Cap</span>
                    </div>
                    <div className="flex justify-between items-center py-1">
                      <span className="text-[#a6b0c3]">Fat-Tailed Shocks</span>
                      <span className="font-display font-bold text-[#34b38a]">Student&apos;s t (df = 5)</span>
                    </div>
                  </div>
                </div>
              </aside>

              {/* MAIN CONTINUOUS EDITORIAL FLOW (8 COLUMNS) */}
              <div className="lg:col-span-8 divide-y divide-[#f4eedf]/12">

                {/* CHAPTER 01: OPERATING MARGIN, GROWTH FADE & FREE CASH FLOW (FCFF) */}
                <section id="dcf-explainer" className="pb-16">
                  <span className="text-xs font-display uppercase tracking-[0.2em] text-[#34b38a] block mb-2 font-bold">
                    01 · Cash Flow &amp; Operating Margin Architecture
                  </span>
                  <h2 className="font-display text-2xl sm:text-4xl font-bold text-[#f4eedf] tracking-tight mb-4 leading-tight">
                    What a DCF valuation actually measures — from Revenue Growth and Operating Margin to Free Cash Flow
                  </h2>
                  <p className="text-[#a6b0c3] text-sm sm:text-base leading-relaxed mb-8 max-w-3xl">
                    Every day, the stock market quotes a <strong className="text-[#f4eedf] font-semibold">share price</strong> driven by sentiment and headlines. A <strong className="text-[#f4eedf] font-semibold">Discounted Cash Flow (DCF)</strong> model measures the <strong className="text-[#e3b23c] font-semibold">intrinsic value of the business itself</strong> based on the actual cash it can distribute after paying taxes and reinvesting in operations.
                  </p>

                  <div className="grid grid-cols-1 xl:grid-cols-12 gap-8 items-center pt-4">
                    <div className="xl:col-span-5 space-y-5">
                      <div className="border-l-2 border-[#34b38a] pl-4">
                        <h3 className="font-display text-base font-bold text-[#f4eedf]">
                          Linear Revenue Growth Fade (Years 1 → 5)
                        </h3>
                        <p className="text-xs sm:text-sm text-[#a6b0c3] mt-1 leading-relaxed">
                          No company grows at 20%+ forever. Our engine takes Year-1 Revenue Growth (<span className="font-display font-bold text-[#f4eedf]">g₁</span>) and <strong className="text-[#f4eedf] font-medium">linearly fades</strong> it each year toward the economy&apos;s long-run nominal GDP growth rate (<span className="font-display font-bold text-[#f4eedf]">g_terminal</span>).
                        </p>
                      </div>

                      <div className="border-l-2 border-[#e3b23c] pl-4">
                        <h3 className="font-display text-base font-bold text-[#f4eedf]">
                          Operating EBIT Margin Convergence &amp; Reinvestment
                        </h3>
                        <p className="text-xs sm:text-sm text-[#a6b0c3] mt-1 leading-relaxed">
                          Operating Margin (<span className="font-display font-bold text-[#f4eedf]">EBIT / Revenue</span>) measures how much profit is kept per ₹100 or $100 of sales. After deducting corporate taxes to get <strong className="text-[#f4eedf] font-medium">NOPAT</strong>, we add back non-cash D&amp;A and subtract physical CapEx and Working Capital (<span className="font-display font-bold text-[#f4eedf]">ΔNWC</span>) required to sustain growth.
                        </p>
                      </div>
                    </div>

                    {/* Visual SVG Diagram: Growth Fade & Margin-to-FCFF Pipeline */}
                    <div className="xl:col-span-7 bg-[#141b26] rounded-2xl p-5 sm:p-6 border border-[#f4eedf]/10">
                      <div className="flex justify-between items-center mb-3">
                        <span className="text-[11px] font-display uppercase tracking-wider text-[#a6b0c3] font-bold">
                          5-Year Linear Growth Fade &amp; FCFF Waterfall
                        </span>
                        <span className="text-[11px] font-display font-bold text-[#34b38a]">
                          FCFF = NOPAT + D&amp;A − CapEx − ΔNWC
                        </span>
                      </div>
                      <svg viewBox="0 0 600 230" className="w-full h-auto">
                        <text x="15" y="22" fill="#f4eedf" fontSize="11" fontWeight="700" fontFamily="Plus Jakarta Sans, sans-serif">
                          A. Revenue Growth Linear Decay (Yr 1 → Yr 5)
                        </text>
                        <line x1="25" y1="175" x2="270" y2="175" stroke="#f4eedf" strokeOpacity="0.2" strokeWidth="1" />
                        <line x1="25" y1="40" x2="25" y2="175" stroke="#f4eedf" strokeOpacity="0.2" strokeWidth="1" />
                        <line x1="25" y1="145" x2="270" y2="145" stroke="#e3b23c" strokeDasharray="4 4" strokeWidth="1.2" />
                        <text x="175" y="138" fill="#e3b23c" fontSize="9.5" fontFamily="Space Grotesk, sans-serif">
                          Terminal g (GDP Cap)
                        </text>
                        <polyline
                          fill="none"
                          stroke="#34b38a"
                          strokeWidth="3"
                          points="45,58 95,80 145,102 195,123 245,145"
                        />
                        {[
                          { x: 45, y: 58, yr: 'Yr 1', val: '16%' },
                          { x: 95, y: 80, yr: 'Yr 2', val: '13.4%' },
                          { x: 145, y: 102, yr: 'Yr 3', val: '10.8%' },
                          { x: 195, y: 123, yr: 'Yr 4', val: '8.1%' },
                          { x: 245, y: 145, yr: 'Yr 5', val: '5.5%' },
                        ].map((pt, idx) => (
                          <g key={idx}>
                            <circle cx={pt.x} cy={pt.y} r="4.5" fill="#34b38a" />
                            <text x={pt.x} y={pt.y - 9} textAnchor="middle" fill="#f4eedf" fontSize="9" fontFamily="Space Grotesk, sans-serif">
                              {pt.val}
                            </text>
                            <text x={pt.x} y="192" textAnchor="middle" fill="#a6b0c3" fontSize="9.5" fontFamily="Space Grotesk, sans-serif">
                              {pt.yr}
                            </text>
                          </g>
                        ))}

                        <line x1="295" y1="20" x2="295" y2="205" stroke="#f4eedf" strokeOpacity="0.1" strokeWidth="1" />

                        <text x="315" y="22" fill="#f4eedf" fontSize="11" fontWeight="700" fontFamily="Plus Jakarta Sans, sans-serif">
                          B. Operating Margin to Free Cash Flow
                        </text>
                        <rect x="320" y="45" width="42" height="130" rx="4" fill="#5b8fd9" fillOpacity="0.85" />
                        <text x="341" y="192" textAnchor="middle" fill="#a6b0c3" fontSize="9" fontFamily="Space Grotesk, sans-serif">Revenue</text>
                        <text x="341" y="40" textAnchor="middle" fill="#8ab4f8" fontSize="9" fontFamily="Space Grotesk, sans-serif">100%</text>

                        <rect x="378" y="105" width="42" height="70" rx="4" fill="#e3b23c" fillOpacity="0.85" />
                        <text x="399" y="192" textAnchor="middle" fill="#a6b0c3" fontSize="9" fontFamily="Space Grotesk, sans-serif">EBIT</text>
                        <text x="399" y="99" textAnchor="middle" fill="#e3b23c" fontSize="9" fontFamily="Space Grotesk, sans-serif">Margin</text>

                        <rect x="436" y="122" width="42" height="53" rx="4" fill="#e07a5f" fillOpacity="0.8" />
                        <text x="457" y="192" textAnchor="middle" fill="#a6b0c3" fontSize="9" fontFamily="Space Grotesk, sans-serif">NOPAT</text>
                        <text x="457" y="116" textAnchor="middle" fill="#e07a5f" fontSize="9" fontFamily="Space Grotesk, sans-serif">−Tax</text>

                        <rect x="494" y="135" width="42" height="40" rx="4" fill="#a6b0c3" fillOpacity="0.5" />
                        <text x="515" y="192" textAnchor="middle" fill="#a6b0c3" fontSize="9" fontFamily="Space Grotesk, sans-serif">−CapEx</text>
                        <text x="515" y="129" textAnchor="middle" fill="#a6b0c3" fontSize="9" fontFamily="Space Grotesk, sans-serif">+D&amp;A</text>

                        <rect x="548" y="118" width="42" height="57" rx="4" fill="#34b38a" />
                        <text x="569" y="192" textAnchor="middle" fill="#34b38a" fontSize="9.5" fontWeight="700" fontFamily="Space Grotesk, sans-serif">FCFF</text>
                        <text x="569" y="112" textAnchor="middle" fill="#34b38a" fontSize="9" fontWeight="700" fontFamily="Space Grotesk, sans-serif">Cash</text>
                      </svg>
                    </div>
                  </div>
                </section>

                {/* CHAPTER 02: DISCOUNT RATE (WACC, CAPM & MID-YEAR DISCOUNTING) */}
                <section id="wacc-section" className="py-16">
                  <span className="text-xs font-display uppercase tracking-[0.2em] text-[#5b8fd9] block mb-2 font-bold">
                    02 · Time Value of Money &amp; Cost of Capital (WACC)
                  </span>
                  <h2 className="font-display text-2xl sm:text-3xl font-bold text-[#f4eedf] tracking-tight mb-4">
                    How the Discount Rate (WACC) works — and why higher interest rates compress fair value
                  </h2>
                  <p className="text-[#a6b0c3] text-sm sm:text-base leading-relaxed mb-8 max-w-3xl">
                    ₹100 or $100 received five years from now is worth less than the same amount in your pocket today because of inflation and opportunity cost. The <strong className="text-[#f4eedf] font-semibold">Weighted Average Cost of Capital (WACC)</strong> is the annual hurdle rate used to translate future cash flows into present-day value.
                  </p>

                  <div className="grid grid-cols-1 xl:grid-cols-12 gap-8 items-center">
                    <div className="xl:col-span-5 space-y-5">
                      <div className="border-l-2 border-[#5b8fd9] pl-4">
                        <h3 className="font-display text-base font-bold text-[#f4eedf]">
                          Cost of Equity via CAPM (Ke = Rf + β × ERP)
                        </h3>
                        <p className="text-xs sm:text-sm text-[#a6b0c3] mt-1 leading-relaxed">
                          Anchored to live <strong className="text-[#f4eedf]">10-Year Sovereign Bond Yields</strong> (India 10Y G-Sec via RBI or US 10Y Treasury via FRED), plus the equity risk premium scaled by the stock&apos;s historical volatility (<span className="font-display font-bold text-[#f4eedf]">Beta</span>).
                        </p>
                      </div>

                      <div className="border-l-2 border-[#e3b23c] pl-4">
                        <h3 className="font-display text-base font-bold text-[#f4eedf]">
                          After-Tax Cost of Debt &amp; Mid-Year Discounting
                        </h3>
                        <p className="text-xs sm:text-sm text-[#a6b0c3] mt-1 leading-relaxed">
                          Debt is priced using a synthetic interest-coverage rating (<span className="font-display font-bold text-[#f4eedf]">EBIT / Interest Expense</span>) minus the corporate tax shield. Because companies earn cash throughout the year rather than on December 31st, we discount at <strong className="text-[#f4eedf]">Mid-Year periods (t = 0.5, 1.5, … 4.5)</strong>.
                        </p>
                      </div>
                    </div>

                    <div className="xl:col-span-7 bg-[#141b26] rounded-2xl p-5 sm:p-6 border border-[#f4eedf]/10">
                      <div className="flex justify-between items-center mb-3">
                        <span className="text-[11px] font-display uppercase tracking-wider text-[#a6b0c3] font-bold">
                          WACC Synthesis &amp; Mid-Year Present Value Decay
                        </span>
                        <span className="text-[11px] font-display font-bold text-[#e3b23c]">
                          PV = FCFF_t / (1 + WACC)^(t − 0.5)
                        </span>
                      </div>
                      <svg viewBox="0 0 600 215" className="w-full h-auto">
                        <rect x="15" y="25" width="165" height="68" rx="8" fill="#0d121a" stroke="#5b8fd9" strokeOpacity="0.6" />
                        <text x="27" y="45" fill="#8ab4f8" fontSize="10" fontWeight="700" fontFamily="Space Grotesk, sans-serif">COST OF EQUITY (Ke)</text>
                        <text x="27" y="63" fill="#f4eedf" fontSize="11" fontFamily="Space Grotesk, sans-serif">Rf + β × (Rm − Rf)</text>
                        <text x="27" y="80" fill="#a6b0c3" fontSize="9.5" fontFamily="Plus Jakarta Sans, sans-serif">10Y G-Sec / Treasury + Beta</text>

                        <rect x="15" y="115" width="165" height="68" rx="8" fill="#0d121a" stroke="#e3b23c" strokeOpacity="0.6" />
                        <text x="27" y="135" fill="#e3b23c" fontSize="10" fontWeight="700" fontFamily="Space Grotesk, sans-serif">AFTER-TAX DEBT (Kd)</text>
                        <text x="27" y="153" fill="#f4eedf" fontSize="11" fontFamily="Space Grotesk, sans-serif">(Rf + Spread) × (1 − T)</text>
                        <text x="27" y="170" fill="#a6b0c3" fontSize="9.5" fontFamily="Plus Jakarta Sans, sans-serif">Synthetic Coverage Rating</text>

                        <path d="M180 59 L225 98" stroke="#5b8fd9" strokeWidth="1.8" fill="none" />
                        <path d="M180 149 L225 110" stroke="#e3b23c" strokeWidth="1.8" fill="none" />

                        <rect x="225" y="76" width="115" height="56" rx="10" fill="#182232" stroke="#f4eedf" strokeOpacity="0.3" />
                        <text x="282" y="99" textAnchor="middle" fill="#e3b23c" fontSize="11" fontWeight="700" fontFamily="Space Grotesk, sans-serif">BLENDED WACC</text>
                        <text x="282" y="117" textAnchor="middle" fill="#f4eedf" fontSize="10" fontFamily="Space Grotesk, sans-serif">Hurdle Rate</text>

                        <path d="M340 104 L375 104" stroke="#f4eedf" strokeOpacity="0.4" strokeWidth="1.5" />

                        <text x="385" y="25" fill="#f4eedf" fontSize="10.5" fontWeight="700" fontFamily="Plus Jakarta Sans, sans-serif">
                          Nominal FCF (Outline) vs. Present Value Today (Solid)
                        </text>
                        {[
                          { x: 395, nomH: 75, pvH: 71, lbl: 't=0.5' },
                          { x: 438, nomH: 85, pvH: 73, lbl: 't=1.5' },
                          { x: 481, nomH: 96, pvH: 75, lbl: 't=2.5' },
                          { x: 524, nomH: 108, pvH: 76, lbl: 't=3.5' },
                          { x: 565, nomH: 120, pvH: 77, lbl: 't=4.5' },
                        ].map((b, i) => (
                          <g key={i}>
                            <rect
                              x={b.x - 12}
                              y={170 - b.nomH}
                              width="24"
                              height={b.nomH}
                              rx="3"
                              fill="none"
                              stroke="#a6b0c3"
                              strokeOpacity="0.45"
                              strokeDasharray="2 2"
                            />
                            <rect
                              x={b.x - 12}
                              y={170 - b.pvH}
                              width="24"
                              height={b.pvH}
                              rx="3"
                              fill="#34b38a"
                            />
                            <text x={b.x} y="187" textAnchor="middle" fill="#a6b0c3" fontSize="8.5" fontFamily="Space Grotesk, sans-serif">
                              {b.lbl}
                            </text>
                          </g>
                        ))}
                      </svg>
                    </div>
                  </div>
                </section>

                {/* CHAPTER 03: CHOLESKY DECOMPOSITION & FAT-TAILED MONTE CARLO */}
                <section id="cholesky-section" className="py-16">
                  <span className="text-xs font-display uppercase tracking-[0.2em] text-[#e3b23c] block mb-2 font-bold">
                    03 · Cholesky Decomposition (Σ = L·Lᵀ) &amp; Fat-Tailed Monte Carlo
                  </span>
                  <h2 className="font-display text-2xl sm:text-3xl font-bold text-[#f4eedf] tracking-tight mb-4">
                    Why we use Cholesky Decomposition instead of naive random numbers
                  </h2>
                  <p className="text-[#a6b0c3] text-sm sm:text-base leading-relaxed mb-8 max-w-3xl">
                    In the real world, financial variables do not move independently—when a company&apos;s revenue growth accelerates, operating leverage usually expands its EBIT margin at the same time (<span className="font-display font-bold text-[#e3b23c]">ρ &gt; 0</span>). ValuationLab uses <strong className="text-[#f4eedf] font-semibold">Cholesky Matrix Decomposition</strong> paired with <strong className="text-[#f4eedf] font-semibold">fat-tailed Student&apos;s t-shocks (df = 5)</strong> across 10,000 valid simulations.
                  </p>

                  <div className="bg-[#141b26] rounded-2xl p-5 sm:p-7 border border-[#f4eedf]/12 mb-8">
                    <div className="flex flex-wrap justify-between items-center gap-2 mb-4">
                      <span className="text-xs font-display uppercase tracking-wider text-[#e3b23c] font-bold">
                        Architecture Diagram · 7-Variable Cholesky Decomposition Pipeline (L @ z)
                      </span>
                      <span className="text-xs font-display font-semibold text-[#a6b0c3]">
                        30,000 Oversampled Draws → 10,000 Economically Valid DCF Worlds
                      </span>
                    </div>

                    <svg viewBox="0 0 820 230" className="w-full h-auto">
                      <rect x="10" y="20" width="185" height="190" rx="10" fill="#0d121a" stroke="#f4eedf" strokeOpacity="0.18" />
                      <text x="24" y="43" fill="#e3b23c" fontSize="10" fontWeight="700" fontFamily="Space Grotesk, sans-serif">
                        1. CORRELATION MATRIX (Σ)
                      </text>
                      <text x="24" y="61" fill="#f4eedf" fontSize="10.5" fontWeight="600" fontFamily="Plus Jakarta Sans, sans-serif">
                        7 Stochastic Risk Drivers:
                      </text>
                      <text x="24" y="80" fill="#34b38a" fontSize="9.5" fontFamily="Space Grotesk, sans-serif">• Rev Growth (g) ↔ Margin (m)</text>
                      <text x="34" y="95" fill="#e3b23c" fontSize="9.5" fontFamily="Space Grotesk, sans-serif">Empirical Corr: ρ = Cov(g,m)</text>
                      <text x="24" y="114" fill="#a6b0c3" fontSize="9.5" fontFamily="Space Grotesk, sans-serif">• Risk-Free Rate (Rf)</text>
                      <text x="24" y="130" fill="#a6b0c3" fontSize="9.5" fontFamily="Space Grotesk, sans-serif">• Regression Beta (β)</text>
                      <text x="24" y="146" fill="#a6b0c3" fontSize="9.5" fontFamily="Space Grotesk, sans-serif">• Equity Risk Prem (ERP)</text>
                      <text x="24" y="162" fill="#a6b0c3" fontSize="9.5" fontFamily="Space Grotesk, sans-serif">• Cost of Debt (Kd)</text>
                      <text x="24" y="178" fill="#a6b0c3" fontSize="9.5" fontFamily="Space Grotesk, sans-serif">• Equity Weight (We)</text>

                      <path d="M195 115 L222 115" stroke="#e3b23c" strokeWidth="2" />

                      <rect x="222" y="20" width="195" height="190" rx="10" fill="#0d121a" stroke="#5b8fd9" strokeOpacity="0.45" />
                      <text x="236" y="43" fill="#8ab4f8" fontSize="10" fontWeight="700" fontFamily="Space Grotesk, sans-serif">
                        2. CHOLESKY FACTOR (Σ = L·Lᵀ)
                      </text>
                      <rect x="236" y="55" width="70" height="62" rx="4" fill="#151e2c" stroke="#5b8fd9" strokeOpacity="0.3" />
                      <text x="246" y="72" fill="#34b38a" fontSize="10" fontFamily="Space Grotesk, sans-serif">1   0   0</text>
                      <text x="246" y="89" fill="#e3b23c" fontSize="10" fontFamily="Space Grotesk, sans-serif">ρ  √1−ρ² 0</text>
                      <text x="246" y="106" fill="#8ab4f8" fontSize="10" fontFamily="Space Grotesk, sans-serif">0   0   1</text>

                      <text x="316" y="76" fill="#f4eedf" fontSize="10.5" fontWeight="700" fontFamily="Space Grotesk, sans-serif">× z (t, df=5)</text>
                      <text x="316" y="93" fill="#a6b0c3" fontSize="9" fontFamily="Plus Jakarta Sans, sans-serif">Heavy-tailed</text>
                      <text x="316" y="106" fill="#a6b0c3" fontSize="9" fontFamily="Plus Jakarta Sans, sans-serif">market shocks</text>

                      <text x="236" y="140" fill="#f4eedf" fontSize="9.5" fontWeight="600" fontFamily="Space Grotesk, sans-serif">
                        Correlated: X = μ + L · z
                      </text>
                      <text x="236" y="158" fill="#a6b0c3" fontSize="9" fontFamily="Plus Jakarta Sans, sans-serif">
                        Preserves historical co-movement
                      </text>
                      <text x="236" y="173" fill="#a6b0c3" fontSize="9" fontFamily="Plus Jakarta Sans, sans-serif">
                        while modeling fat-tail shocks.
                      </text>

                      <path d="M417 115 L444 115" stroke="#5b8fd9" strokeWidth="2" />

                      <rect x="444" y="20" width="165" height="190" rx="10" fill="#0d121a" stroke="#34b38a" strokeOpacity="0.4" />
                      <text x="458" y="43" fill="#34b38a" fontSize="10" fontWeight="700" fontFamily="Space Grotesk, sans-serif">
                        3. GUARDRAILS
                      </text>
                      <text x="458" y="65" fill="#f4eedf" fontSize="10" fontWeight="600" fontFamily="Plus Jakarta Sans, sans-serif">
                        3× Oversampling (30k)
                      </text>
                      <text x="458" y="84" fill="#a6b0c3" fontSize="9.5" fontFamily="Plus Jakarta Sans, sans-serif">
                        Rejects invalid worlds:
                      </text>
                      <text x="458" y="103" fill="#e07a5f" fontSize="9.5" fontFamily="Space Grotesk, sans-serif">
                        ✗ WACC ≤ Terminal g
                      </text>
                      <text x="458" y="120" fill="#e07a5f" fontSize="9.5" fontFamily="Space Grotesk, sans-serif">
                        ✗ WACC − g &lt; 1.5%
                      </text>
                      <text x="458" y="137" fill="#e07a5f" fontSize="9.5" fontFamily="Space Grotesk, sans-serif">
                        ✗ Negative Kd or Ke
                      </text>
                      <text x="458" y="165" fill="#34b38a" fontSize="10" fontWeight="700" fontFamily="Space Grotesk, sans-serif">
                        ✓ Slices 10,000 Valid
                      </text>
                      <text x="458" y="180" fill="#34b38a" fontSize="10" fontWeight="700" fontFamily="Space Grotesk, sans-serif">
                        5-Yr DCF Valuations
                      </text>

                      <path d="M609 115 L636 115" stroke="#34b38a" strokeWidth="2" />

                      <rect x="636" y="20" width="174" height="190" rx="10" fill="#0d121a" stroke="#e3b23c" strokeOpacity="0.5" />
                      <text x="650" y="43" fill="#e3b23c" fontSize="10" fontWeight="700" fontFamily="Space Grotesk, sans-serif">
                        4. FAIR VALUE BAND
                      </text>
                      {[
                        { x: 652, h: 16, c: '#2d3848' },
                        { x: 666, h: 32, c: '#e3b23c' },
                        { x: 680, h: 54, c: '#5b8fd9' },
                        { x: 694, h: 78, c: '#5b8fd9' },
                        { x: 708, h: 95, c: '#34b38a' },
                        { x: 722, h: 82, c: '#5b8fd9' },
                        { x: 736, h: 60, c: '#5b8fd9' },
                        { x: 750, h: 38, c: '#5b8fd9' },
                        { x: 764, h: 24, c: '#e3b23c' },
                        { x: 778, h: 12, c: '#2d3848' },
                      ].map((bar, idx) => (
                        <rect
                          key={idx}
                          x={bar.x}
                          y={155 - bar.h}
                          width="10"
                          height={bar.h}
                          rx="2"
                          fill={bar.c}
                        />
                      ))}
                      <line x1="648" y1="155" x2="795" y2="155" stroke="#f4eedf" strokeOpacity="0.2" />
                      <text x="668" y="172" textAnchor="middle" fill="#e3b23c" fontSize="8.5" fontFamily="Space Grotesk, sans-serif">P5</text>
                      <text x="713" y="172" textAnchor="middle" fill="#34b38a" fontSize="8.5" fontWeight="700" fontFamily="Space Grotesk, sans-serif">P50 Median</text>
                      <text x="768" y="172" textAnchor="middle" fill="#e3b23c" fontSize="8.5" fontFamily="Space Grotesk, sans-serif">P95</text>
                      <text x="722" y="192" textAnchor="middle" fill="#a6b0c3" fontSize="9" fontFamily="Plus Jakarta Sans, sans-serif">
                        90% Confidence Interval
                      </text>
                    </svg>
                  </div>
                </section>

                {/* CHAPTER 04: PORTFOLIO GUIDE */}
                <section id="portfolio-guide" className="py-16">
                  <span className="text-xs font-display uppercase tracking-[0.2em] text-[#e07a5f] block mb-2 font-bold">
                    04 · Practical Application &amp; Portfolio Construction
                  </span>
                  <h2 className="font-display text-2xl sm:text-3xl font-bold text-[#f4eedf] tracking-tight mb-4">
                    How to incorporate DCF valuations into your own stock analysis and portfolio
                  </h2>

                  <div className="divide-y divide-[#f4eedf]/10 border-t border-b border-[#f4eedf]/10 mt-6">
                    {[
                      {
                        num: '01',
                        title: 'Demand a Margin of Safety on Cyclical & Value Stocks',
                        desc: 'When today’s Market Price sits below the DCF Intrinsic Fair Value and near the lower half (P25–P50) of the Monte Carlo distribution, you have a structural Margin of Safety—you are paying less than the business is worth even if growth stays ordinary.'
                      },
                      {
                        num: '02',
                        title: 'Reverse-Engineer What the Market is Pricing In for Compounders',
                        desc: 'High-quality franchises (such as HUL, Titan, or NVIDIA) often trade above baseline historical DCF. Use the Model Assumptions sliders inside the workspace to raise Revenue Growth or Margin until Fair Value matches today’s share price—then decide if that implied growth rate is achievable.'
                      },
                      {
                        num: '03',
                        title: 'Interpret Model Validation Badges (VERIFIED, WARNING, FLAGGED & DISTRESSED)',
                        desc: 'The engine cross-checks DCF Implied EV/EBITDA (or P/B for Banks/NBFCs) against Current Market Multiples. VERIFIED (<50% gap) confirms tight alignment with peer pricing; WARNING (50%–80% gap) indicates the market prices in higher growth/margins than historical averages; FLAGGED (>80% gap) signals an extreme growth premium or negative EBITDA turnaround; and DCF UNRELIABLE / DISTRESSED alerts you when Balance Sheet Debt exceeds Enterprise Value (Equity Value ≤ 0) or >20% of Monte Carlo simulations result in equity wipeout.'
                      },
                      {
                        num: '04',
                        title: 'Size Portfolio Positions Using the P5–P95 Dispersion Band',
                        desc: 'Check the width of the 90% Monte Carlo confidence band. A tight P5–P95 band indicates predictable cash flows suited for a core 5–8% portfolio weight; a wide band means the stock is highly sensitive to WACC and terminal assumptions, warranting a smaller 1–3% position.'
                      }
                    ].map((row) => (
                      <div key={row.num} className="py-6 grid grid-cols-1 md:grid-cols-12 gap-4 items-start">
                        <div className="md:col-span-4 flex items-baseline gap-3">
                          <span className="font-display text-sm font-bold text-[#e3b23c]">{row.num}.</span>
                          <h3 className="font-display text-base sm:text-lg font-bold text-[#f4eedf] leading-snug">{row.title}</h3>
                        </div>
                        <p className="md:col-span-8 text-xs sm:text-sm text-[#a6b0c3] leading-relaxed">
                          {row.desc}
                        </p>
                      </div>
                    ))}
                  </div>
                </section>

                {/* CHAPTER 05: LIVE ENGINE SHOWCASE */}
                <section id="live-showcase" className="pt-16">
                  <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-8">
                    <div>
                      <span className="text-xs font-display uppercase tracking-[0.2em] text-[#e3b23c] block mb-2 font-bold">
                        05 · Verified Engine Benchmarks
                      </span>
                      <h2 className="font-display text-2xl sm:text-3xl font-bold text-[#f4eedf] tracking-tight">
                        Inspect sample DCF valuations &amp; launch the workspace
                      </h2>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {Object.keys(PREVIEW_DATA).map((key) => {
                        const item = PREVIEW_DATA[key];
                        const isSelected = previewStock === key;
                        return (
                          <button 
                            key={key}
                            type="button"
                            onClick={() => setPreviewStock(key)}
                            className={`text-xs font-bold px-3.5 py-2 rounded-xl transition cursor-pointer ${
                              isSelected
                                ? 'bg-[#e3b23c] text-[#0f141c]'
                                : 'bg-[#141b26] text-[#a6b0c3] hover:text-[#f4eedf] border border-[#f4eedf]/10'
                            }`}
                          >
                            {item.tabLabel}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div className="border-t border-b border-[#f4eedf]/15 py-6">
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 pb-6 border-b border-[#f4eedf]/10">
                      <div>
                        <span className="text-xs text-[#a6b0c3] block mb-1">DCF Intrinsic Fair Value</span>
                        <span className={`font-display text-3xl font-bold tabular-nums ${
                          currentPreview.upsidePct >= 0 ? 'text-[#34b38a]' : 'text-[#e3b23c]'
                        }`}>
                          {currentPreview.fairValue}
                        </span>
                        <span className={`text-xs font-bold block mt-1 ${
                          currentPreview.upsidePct >= 0 ? 'text-[#34b38a]' : 'text-[#e07a5f]'
                        }`}>
                          {currentPreview.upsideBadge}
                        </span>
                      </div>

                      <div>
                        <span className="text-xs text-[#a6b0c3] block mb-1">Current Market Price</span>
                        <span className="font-display text-3xl font-bold text-[#f4eedf] tabular-nums">
                          {currentPreview.currentPrice}
                        </span>
                        <span className="text-xs text-[#a6b0c3] block mt-1">
                          {currentPreview.name}
                        </span>
                      </div>

                      <div>
                        <span className="text-xs text-[#a6b0c3] block mb-1">Blended WACC</span>
                        <span className="font-display text-3xl font-bold text-[#f4eedf] tabular-nums">
                          {currentPreview.wacc}
                        </span>
                        <span className="text-xs text-[#a6b0c3] block mt-1">
                          {currentPreview.waccNote}
                        </span>
                      </div>

                      <div>
                        <span className="text-xs text-[#a6b0c3] block mb-1">Monte Carlo (P5 – P95)</span>
                        <span className="font-display text-2xl font-bold text-[#8ab4f8] tabular-nums">
                          {currentPreview.mcRange}
                        </span>
                        <span className="text-xs text-[#a6b0c3] block mt-1">
                          10,000 Cholesky runs
                        </span>
                      </div>
                    </div>

                    <div className="py-6 space-y-4">
                      <div className="flex justify-between text-xs font-semibold text-[#a6b0c3]">
                        <span>Share Price vs. DCF Fair Value Scale</span>
                        <span className="text-[#f4eedf]">{currentPreview.upsideNote}</span>
                      </div>
                      <div className="relative h-4 rounded-full bg-[#141b26] border border-[#f4eedf]/12 overflow-hidden">
                        <div
                          className="absolute inset-y-0 left-0 bg-gradient-to-r from-[#34b38a]/35 to-[#34b38a]/15"
                          style={{ width: `${prevFairPct}%` }}
                        />
                        <div
                          className="absolute inset-y-0 right-0 bg-gradient-to-r from-[#e3b23c]/15 to-[#e07a5f]/35"
                          style={{ left: `${prevFairPct}%` }}
                        />
                        <div
                          className="absolute inset-y-0 w-1 bg-[#e3b23c]"
                          style={{ left: `${prevFairPct}%` }}
                        />
                        <div
                          className="absolute inset-y-0 w-1 bg-[#f4eedf]"
                          style={{ left: `${prevPricePct}%` }}
                        />
                      </div>
                      <div className="flex justify-between items-center pt-2">
                        <div className="flex gap-6 text-xs font-bold">
                          <span className="text-[#e3b23c]">● DCF Fair Value: {currentPreview.fairValue}</span>
                          <span className="text-[#f4eedf]">● Market Price: {currentPreview.currentPrice}</span>
                        </div>
                        <button
                          type="button"
                          onClick={() => handleQuickLaunch(currentPreview.ticker, currentPreview.market)}
                          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#e3b23c] hover:bg-[#ecc052] text-[#0f141c] font-bold text-xs shadow-lg transition cursor-pointer"
                        >
                          <span>Analyze {currentPreview.name} Live</span>
                          <FiArrowRight />
                        </button>
                      </div>
                    </div>
                  </div>
                </section>

              </div>
            </div>

            {/* Footer */}
            <footer className="border-t border-[#f4eedf]/10 py-10 px-4 sm:px-8 text-center text-xs text-[#a6b0c3]">
              <div className="max-w-4xl mx-auto space-y-2">
                <p className="text-[#f4eedf]/80 font-display font-bold">
                  ValuationLab — Institutional DCF &amp; Cholesky Monte Carlo Equity Research Platform
                </p>
                <p>
                  Audited financial statements via Yahoo Finance; live sovereign bond yields via FRED API &amp; RBI. For analytical research only.
                </p>
              </div>
            </footer>
          </div>
        )}

        {/* ===================================================================== */}
        {/* COMPANY VALUATION WORKSPACE (FULL-WIDTH, NUMBERS-FIRST DASHBOARD)     */}
        {/* ===================================================================== */}
        {analysisData && (
          <div className="flex-1 w-full max-w-[1680px] mx-auto px-4 sm:px-6 py-5 space-y-5">
            
            {/* Corporate Action Auto-Redirect Note (Clean notice) */}
            {analysisData?.company?.redirect_note && (
              <div className="px-4 py-3 rounded-xl bg-[#141b26] border border-[#f4eedf]/12 text-[#f4eedf] text-xs flex items-center gap-2.5">
                <span className="font-display font-bold uppercase tracking-wider text-[11px] text-[#e3b23c] shrink-0">
                  Corporate Action Sync:
                </span>
                <span>{analysisData.company.redirect_note}</span>
              </div>
            )}

            {/* 1. TOP HEADLINE BAR: COMPANY TITLE + 4 ON-FACE KPI CARDS */}
            <div className="space-y-4">
              {/* Company Title Row */}
              <div className="flex flex-wrap items-baseline justify-between gap-y-2 gap-x-4">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 min-w-0 flex-1">
                  <h1 className="font-display text-2xl sm:text-3xl font-bold text-[#f4eedf] tracking-tight break-words max-w-full leading-tight">
                    {formatCompanyName(analysisData.company?.name, analysisData.company?.ticker)}
                  </h1>
                  <span className="font-display font-bold text-base text-[#e3b23c] tracking-wide">
                    {analysisData.company?.ticker}
                  </span>
                  <span className="text-xs sm:text-sm text-[#a6b0c3] font-medium">
                    · {analysisData.company?.market === 'IN' ? '🇮🇳 NSE / BSE' : '🇺🇸 US Market'}
                    {analysisData.company?.sector ? ` · ${analysisData.company.sector}` : ''}
                  </span>
                  {analysisData.market_data?.is_illiquid && (
                    <span className="text-xs font-semibold text-[#e3b23c]">
                      · ⚠️ Thinly Traded
                    </span>
                  )}
                </div>

                <div className="text-xs text-[#a6b0c3] font-normal shrink-0">
                  Model Framework:{' '}
                  <strong className="text-[#f4eedf]">
                    {analysisData.company?.is_financial ? 'Tier-1 Regulatory Capital FCFE' : '5-Year Unlevered FCFF + Cholesky Monte Carlo'}
                  </strong>
                </div>
              </div>

              {/* 4 Straightforward On-Face Headline Metric Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
                
                {/* Card 1: DCF Intrinsic Fair Value (Primary Highlight - Clean & Uniform Border) */}
                <div className="bg-[#141b26] rounded-2xl p-5 shadow-lg border border-[#f4eedf]/10 relative">
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-xs font-bold uppercase tracking-wider text-[#e3b23c]">
                      DCF Intrinsic Fair Value
                    </span>
                    {analysisData.diagnostics?.tv_share_of_ev != null && (
                      <span className="text-[11px] font-semibold text-[#a6b0c3] tabular-nums">
                        TV {(analysisData.diagnostics.tv_share_of_ev * 100).toFixed(0)}% of EV
                      </span>
                    )}
                  </div>
                  <div className="font-display text-4xl sm:text-[42px] font-bold text-[#e3b23c] tabular-nums leading-tight my-1">
                    {wsSymbol}{wsFairValue.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <div className={`flex items-center text-xs font-bold tabular-nums ${
                    wsIsUndervalued ? 'text-[#34b38a]' : 'text-[#e07a5f]'
                  }`}>
                    {wsIsUndervalued ? <FiTrendingUp className="mr-1.5 text-sm shrink-0" /> : <FiTrendingDown className="mr-1.5 text-sm shrink-0" />}
                    <span>
                      {wsIsUndervalued ? '▲' : '▼'} {Math.abs(wsUpsidePct).toFixed(1)}% {wsIsUndervalued ? 'Upside (Undervalued)' : 'Downside (Above DCF)'}
                    </span>
                  </div>
                </div>

                {/* Card 2: Current Market Price */}
                <div className="bg-[#141b26] rounded-2xl p-5 shadow-lg border border-[#f4eedf]/10 flex flex-col justify-between">
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-xs font-bold uppercase tracking-wider text-[#a6b0c3]">
                      Current Market Price
                    </span>
                    <span className="text-[11px] font-semibold text-[#a6b0c3] bg-[#0d121a] px-2 py-0.5 rounded border border-[#f4eedf]/10">
                      {analysisData.company?.currency || 'USD'}
                    </span>
                  </div>
                  <div className="font-display text-3xl sm:text-4xl font-bold text-[#f4eedf] tabular-nums leading-tight my-1">
                    {wsSymbol}{wsCurrentPrice.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <div className="text-xs text-[#a6b0c3] flex items-center gap-2 tabular-nums">
                    <span>Beta: <strong className="text-[#f4eedf]">{analysisData.market_data?.beta ? analysisData.market_data.beta.toFixed(2) : '1.00'}</strong></span>
                    <span>•</span>
                    <span>WACC: <strong className="text-[#e3b23c]">{((analysisData.wacc?.wacc || 0) * 100).toFixed(1)}%</strong></span>
                  </div>
                </div>

                {/* Card 3: Monte Carlo Median */}
                <div className="bg-[#141b26] rounded-2xl p-5 shadow-lg border border-[#f4eedf]/10 flex flex-col justify-between">
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-xs font-bold uppercase tracking-wider text-[#a6b0c3]">
                      Monte Carlo Median
                    </span>
                    <span className="text-[11px] font-semibold text-[#8ab4f8] bg-[#5b8fd9]/10 px-2 py-0.5 rounded border border-[#5b8fd9]/25">
                      10,000 Runs
                    </span>
                  </div>
                  <div className="font-display text-3xl sm:text-4xl font-bold text-[#f4eedf] tabular-nums leading-tight my-1">
                    {wsSymbol}{wsMcMedian.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <div className="text-xs text-[#a6b0c3] tabular-nums">
                    90% CI: <strong className="text-[#f4eedf]">{wsSymbol}{wsP5.toLocaleString('en-US', { maximumFractionDigits: 0 })} – {wsSymbol}{wsP95.toLocaleString('en-US', { maximumFractionDigits: 0 })}</strong>
                  </div>
                </div>

                {/* Card 4: Verdict & Multiple Signal */}
                <div className="bg-[#141b26] rounded-2xl p-5 shadow-lg border border-[#f4eedf]/10 flex flex-col justify-between">
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-xs font-bold uppercase tracking-wider text-[#a6b0c3]">
                      Valuation Verdict
                    </span>
                    <span className="text-[11px] font-semibold text-[#a6b0c3] tabular-nums">
                      {analysisData.validation?.metric_used === 'ev_revenue' ? 'EV/Sales' : analysisData.company?.is_financial ? 'P/B' : 'EV/EBITDA'}:{' '}
                      <strong className="text-[#f4eedf]">
                        {analysisData.validation?.market_multiple ? `${analysisData.validation.market_multiple.toFixed(1)}x` : 'N/A'}
                      </strong>
                    </span>
                  </div>
                  <div className={`font-display ${
                    (analysisData.verdict?.verdict || '').length > 14 ? 'text-xl sm:text-2xl' : 'text-3xl sm:text-4xl'
                  } font-bold leading-tight my-1 tracking-tight ${
                    analysisData.verdict?.verdict?.includes('BUY')
                      ? 'text-[#34b38a]'
                      : analysisData.verdict?.verdict?.includes('SELL')
                      ? 'text-[#e07a5f]'
                      : 'text-[#e3b23c]'
                  }`}>
                    {analysisData.verdict?.verdict || 'N/A'}
                  </div>
                  <div className="text-xs text-[#a6b0c3] leading-snug" title={analysisData.verdict?.description}>
                    {analysisData.verdict?.description || 'Probability-weighted valuation signal'}
                  </div>
                </div>

              </div>
            </div>

            {/* 2. MAIN FULL-WIDTH 12-COLUMN GRID: LEFT CONTROLS + RIGHT ANALYSIS TABS */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
              
              {/* Left 3 Columns: Model Assumptions (with Restore Defaults) + Macro Config */}
              <div className="lg:col-span-3 space-y-4">
                <AssumptionSliders 
                  key={`sliders-${resetKey}-${analysisData.company?.ticker}`}
                  data={analysisData}
                  onOverride={(newOverrides) => {
                    setOverrides(newOverrides);
                  }}
                  onApply={(appliedOverrides) => {
                    setOverrides(appliedOverrides);
                    handleAnalyze(appliedOverrides, false);
                  }}
                  onReset={() => {
                    setOverrides({});
                    sessionStorage.removeItem('vl_overrides');
                    setResetKey(k => k + 1);
                    handleAnalyze({}, true);
                  }}
                  loading={loading}
                />

                <MacroDisplay data={analysisData} />
              </div>

              {/* Right 9 Columns: Tab Navigation + Active Data View */}
              <div className="lg:col-span-9 min-w-0 space-y-4">
                {/* Tab Bar */}
                <div className="bg-[#141b26] rounded-2xl p-1.5 border border-[#f4eedf]/10 flex space-x-1 overflow-x-auto shadow-lg">
                  {tabs.map((tab) => {
                    const isActive = activeTab === tab.id;
                    return (
                      <button
                        key={tab.id}
                        type="button"
                        onClick={() => setActiveTab(tab.id)}
                        className={`flex items-center gap-2 py-2.5 px-4 rounded-xl text-xs sm:text-sm font-bold transition-all whitespace-nowrap cursor-pointer ${
                          isActive
                            ? 'bg-[#e3b23c] text-[#0f141c] shadow-sm'
                            : 'text-[#a6b0c3] hover:text-[#f4eedf] hover:bg-[#0d121a]/60'
                        }`}
                      >
                        <span>{tab.icon}</span>
                        <span>{tab.label}</span>
                      </button>
                    );
                  })}
                </div>

                {/* Active Tab Content */}
                <div className="pb-10">
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
          </div>
        )}
      </main>

      <Analytics />
    </div>
  );
}
