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
  FiX,
  FiMail,
  FiMessageSquare
} from 'react-icons/fi';
import { FaLinkedin } from 'react-icons/fa';

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
import ContactAndFeedback from './components/ContactAndFeedback';
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
  const [showFeedbackModal, setShowFeedbackModal] = useState(false);

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
                onClick={() => setShowFeedbackModal(true)}
                className="hidden sm:inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-bold text-[#a6b0c3] hover:text-[#f4eedf] bg-[#141b26] hover:bg-[#1f2937] border border-[#f4eedf]/12 rounded-xl transition-colors cursor-pointer"
                title="Leave feedback or report an error"
              >
                <FiMessageSquare className="w-3.5 h-3.5 text-[#e3b23c]" />
                <span>Feedback</span>
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
              {/* 01. Linear Growth Fade & Operating Margin */}
              <div className="bg-[#0d121a] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-sm space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#f4eedf]/8 pb-2.5">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-bold text-[#e3b23c]">01 ·</span>
                    <h4 className="font-display font-bold text-base text-[#f4eedf]">Linear Growth Fade &amp; Operating Margin Convergence</h4>
                  </div>
                  <span className="font-mono text-xs text-[#e3b23c] font-medium">
                    FCFF = NOPAT + D&amp;A − CapEx − ΔNWC
                  </span>
                </div>
                <div className="space-y-2 text-xs sm:text-sm text-[#c5cedd]">
                  <div className="flex items-start gap-2.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#e3b23c] mt-2 shrink-0" />
                    <p><strong className="text-[#f4eedf] font-semibold">Growth Decay:</strong> Year-1 revenue growth steps down linearly over 5 years toward long-run nominal GDP growth, preventing perpetual runaway projections.</p>
                  </div>
                  <div className="flex items-start gap-2.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#e3b23c] mt-2 shrink-0" />
                    <p><strong className="text-[#f4eedf] font-semibold">Margin Normalization:</strong> Operating EBIT margin gradually converges toward proven sustainable historical margins rather than assuming cyclical peak profitability forever.</p>
                  </div>
                  <div className="flex items-start gap-2.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#e3b23c] mt-2 shrink-0" />
                    <p><strong className="text-[#f4eedf] font-semibold">Distributable Cash:</strong> Unlevered Free Cash Flow (FCFF) deducts effective corporate taxes, adds non-cash D&amp;A, and subtracts required CapEx and working capital reinvestment.</p>
                  </div>
                </div>
              </div>

              {/* 02. Dynamic Cost of Capital (WACC) */}
              <div className="bg-[#0d121a] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-sm space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#f4eedf]/8 pb-2.5">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-bold text-[#5b8fd9]">02 ·</span>
                    <h4 className="font-display font-bold text-base text-[#f4eedf]">Dynamic Cost of Capital (WACC, CAPM &amp; Mid-Year)</h4>
                  </div>
                  <span className="font-mono text-xs text-[#8ab4f8] font-medium">
                    Cost of Equity &amp; Mid-Year Discounting
                  </span>
                </div>
                <div className="space-y-2 text-xs sm:text-sm text-[#c5cedd]">
                  <div className="flex items-start gap-2.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#8ab4f8] mt-2 shrink-0" />
                    <p><strong className="text-[#f4eedf] font-semibold">Cost of Equity:</strong> Anchored directly to live 10-year sovereign bond yields (RBI 10Y G-Sec for India or US FRED 10Y Treasury), plus company beta scaled by the equity risk premium.</p>
                  </div>
                  <div className="flex items-start gap-2.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#8ab4f8] mt-2 shrink-0" />
                    <p><strong className="text-[#f4eedf] font-semibold">Synthetic Debt Cost:</strong> Prices borrowing cost using synthetic interest-coverage ratings (Operating Profit divided by Interest Expense), net of corporate tax shield deductions.</p>
                  </div>
                  <div className="flex items-start gap-2.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#8ab4f8] mt-2 shrink-0" />
                    <p><strong className="text-[#f4eedf] font-semibold">Mid-Year Discounting:</strong> Cash flows are discounted at fractional half-year points because businesses collect cash continuously throughout the fiscal year rather than on December 31.</p>
                  </div>
                </div>
              </div>

              {/* 03. Cholesky Decomposition & Monte Carlo */}
              <div className="bg-[#0d121a] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-sm space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#f4eedf]/8 pb-2.5">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-bold text-[#34b38a]">03 ·</span>
                    <h4 className="font-display font-bold text-base text-[#f4eedf]">Correlated Monte Carlo &amp; Heavy-Tailed Shocks</h4>
                  </div>
                  <span className="font-mono text-xs text-[#34b38a] font-medium">
                    10,000 Verified Simulations &nbsp;|&nbsp; 3× Oversampled
                  </span>
                </div>
                <div className="space-y-2 text-xs sm:text-sm text-[#c5cedd]">
                  <div className="flex items-start gap-2.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#34b38a] mt-2 shrink-0" />
                    <p><strong className="text-[#f4eedf] font-semibold">7-Variable Covariance Matrix:</strong> Links Revenue Growth, Margins, Risk-Free Rates, Beta, Equity Risk Premium, and Borrowing Costs so all economic variables co-move realistically together.</p>
                  </div>
                  <div className="flex items-start gap-2.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#34b38a] mt-2 shrink-0" />
                    <p><strong className="text-[#f4eedf] font-semibold">Heavy-Tailed Crisis Distributions:</strong> Replaces naive Gaussian bell curves with fat-tailed Student's t shocks, accurately stress-testing severe macro downturns and black swans.</p>
                  </div>
                  <div className="flex items-start gap-2.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#34b38a] mt-2 shrink-0" />
                    <p><strong className="text-[#f4eedf] font-semibold">Strict Economic Filters:</strong> Oversamples 30,000 raw trials and discards economically invalid worlds (such as discount rates lower than GDP growth or negative borrowing rates) to deliver 10,000 verified DCF distributions.</p>
                  </div>
                </div>
              </div>

              {/* 04. Financial Institution Auto-Switch */}
              <div className="bg-[#0d121a] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-sm space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#f4eedf]/8 pb-2.5">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-bold text-[#e07a5f]">04 ·</span>
                    <h4 className="font-display font-bold text-base text-[#f4eedf]">Bank &amp; Financial Institution Auto-Switch (FCFE &amp; Justified P/B)</h4>
                  </div>
                  <span className="font-mono text-xs text-[#e07a5f] font-medium">
                    Tier-1 Capital &nbsp;|&nbsp; Direct-to-Equity FCFE
                  </span>
                </div>
                <div className="space-y-2 text-xs sm:text-sm text-[#c5cedd]">
                  <div className="flex items-start gap-2.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#e07a5f] mt-2 shrink-0" />
                    <p><strong className="text-[#f4eedf] font-semibold">Operating Deposits:</strong> For Banks and NBFCs, customer deposits and borrowings are operational working capital rather than traditional corporate debt.</p>
                  </div>
                  <div className="flex items-start gap-2.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#e07a5f] mt-2 shrink-0" />
                    <p><strong className="text-[#f4eedf] font-semibold">Tier-1 Regulatory Model:</strong> The engine automatically switches to a 100%-equity Tier-1 capital model that values equity directly via Free Cash Flow to Equity (FCFE).</p>
                  </div>
                  <div className="flex items-start gap-2.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#e07a5f] mt-2 shrink-0" />
                    <p><strong className="text-[#f4eedf] font-semibold">Justified P/B Check:</strong> Terminal equity value is grounded in sustainable Return on Equity via <span className="text-[#f4eedf] font-mono">P/B = (ROE − g) / (Ke − g)</span>.</p>
                  </div>
                </div>
              </div>

              {/* 05. Model Validation & Guardrails */}
              <div className="bg-[#0d121a] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-sm space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#f4eedf]/8 pb-2.5">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-bold text-[#e3b23c]">05 ·</span>
                    <h4 className="font-display font-bold text-base text-[#f4eedf]">Model Validation, Multiples Cross-Check &amp; Distress Logic</h4>
                  </div>
                  <span className="font-mono text-xs text-[#e3b23c] font-medium">
                    EV/EBITDA &nbsp;|&nbsp; P/B &nbsp;|&nbsp; Distress Guardrails
                  </span>
                </div>
                <p className="text-[#c5cedd] text-xs sm:text-sm">
                  Every DCF is automatically cross-referenced against current market trading multiples to detect market mispricings and model divergence:
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 mt-2 text-xs">
                  <div className="bg-[#141b26] p-3 rounded-xl border border-[#34b38a]/20">
                    <div className="font-display font-bold text-[#34b38a] mb-1 flex items-center gap-1.5">
                      <span>✓ VERIFIED</span>
                      <span className="text-[10px] text-[#a6b0c3] font-normal">(&lt;50% gap)</span>
                    </div>
                    <p className="text-[#a6b0c3] leading-relaxed">
                      Tight alignment between DCF implied multiples and current market multiples, confirming reasonable baseline cash flow assumptions.
                    </p>
                  </div>
                  <div className="bg-[#141b26] p-3 rounded-xl border border-[#e3b23c]/20">
                    <div className="font-display font-bold text-[#e3b23c] mb-1 flex items-center gap-1.5">
                      <span>⚠️ WARNING</span>
                      <span className="text-[10px] text-[#a6b0c3] font-normal">(50%–80% gap)</span>
                    </div>
                    <p className="text-[#a6b0c3] leading-relaxed">
                      Moderate divergence or Terminal Value &gt;75% of EV. Indicates market prices in growth acceleration beyond historical averages.
                    </p>
                  </div>
                  <div className="bg-[#141b26] p-3 rounded-xl border border-[#e07a5f]/20">
                    <div className="font-display font-bold text-[#e07a5f] mb-1 flex items-center gap-1.5">
                      <span>⚠️ FLAGGED</span>
                      <span className="text-[10px] text-[#a6b0c3] font-normal">(&gt;80% gap)</span>
                    </div>
                    <p className="text-[#a6b0c3] leading-relaxed">
                      High disconnect or negative operating EBITDA, signaling the stock trades on speculative sentiment or aggressive turnaround expectations.
                    </p>
                  </div>
                  <div className="bg-[#141b26] p-3 rounded-xl border border-[#e07a5f]/40">
                    <div className="font-display font-bold text-[#e07a5f] mb-1 flex items-center gap-1.5">
                      <span>🚨 DISTRESSED</span>
                      <span className="text-[10px] text-[#a6b0c3] font-normal">(DCF Unreliable)</span>
                    </div>
                    <p className="text-[#a6b0c3] leading-relaxed">
                      Triggered when debt exceeds Enterprise Value (<span className="text-[#f4eedf]">Equity ≤ 0</span>), Year-5 FCF is negative, or &gt;20% of simulations wipe out equity.
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

      {/* Feedback & Contact Modal (Accessible from workspace & header anytime) */}
      {showFeedbackModal && (
        <div className="fixed inset-0 z-50 bg-[#080c12]/85 backdrop-blur-md flex items-center justify-center p-4 sm:p-6 overflow-y-auto">
          <div className="bg-[#141b26] border border-[#f4eedf]/20 rounded-3xl max-w-5xl w-full max-h-[92vh] flex flex-col shadow-2xl overflow-hidden my-auto">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[#f4eedf]/12 bg-[#0f1520]">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-[#141b26] border border-[#f4eedf]/12 flex items-center justify-center text-[#e3b23c]">
                  <FiMessageSquare className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="font-display text-base sm:text-lg font-bold text-[#f4eedf] tracking-tight">
                    ValuationLab Feedback &amp; Contact
                  </h3>
                  <p className="text-xs text-[#a6b0c3]">
                    Report errors, suggest features, or connect with Sarandeep directly
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowFeedbackModal(false)}
                className="p-2 text-[#a6b0c3] hover:text-[#f4eedf] hover:bg-[#1f2937] rounded-xl transition-colors cursor-pointer"
              >
                <FiX className="w-5 h-5" />
              </button>
            </div>
            
            <div className="p-6 sm:p-8 overflow-y-auto space-y-6">
              <ContactAndFeedback currentTicker={analysisData?.company?.ticker || ticker} />
            </div>

            <div className="px-6 py-3.5 border-t border-[#f4eedf]/12 bg-[#0f1520] flex justify-end">
              <button
                type="button"
                onClick={() => setShowFeedbackModal(false)}
                className="px-5 py-2 text-xs font-bold bg-[#e3b23c] hover:bg-[#ecc052] text-[#0f141c] rounded-xl transition cursor-pointer shadow-md"
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

              {/* Top-Center Floating Solid Pill Navbar (Extended Length, Institutional & Sleek) */}
              <div className="relative z-20 pt-6 sm:pt-8 px-4 flex justify-center w-full">
                <nav className="w-full max-w-4xl bg-[#121824]/92 border border-[#f4eedf]/15 rounded-full px-5 sm:px-8 py-2.5 sm:py-3 flex items-center justify-between gap-4 sm:gap-6 shadow-[0_12px_45px_rgba(0,0,0,0.65)] backdrop-blur-xl">
                  {/* Left Brand Unit */}
                  <div 
                    onClick={() => handleGoHome(true)}
                    className="flex items-center gap-2.5 cursor-pointer group select-none shrink-0"
                    title="ValuationLabs"
                  >
                    <div className="w-8 h-8 rounded-full bg-[#182232] border border-[#f4eedf]/15 group-hover:border-[#e3b23c]/50 flex items-center justify-center text-[#e3b23c] transition-all">
                      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M3 3v18h18" />
                        <path d="m19 9-5 5-4-4-3 3" />
                      </svg>
                    </div>
                    <span className="font-display text-sm sm:text-base font-bold tracking-tight text-[#f4eedf]">
                      Valuation<span className="text-[#e3b23c]">Labs</span>
                    </span>
                  </div>

                  {/* Centered Navigation Links with Generous Spacing */}
                  <div className="hidden sm:flex items-center gap-1 sm:gap-2 text-xs sm:text-sm font-medium text-[#c5cedd]">
                    <button
                      type="button"
                      onClick={() => scrollToSection('dcf-explainer')}
                      className="px-3.5 py-1.5 rounded-full hover:text-[#f4eedf] hover:bg-[#1a2334] transition cursor-pointer"
                    >
                      Methodology
                    </button>
                    <button
                      type="button"
                      onClick={() => scrollToSection('cholesky-section')}
                      className="px-3.5 py-1.5 rounded-full hover:text-[#f4eedf] hover:bg-[#1a2334] transition cursor-pointer"
                    >
                      Cholesky &amp; WACC
                    </button>
                    <button
                      type="button"
                      onClick={() => scrollToSection('portfolio-guide')}
                      className="px-3.5 py-1.5 rounded-full hover:text-[#f4eedf] hover:bg-[#1a2334] transition cursor-pointer"
                    >
                      Portfolio Guide
                    </button>
                    <button
                      type="button"
                      onClick={() => scrollToSection('live-showcase')}
                      className="px-3.5 py-1.5 rounded-full hover:text-[#f4eedf] hover:bg-[#1a2334] transition cursor-pointer"
                    >
                      Live Models
                    </button>
                    <button
                      type="button"
                      onClick={() => scrollToSection('contact-feedback')}
                      className="px-3.5 py-1.5 rounded-full hover:text-[#f4eedf] hover:bg-[#1a2334] transition cursor-pointer"
                    >
                      Feedback &amp; Contact
                    </button>
                  </div>

                  {/* Right Action: Methodology Guide Quick Access */}
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={() => setShowMethodology(true)}
                      className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-bold text-[#f4eedf] hover:text-[#e3b23c] bg-[#1a2332] hover:bg-[#222e42] border border-[#f4eedf]/15 rounded-full transition cursor-pointer shadow-sm"
                    >
                      <FiFileText className="w-3.5 h-3.5 text-[#e3b23c]" />
                      <span>Full Guide</span>
                    </button>
                  </div>
                </nav>
              </div>

              {/* Upper-Sky Headline: ValuationLabs prominently on top, Intrinsic Value typewriter line below */}
              <div className="relative z-20 max-w-4xl mx-auto text-center px-4 mt-7 sm:mt-11 mb-auto flex flex-col items-center">
                <div className="flex items-center justify-center gap-2 mb-3 sm:mb-3.5">
                  <span className="font-mono text-xs sm:text-sm font-bold tracking-[0.25em] uppercase text-[#f4eedf]">
                    Valuation<span className="text-[#e3b23c]">Labs</span>
                  </span>
                </div>
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
            {/* PLATFORM AIM & ACTIVE CAPABILITIES (NEW INTRODUCTORY SECTION)         */}
            {/* ===================================================================== */}
            {/* PLATFORM AIM & ACTIVE CAPABILITIES (EDITORIAL, OPEN & BULLETED)       */}
            {/* ===================================================================== */}
            <section id="platform-aim" className="w-full max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pt-16 pb-12">
              <div className="border-b border-[#f4eedf]/10 pb-8 mb-10">
                <span className="text-sm sm:text-base md:text-lg font-mono uppercase tracking-[0.22em] text-[#e3b23c] font-bold block mb-3">
                  Purpose &amp; Active Capabilities
                </span>
                <h2 className="font-display text-3xl sm:text-4xl lg:text-5xl font-bold text-[#f4eedf] tracking-tight">
                  Democratizing First-Principles Valuation
                </h2>
                <p className="text-base sm:text-lg text-[#c5cedd] mt-3 max-w-3xl leading-relaxed">
                  Why ValuationLabs exists, what we stand for, and the quantitative financial modeling engine ready in your browser today.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-10 lg:gap-14 items-start">
                {/* Left Column: Our Aim */}
                <div className="space-y-6 flex flex-col justify-between h-full">
                  <div>
                    <span className="text-sm sm:text-base md:text-lg font-mono uppercase tracking-widest text-[#e3b23c] font-bold block mb-2">
                      Our Aim
                    </span>
                    <h3 className="font-display text-2xl sm:text-3xl font-bold text-[#f4eedf] tracking-tight leading-snug mb-3 md:min-h-[4.5rem] flex items-start">
                      Grounding stock analysis in real cash flows, not market sentiment.
                    </h3>
                    <p className="text-base sm:text-lg text-[#d1d7e0] leading-relaxed mb-6 md:min-h-[5.5rem]">
                      Daily stock prices fluctuate on headlines, momentum, and short-term quarterly speculation. Our purpose is to cut through the noise and give every investor the institutional-grade quantitative tools to value companies from first principles.
                    </p>

                    <ul className="space-y-5 text-base sm:text-[16.5px] text-[#d1d7e0] leading-relaxed">
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#e3b23c] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#f4eedf] font-semibold">First-Principles Valuation:</strong> Grounding equity research strictly in real cash flows, operating earnings, and audited balance sheets rather than hype or momentum.
                        </p>
                      </li>
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#e3b23c] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#f4eedf] font-semibold">Institutional Rigor for Everyone:</strong> Automating the exact Damodaran-aligned cash flow frameworks and debt rating mechanics previously restricted to costly hedge-fund terminals.
                        </p>
                      </li>
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#e3b23c] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#f4eedf] font-semibold">Probabilistic Reality over Targets:</strong> Moving past fragile single price targets by computing full 10,000-scenario confidence distributions across the full bear-to-bull spectrum.
                        </p>
                      </li>
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#e3b23c] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#f4eedf] font-semibold">Complete Modeling Transparency:</strong> Open assumptions, zero black-box formulas, and audited financial line items you can inspect in your browser and export to Excel.
                        </p>
                      </li>
                    </ul>
                  </div>
                </div>

                {/* Right Column: What ValuationLabs Offers Currently */}
                <div className="space-y-6 flex flex-col justify-between h-full">
                  <div>
                    <span className="text-sm sm:text-base md:text-lg font-mono uppercase tracking-widest text-[#5b8fd9] font-bold block mb-2">
                      Active Capabilities
                    </span>
                    <h3 className="font-display text-2xl sm:text-3xl font-bold text-[#f4eedf] tracking-tight leading-snug mb-3 md:min-h-[4.5rem] flex items-start">
                      Institutional financial modeling pipelines ready in your browser.
                    </h3>
                    <p className="text-base sm:text-lg text-[#d1d7e0] leading-relaxed mb-6 md:min-h-[5.5rem]">
                      Production-ready quantitative valuation workflows executing instantly on live market data across NSE, BSE, and US Equities, backed by audited filings and live sovereign anchors.
                    </p>

                    <ul className="space-y-5 text-base sm:text-[16.5px] text-[#d1d7e0] leading-relaxed">
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#34b38a] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#f4eedf] font-semibold">Automated 5-Year DCF Engine:</strong> Extracts audited SEC and NSE filings to model linear growth decay and calculate true Free Cash Flow to Firm (FCFF).
                        </p>
                      </li>
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#5b8fd9] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#f4eedf] font-semibold">Dynamic Macro WACC:</strong> Anchors discount rates to live 10-Year sovereign bond yields from the RBI and US Federal Reserve, factoring in company beta and capital structure.
                        </p>
                      </li>
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#e3b23c] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#f4eedf] font-semibold">10,000-Run Monte Carlo:</strong> Uses correlated matrix decomposition with heavy-tailed market shock distributions to stress-test real-world economic risks.
                        </p>
                      </li>
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#e07a5f] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#f4eedf] font-semibold">Reverse-DCF &amp; Excel Export:</strong> Adjusts growth and margin sliders in real time to reveal implied market expectations, with instant one-click multi-tab Excel export.
                        </p>
                      </li>
                    </ul>
                  </div>
                </div>
              </div>
            </section>

            {/* ===================================================================== */}
            {/* METHODOLOGY GUIDE (OPEN EDITORIAL, PROPORTIONATE CHARTS)              */}
            {/* ===================================================================== */}
            <div className="w-full max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-24 space-y-16 sm:space-y-20">

              {/* CHAPTER 01: OPERATING MARGIN, GROWTH FADE & FREE CASH FLOW (FCFF) */}
              <section id="dcf-explainer" className="space-y-8">
                <div>
                  <span className="text-sm sm:text-base md:text-lg font-mono uppercase tracking-[0.22em] text-[#34b38a] block mb-3 font-bold">
                    01 · Cash Flow &amp; Operating Margin Architecture
                  </span>
                  <h2 className="font-display text-3xl sm:text-4xl lg:text-5xl font-bold text-[#f4eedf] tracking-tight mb-4">
                    From Revenue Growth to Distributable Free Cash Flow
                  </h2>
                  <p className="text-base sm:text-lg text-[#d1d7e0] leading-relaxed max-w-4xl">
                    Every day, the stock market quotes a <strong className="text-[#f4eedf] font-semibold">share price</strong> driven by sentiment and headlines. A <strong className="text-[#f4eedf] font-semibold">Discounted Cash Flow (DCF)</strong> model measures the <strong className="text-[#e3b23c] font-semibold">intrinsic value of the business itself</strong> based on the actual cash it produces after paying taxes and reinvesting in operations.
                  </p>
                </div>

                {/* Clean 3-Column Editorial Explanations (Perfect Horizontal Alignment) */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-8 py-2 items-start">
                  <div className="space-y-2.5">
                    <h3 className="font-display text-xl sm:text-2xl font-bold text-[#f4eedf] leading-snug md:min-h-[3.25rem] flex items-start">
                      Linear Growth Decay
                    </h3>
                    <p className="text-base text-[#d1d7e0] leading-relaxed">
                      Year-1 revenue growth steps down systematically each year toward the long-term nominal GDP growth rate of the economy. This prevents the model from assuming unrealistic perpetual compounding.
                    </p>
                  </div>

                  <div className="space-y-2.5">
                    <h3 className="font-display text-xl sm:text-2xl font-bold text-[#f4eedf] leading-snug md:min-h-[3.25rem] flex items-start">
                      Margin Normalization
                    </h3>
                    <p className="text-base text-[#d1d7e0] leading-relaxed">
                      Operating EBIT margins converge gradually toward sustainable historical industry averages rather than assuming temporary boom-cycle peak profitability lasts forever.
                    </p>
                  </div>

                  <div className="space-y-2.5">
                    <h3 className="font-display text-xl sm:text-2xl font-bold text-[#f4eedf] leading-snug md:min-h-[3.25rem] flex items-start">
                      Distributable Cash Flow
                    </h3>
                    <p className="text-base text-[#d1d7e0] leading-relaxed">
                      Deducts effective corporate income taxes, adds back non-cash depreciation and amortization, and subtracts required investments in physical CapEx and Working Capital.
                    </p>
                  </div>
                </div>

                {/* Exhibit: Clean Financial Model (Zero Glowing Boxes, Sleek Typography) */}
                <div className="bg-[#0c121d] rounded-2xl p-6 sm:p-9 border border-[#f4eedf]/10 space-y-6">
                  <div className="flex flex-wrap justify-between items-center gap-3 pb-5 border-b border-[#f4eedf]/10">
                    <span className="text-xs sm:text-sm font-mono uppercase tracking-wider text-[#f4eedf] font-bold">
                      5-Year Revenue Decay &amp; Distributable Cash Flow Waterfall
                    </span>
                    <span className="text-xs sm:text-sm font-mono text-[#8b9bb4]">
                      FCFF = NOPAT + D&amp;A − CapEx − ΔNWC
                    </span>
                  </div>

                  <svg viewBox="0 0 960 335" className="w-full h-auto select-none">
                    <defs>
                      <linearGradient id="decayAreaGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.16" />
                        <stop offset="70%" stopColor="#38bdf8" stopOpacity="0.03" />
                        <stop offset="100%" stopColor="#38bdf8" stopOpacity="0.0" />
                      </linearGradient>

                      <filter id="glowBlue" x="-30%" y="-30%" width="160%" height="160%">
                        <feGaussianBlur stdDeviation="3" result="blur" />
                        <feMerge>
                          <feMergeNode in="blur" />
                          <feMergeNode in="SourceGraphic" />
                        </feMerge>
                      </filter>

                      <filter id="glowGreen" x="-30%" y="-30%" width="160%" height="160%">
                        <feGaussianBlur stdDeviation="3" result="blur" />
                        <feMerge>
                          <feMergeNode in="blur" />
                          <feMergeNode in="SourceGraphic" />
                        </feMerge>
                      </filter>

                      {/* Subtle Bar Gradients */}
                      <linearGradient id="barRevGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#1e293b" stopOpacity="0.9" />
                        <stop offset="100%" stopColor="#0f172a" stopOpacity="0.95" />
                      </linearGradient>
                      <linearGradient id="barEbitGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#252422" stopOpacity="0.9" />
                        <stop offset="100%" stopColor="#131418" stopOpacity="0.95" />
                      </linearGradient>
                      <linearGradient id="barNopatGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#1c212c" stopOpacity="0.9" />
                        <stop offset="100%" stopColor="#0d1219" stopOpacity="0.95" />
                      </linearGradient>
                      <linearGradient id="barReinvestGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#231a1f" stopOpacity="0.85" />
                        <stop offset="100%" stopColor="#130f14" stopOpacity="0.95" />
                      </linearGradient>
                      <linearGradient id="barFcffGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#064e3b" stopOpacity="0.9" />
                        <stop offset="100%" stopColor="#022c22" stopOpacity="0.95" />
                      </linearGradient>

                      <style>
                        {`
                          @keyframes flowDashDecay {
                            to { stroke-dashoffset: -32; }
                          }
                          @keyframes flowDashSteps {
                            to { stroke-dashoffset: -16; }
                          }
                          @keyframes pulseGlowBar {
                            0%, 100% { stroke-opacity: 0.6; }
                            50% { stroke-opacity: 1; }
                          }
                          .flow-decay {
                            animation: flowDashDecay 2.4s linear infinite;
                          }
                          .flow-steps {
                            animation: flowDashSteps 1.2s linear infinite;
                          }
                          .pulse-bar {
                            animation: pulseGlowBar 2s ease-in-out infinite;
                          }
                        `}
                      </style>
                    </defs>

                    {/* LEFT EXHIBIT: 5-Year Revenue Growth Decay (With Live Motion) */}
                    <g>
                      <text x="35" y="30" fill="#f4eedf" fontSize="15" fontWeight="700" fontFamily="Space Grotesk, sans-serif">
                        A. Revenue Growth Linear Decay (Yr 1 → Yr 5)
                      </text>

                      {/* Subtle Background Guidelines */}
                      <line x1="50" y1="80" x2="430" y2="80" stroke="#f4eedf" strokeOpacity="0.06" strokeDasharray="3 3" />
                      <line x1="50" y1="140" x2="430" y2="140" stroke="#f4eedf" strokeOpacity="0.06" strokeDasharray="3 3" />
                      <line x1="50" y1="200" x2="430" y2="200" stroke="#f4eedf" strokeOpacity="0.06" strokeDasharray="3 3" />
                      <line x1="50" y1="245" x2="430" y2="245" stroke="#f4eedf" strokeOpacity="0.18" strokeWidth="1" />
                      <line x1="50" y1="55" x2="50" y2="245" stroke="#f4eedf" strokeOpacity="0.18" strokeWidth="1" />

                      {/* Y-Axis Value Labels */}
                      <text x="42" y="84" textAnchor="end" fill="#64748b" fontSize="10.5" fontFamily="monospace">20%</text>
                      <text x="42" y="144" textAnchor="end" fill="#64748b" fontSize="10.5" fontFamily="monospace">10%</text>
                      <text x="42" y="249" textAnchor="end" fill="#64748b" fontSize="10.5" fontFamily="monospace">0%</text>

                      {/* Terminal GDP Cap Line & Clean Unboxed Label */}
                      <line x1="50" y1="200" x2="430" y2="200" stroke="#e3b23c" strokeDasharray="4 4" strokeWidth="1.2" strokeOpacity="0.5" />
                      <text x="58" y="218" fill="#e3b23c" fontSize="11" fontWeight="600" fontFamily="Space Grotesk, sans-serif">
                        ── Terminal GDP Cap: 5.5%
                      </text>

                      {/* Smooth Bezier Shaded Area Under Curve */}
                      <path
                        fill="url(#decayAreaGrad)"
                        d="M 70 80 C 120 95, 130 105, 155 110 C 200 120, 215 135, 240 140 C 285 150, 300 165, 325 170 C 370 180, 385 195, 410 198 L 410 245 L 70 245 Z"
                      />

                      {/* Static Base Curve Line */}
                      <path
                        fill="none"
                        stroke="#0369a1"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        d="M 70 80 C 120 95, 130 105, 155 110 C 200 120, 215 135, 240 140 C 285 150, 300 165, 325 170 C 370 180, 385 195, 410 198"
                      />

                      {/* Live Moving Dashed Flow Down the Curve */}
                      <path
                        fill="none"
                        stroke="#38bdf8"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeDasharray="8 8"
                        className="flow-decay"
                        d="M 70 80 C 120 95, 130 105, 155 110 C 200 120, 215 135, 240 140 C 285 150, 300 165, 325 170 C 370 180, 385 195, 410 198"
                      />

                      {/* Traveling Beacon Moving Down Curve */}
                      <circle r="4.5" fill="#38bdf8" filter="url(#glowBlue)">
                        <animateMotion
                          path="M 70 80 C 120 95, 130 105, 155 110 C 200 120, 215 135, 240 140 C 285 150, 300 165, 325 170 C 370 180, 385 195, 410 198"
                          dur="3.2s"
                          repeatCount="indefinite"
                        />
                      </circle>
                      <circle r="9" fill="none" stroke="#38bdf8" strokeWidth="1.5">
                        <animateMotion
                          path="M 70 80 C 120 95, 130 105, 155 110 C 200 120, 215 135, 240 140 C 285 150, 300 165, 325 170 C 370 180, 385 195, 410 198"
                          dur="3.2s"
                          repeatCount="indefinite"
                        />
                        <animate attributeName="r" values="4;12;4" dur="1.6s" repeatCount="indefinite" />
                        <animate attributeName="opacity" values="0.8;0.1;0.8" dur="1.6s" repeatCount="indefinite" />
                      </circle>

                      {/* Nodes & Clean Values */}
                      {[
                        { x: 70, y: 80, yr: 'Year 1', rate: '16.0%' },
                        { x: 155, y: 110, yr: 'Year 2', rate: '13.4%' },
                        { x: 240, y: 140, yr: 'Year 3', rate: '10.8%' },
                        { x: 325, y: 170, yr: 'Year 4', rate: '8.1%' },
                        { x: 410, y: 198, yr: 'Year 5', rate: '5.5%' },
                      ].map((pt, idx) => (
                        <g key={idx}>
                          {/* Outer Subtle Ring */}
                          <circle cx={pt.x} cy={pt.y} r="6" fill="none" stroke="#38bdf8" strokeOpacity="0.4" strokeWidth="1.2" />
                          {/* Inner Dot */}
                          <circle cx={pt.x} cy={pt.y} r="3" fill="#38bdf8" />
                          
                          {/* Clean Unboxed Value Label */}
                          <text x={pt.x} y={pt.y - 12} textAnchor="middle" fill="#f1f5f9" fontSize="11.5" fontWeight="700" fontFamily="Space Grotesk, sans-serif">
                            {pt.rate}
                          </text>

                          {/* Year Label - Clean 2-Line Separation */}
                          <text x={pt.x} y="268" textAnchor="middle" fill="#cbd5e1" fontSize="11.5" fontWeight="600" fontFamily="Space Grotesk, sans-serif">
                            {pt.yr}
                          </text>
                          <text x={pt.x} y="284" textAnchor="middle" fill="#64748b" fontSize="10" fontFamily="monospace">
                            g = {pt.rate}
                          </text>
                        </g>
                      ))}
                    </g>

                    {/* Middle Divider */}
                    <line x1="462" y1="20" x2="462" y2="305" stroke="#f4eedf" strokeOpacity="0.1" strokeWidth="1" />

                    {/* RIGHT EXHIBIT: Free Cash Flow Step Waterfall (With Live Cash Journey Motion) */}
                    <g>
                      <text x="495" y="30" fill="#f4eedf" fontSize="15" fontWeight="700" fontFamily="Space Grotesk, sans-serif">
                        B. Operating Margin to Distributable Free Cash Flow
                      </text>

                      {/* Baseline */}
                      <line x1="495" y1="245" x2="935" y2="245" stroke="#f4eedf" strokeOpacity="0.18" strokeWidth="1" />

                      {/* 1. Revenue Bar */}
                      <rect x="505" y="75" width="64" height="170" rx="8" fill="url(#barRevGrad)" stroke="rgba(148, 163, 184, 0.35)" strokeWidth="1.2" />
                      <line x1="509" y1="76" x2="565" y2="76" stroke="#ffffff" strokeOpacity="0.35" strokeWidth="1.5" strokeLinecap="round" />
                      <text x="537" y="63" textAnchor="middle" fill="#cbd5e1" fontSize="13" fontWeight="700" fontFamily="Space Grotesk, sans-serif">100%</text>

                      {/* Flowing Step Connector Rev -> EBIT */}
                      <path d="M 569 150 L 595 150" stroke="#f4eedf" strokeDasharray="3 3" strokeOpacity="0.4" strokeWidth="1.5" className="flow-steps" />

                      {/* 2. EBIT Bar */}
                      <rect x="595" y="150" width="64" height="95" rx="8" fill="url(#barEbitGrad)" stroke="rgba(227, 178, 60, 0.45)" strokeWidth="1.2" />
                      <line x1="599" y1="151" x2="655" y2="151" stroke="rgba(227, 178, 60, 0.55)" strokeWidth="1.5" strokeLinecap="round" />
                      <text x="627" y="138" textAnchor="middle" fill="#fde68a" fontSize="13" fontWeight="700" fontFamily="Space Grotesk, sans-serif">24%</text>

                      {/* Flowing Step Connector EBIT -> NOPAT */}
                      <path d="M 659 170 L 685 170" stroke="#f4eedf" strokeDasharray="3 3" strokeOpacity="0.4" strokeWidth="1.5" className="flow-steps" />

                      {/* 3. NOPAT Bar */}
                      <rect x="685" y="170" width="64" height="75" rx="8" fill="url(#barNopatGrad)" stroke="rgba(148, 163, 184, 0.35)" strokeWidth="1.2" />
                      <line x1="689" y1="171" x2="745" y2="171" stroke="#ffffff" strokeOpacity="0.25" strokeWidth="1.5" strokeLinecap="round" />
                      <text x="717" y="158" textAnchor="middle" fill="#cbd5e1" fontSize="13" fontWeight="700" fontFamily="Space Grotesk, sans-serif">18%</text>

                      {/* Flowing Step Connector NOPAT -> Reinvest */}
                      <path d="M 749 190 L 775 190" stroke="#f4eedf" strokeDasharray="3 3" strokeOpacity="0.4" strokeWidth="1.5" className="flow-steps" />

                      {/* 4. Reinvestment Bar */}
                      <rect x="775" y="190" width="64" height="55" rx="8" fill="url(#barReinvestGrad)" stroke="rgba(224, 122, 95, 0.45)" strokeWidth="1.2" />
                      <line x1="779" y1="191" x2="835" y2="191" stroke="rgba(224, 122, 95, 0.5)" strokeWidth="1.5" strokeLinecap="round" />
                      <text x="807" y="178" textAnchor="middle" fill="#fca5a5" fontSize="13" fontWeight="700" fontFamily="Space Grotesk, sans-serif">−6%</text>

                      {/* Flowing Step Connector Reinvest -> FCFF */}
                      <path d="M 839 175 L 865 175" stroke="#34d399" strokeDasharray="3 3" strokeWidth="1.5" className="flow-steps" />

                      {/* 5. FCFF Bar */}
                      <rect x="865" y="175" width="68" height="70" rx="8" fill="url(#barFcffGrad)" stroke="#34d399" strokeWidth="1.5" className="pulse-bar" />
                      <line x1="869" y1="176" x2="929" y2="176" stroke="#6ee7b7" strokeOpacity="0.7" strokeWidth="2" strokeLinecap="round" />
                      <text x="899" y="162" textAnchor="middle" fill="#34d399" fontSize="13.5" fontWeight="800" fontFamily="Space Grotesk, sans-serif">12%</text>

                      {/* Traveling Cash Flow Particle showing journey from Revenue to FCFF cash */}
                      <g>
                        <circle r="4" fill="#34d399" filter="url(#glowGreen)">
                          <animateMotion
                            path="M 537 75 L 537 150 L 627 150 L 627 170 L 717 170 L 717 190 L 807 190 L 807 175 L 899 175 L 899 220"
                            dur="4.5s"
                            repeatCount="indefinite"
                          />
                        </circle>
                        <circle r="8" fill="none" stroke="#34d399" strokeWidth="1.2">
                          <animateMotion
                            path="M 537 75 L 537 150 L 627 150 L 627 170 L 717 170 L 717 190 L 807 190 L 807 175 L 899 175 L 899 220"
                            dur="4.5s"
                            repeatCount="indefinite"
                          />
                          <animate attributeName="opacity" values="0.8;0.1;0.8" dur="1.2s" repeatCount="indefinite" />
                          <animate attributeName="r" values="5;10;5" dur="1.2s" repeatCount="indefinite" />
                        </circle>
                      </g>

                      {/* X-Axis Labels - Two Distinct Lines with 40px+ Inter-Column Breathing Room (Zero Cramping) */}
                      {/* 1. Revenue */}
                      <text x="537" y="268" textAnchor="middle" fill="#cbd5e1" fontSize="11.5" fontWeight="600" fontFamily="Space Grotesk, sans-serif">Revenue</text>
                      <text x="537" y="284" textAnchor="middle" fill="#64748b" fontSize="10" fontFamily="monospace">100% Base</text>

                      {/* 2. Operating EBIT */}
                      <text x="627" y="268" textAnchor="middle" fill="#cbd5e1" fontSize="11.5" fontWeight="600" fontFamily="Space Grotesk, sans-serif">Operating</text>
                      <text x="627" y="284" textAnchor="middle" fill="#fde68a" fontSize="10" fontWeight="700" fontFamily="monospace">EBIT (24%)</text>

                      {/* 3. After-Tax NOPAT */}
                      <text x="717" y="268" textAnchor="middle" fill="#cbd5e1" fontSize="11.5" fontWeight="600" fontFamily="Space Grotesk, sans-serif">After-Tax</text>
                      <text x="717" y="284" textAnchor="middle" fill="#cbd5e1" fontSize="10" fontWeight="700" fontFamily="monospace">NOPAT (18%)</text>

                      {/* 4. Reinvestment */}
                      <text x="807" y="268" textAnchor="middle" fill="#cbd5e1" fontSize="11.5" fontWeight="600" fontFamily="Space Grotesk, sans-serif">Reinvest</text>
                      <text x="807" y="284" textAnchor="middle" fill="#fca5a5" fontSize="10" fontWeight="700" fontFamily="monospace">CapEx (−6%)</text>

                      {/* 5. FCFF Cash */}
                      <text x="899" y="268" textAnchor="middle" fill="#34d399" fontSize="12" fontWeight="700" fontFamily="Space Grotesk, sans-serif">FCFF Cash</text>
                      <text x="899" y="284" textAnchor="middle" fill="#34d399" fontSize="10" fontWeight="800" fontFamily="monospace">Distributable</text>
                    </g>
                  </svg>
                </div>
              </section>

              {/* CHAPTER 02: DISCOUNT RATE (WACC, CAPM & MID-YEAR DISCOUNTING) */}
              <section id="wacc-section" className="space-y-8">
                <div>
                  <span className="text-sm sm:text-base md:text-lg font-mono uppercase tracking-[0.22em] text-[#5b8fd9] block mb-3 font-bold">
                    02 · Time Value of Money &amp; Cost of Capital (WACC)
                  </span>
                  <h2 className="font-display text-3xl sm:text-4xl lg:text-5xl font-bold text-[#f4eedf] tracking-tight mb-4">
                    How the Discount Rate (WACC) Determines Present Value
                  </h2>
                  <p className="text-base sm:text-lg text-[#d1d7e0] leading-relaxed max-w-4xl">
                    ₹100 or $100 received five years from now is worth less than the same amount in your pocket today because of inflation and opportunity cost. The <strong className="text-[#f4eedf] font-semibold">Weighted Average Cost of Capital (WACC)</strong> is the annual hurdle rate used to discount future cash flows back to today&apos;s purchasing power.
                  </p>
                </div>

                {/* Clean 3-Column Editorial Explanations (Perfect Horizontal Alignment) */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-8 py-2 items-start">
                  <div className="space-y-2.5">
                    <h3 className="font-display text-xl sm:text-2xl font-bold text-[#f4eedf] leading-snug md:min-h-[3.25rem] flex items-start">
                      Cost of Equity (CAPM)
                    </h3>
                    <p className="text-base text-[#d1d7e0] leading-relaxed">
                      Anchored directly to live 10-Year sovereign bond yields (RBI 10Y G-Sec for Indian equities or US 10Y Treasury for US stocks), plus company beta multiplied by the equity risk premium.
                    </p>
                  </div>

                  <div className="space-y-2.5">
                    <h3 className="font-display text-xl sm:text-2xl font-bold text-[#f4eedf] leading-snug md:min-h-[3.25rem] flex items-start">
                      After-Tax Cost of Debt
                    </h3>
                    <p className="text-base text-[#d1d7e0] leading-relaxed">
                      Borrowing rates are priced using synthetic credit spreads based on interest coverage ratios (Operating Profit divided by Interest Expense), reduced by the corporate tax shield deduction.
                    </p>
                  </div>

                  <div className="space-y-2.5">
                    <h3 className="font-display text-xl sm:text-2xl font-bold text-[#f4eedf] leading-snug md:min-h-[3.25rem] flex items-start">
                      Mid-Year Discounting
                    </h3>
                    <p className="text-base text-[#d1d7e0] leading-relaxed">
                      Because companies earn cash continuously throughout the operating year rather than on December 31, cash flows are discounted at fractional half-year periods for mathematical accuracy.
                    </p>
                  </div>
                </div>

                {/* Exhibit: Clean Financial Model (Zero Glowing Boxes, Sleek Typography) */}
                <div className="bg-[#0c121d] rounded-2xl p-6 sm:p-9 border border-[#f4eedf]/10 space-y-6">
                  <div className="flex flex-wrap justify-between items-center gap-3 pb-5 border-b border-[#f4eedf]/10">
                    <span className="text-xs sm:text-sm font-mono uppercase tracking-wider text-[#f4eedf] font-bold">
                      Capital Structure Blending &amp; Mid-Year Time Discounting Exhibit
                    </span>
                    <span className="text-xs sm:text-sm font-mono text-[#8b9bb4]">
                      Present Value = Future Cash Flow / (1 + WACC)^(t − 0.5)
                    </span>
                  </div>

                  <svg viewBox="0 0 960 370" className="w-full h-auto select-none">
                    <defs>
                      {/* Frosted Glass Backplates */}
                      <linearGradient id="panelGlassGrad" x1="0" y1="0" x2="1" y2="1">
                        <stop offset="0%" stopColor="#1e293b" stopOpacity="0.4" />
                        <stop offset="50%" stopColor="#0f172a" stopOpacity="0.25" />
                        <stop offset="100%" stopColor="#0a0f18" stopOpacity="0.5" />
                      </linearGradient>

                      {/* Ke & Kd Frosted Card Gradients */}
                      <linearGradient id="keCardGrad" x1="0" y1="0" x2="1" y2="1">
                        <stop offset="0%" stopColor="#0284c7" stopOpacity="0.14" />
                        <stop offset="100%" stopColor="#0f172a" stopOpacity="0.65" />
                      </linearGradient>

                      <linearGradient id="kdCardGrad" x1="0" y1="0" x2="1" y2="1">
                        <stop offset="0%" stopColor="#d97706" stopOpacity="0.14" />
                        <stop offset="100%" stopColor="#0f172a" stopOpacity="0.65" />
                      </linearGradient>

                      <linearGradient id="waccHubGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#1e293b" stopOpacity="0.85" />
                        <stop offset="100%" stopColor="#090d16" stopOpacity="0.95" />
                      </linearGradient>

                      {/* Frosted Glass Pillar (Outer 100% Future Cash Envelope) */}
                      <linearGradient id="pillarGlassGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="rgba(255, 255, 255, 0.05)" />
                        <stop offset="50%" stopColor="rgba(255, 255, 255, 0.015)" />
                        <stop offset="100%" stopColor="rgba(255, 255, 255, 0.03)" />
                      </linearGradient>

                      {/* Luminous Liquid Emerald Glass (Present Value Today) */}
                      <linearGradient id="pvLiquidGlass" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#34d399" stopOpacity="0.6" />
                        <stop offset="35%" stopColor="#059669" stopOpacity="0.45" />
                        <stop offset="100%" stopColor="#022c22" stopOpacity="0.2" />
                      </linearGradient>

                      <filter id="glowAmber" x="-30%" y="-30%" width="160%" height="160%">
                        <feGaussianBlur stdDeviation="3.5" result="blur" />
                        <feMerge>
                          <feMergeNode in="blur" />
                          <feMergeNode in="SourceGraphic" />
                        </feMerge>
                      </filter>

                      <filter id="glowSky" x="-30%" y="-30%" width="160%" height="160%">
                        <feGaussianBlur stdDeviation="3.5" result="blur" />
                        <feMerge>
                          <feMergeNode in="blur" />
                          <feMergeNode in="SourceGraphic" />
                        </feMerge>
                      </filter>

                      <style>
                        {`
                          @keyframes flowDashWacc {
                            to { stroke-dashoffset: -24; }
                          }
                          @keyframes flowDashWaccFast {
                            to { stroke-dashoffset: -16; }
                          }
                          @keyframes flowDashCurve {
                            to { stroke-dashoffset: -20; }
                          }
                          @keyframes pulseWaccHub {
                            0%, 100% { stroke-opacity: 0.5; }
                            50% { stroke-opacity: 1; }
                          }
                          .flow-wacc {
                            animation: flowDashWacc 2s linear infinite;
                          }
                          .flow-wacc-fast {
                            animation: flowDashWaccFast 1.2s linear infinite;
                          }
                          .flow-curve {
                            animation: flowDashCurve 2.2s linear infinite;
                          }
                          .pulse-hub {
                            animation: pulseWaccHub 2.5s ease-in-out infinite;
                          }
                        `}
                      </style>
                    </defs>

                    {/* ========================================================= */}
                    {/* LEFT PANEL: Capital Structure Hurdle Rate Formulation     */}
                    {/* ========================================================= */}
                    <g>
                      <text x="25" y="28" fill="#f4eedf" fontSize="15" fontWeight="700" fontFamily="Space Grotesk, sans-serif">
                        A. Capital Structure Hurdle Rate Formulation
                      </text>

                      {/* Matching Glassmorphic Panel Backplate */}
                      <rect x="15" y="45" width="445" height="310" rx="16" fill="url(#panelGlassGrad)" stroke="rgba(255, 255, 255, 0.08)" strokeWidth="1" />
                      <line x1="30" y1="46" x2="445" y2="46" stroke="rgba(255, 255, 255, 0.15)" strokeWidth="1" strokeLinecap="round" />

                      {/* Card 1: Cost of Equity (Ke) - 75% Capital Weight (Spacious & Zero Text Leakage) */}
                      <rect x="26" y="62" width="256" height="118" rx="12" fill="url(#keCardGrad)" stroke="rgba(56, 189, 248, 0.3)" strokeWidth="1.2" />
                      <rect x="26" y="62" width="4" height="118" rx="2" fill="#38bdf8" />
                      <text x="42" y="85" fill="#38bdf8" fontSize="11" fontWeight="700" fontFamily="Space Grotesk, sans-serif">
                        COST OF EQUITY (Ke)
                      </text>
                      <text x="270" y="85" textAnchor="end" fill="#7dd3fc" fontSize="10.5" fontWeight="600" fontFamily="monospace">
                        75% Weight
                      </text>
                      <text x="42" y="120" fill="#f8fafc" fontSize="24" fontWeight="800" fontFamily="Space Grotesk, sans-serif">
                        13.4%
                      </text>
                      <text x="42" y="145" fill="#94a3b8" fontSize="11" fontFamily="Space Grotesk, sans-serif">
                        Rf 7.1% + (1.15 β × 5.5% ERP)
                      </text>
                      <text x="42" y="163" fill="#64748b" fontSize="10" fontFamily="Space Grotesk, sans-serif">
                        10Y Sovereign Yield + Equity Spread
                      </text>

                      {/* Card 2: After-Tax Cost of Debt (Kd) - 25% Capital Weight (Spacious & Zero Text Leakage) */}
                      <rect x="26" y="202" width="256" height="118" rx="12" fill="url(#kdCardGrad)" stroke="rgba(227, 178, 60, 0.3)" strokeWidth="1.2" />
                      <rect x="26" y="202" width="4" height="118" rx="2" fill="#e3b23c" />
                      <text x="42" y="225" fill="#e3b23c" fontSize="11" fontWeight="700" fontFamily="Space Grotesk, sans-serif">
                        AFTER-TAX DEBT (Kd)
                      </text>
                      <text x="270" y="225" textAnchor="end" fill="#fde68a" fontSize="10.5" fontWeight="600" fontFamily="monospace">
                        25% Weight
                      </text>
                      <text x="42" y="260" fill="#f8fafc" fontSize="24" fontWeight="800" fontFamily="Space Grotesk, sans-serif">
                        6.6%
                      </text>
                      <text x="42" y="285" fill="#94a3b8" fontSize="11" fontFamily="Space Grotesk, sans-serif">
                        8.8% Borrowing × (1 − 25% Tax)
                      </text>
                      <text x="42" y="303" fill="#64748b" fontSize="10" fontFamily="Space Grotesk, sans-serif">
                        Synthetic Spread + Corporate Shield
                      </text>

                      {/* Connecting Curves: Base Underlay */}
                      <path d="M 282 121 C 298 121, 298 178, 310 178" stroke="rgba(56, 189, 248, 0.25)" strokeWidth="2" fill="none" />
                      <path d="M 282 261 C 298 261, 298 192, 310 192" stroke="rgba(227, 178, 60, 0.25)" strokeWidth="2" fill="none" />

                      {/* Connecting Curves: Animated Flowing Dashes */}
                      <path d="M 282 121 C 298 121, 298 178, 310 178" stroke="#38bdf8" strokeWidth="2.5" strokeDasharray="6 6" className="flow-wacc" fill="none" />
                      <path d="M 282 261 C 298 261, 298 192, 310 192" stroke="#e3b23c" strokeWidth="2.5" strokeDasharray="6 6" className="flow-wacc" fill="none" />

                      {/* Traveling Particles from Ke & Kd into WACC Hub */}
                      <circle r="3.5" fill="#38bdf8" filter="url(#glowSky)">
                        <animateMotion
                          path="M 282 121 C 298 121, 298 178, 310 178"
                          dur="2.4s"
                          repeatCount="indefinite"
                        />
                      </circle>
                      <circle r="3.5" fill="#e3b23c" filter="url(#glowAmber)">
                        <animateMotion
                          path="M 282 261 C 298 261, 298 192, 310 192"
                          dur="2.4s"
                          repeatCount="indefinite"
                        />
                      </circle>

                      {/* Blended WACC Command Hub */}
                      <rect x="310" y="118" width="138" height="146" rx="14" fill="url(#waccHubGrad)" stroke="rgba(227, 178, 60, 0.75)" strokeWidth="1.5" className="pulse-hub" />
                      <line x1="320" y1="119" x2="438" y2="119" stroke="#fde68a" strokeOpacity="0.5" strokeWidth="1.5" strokeLinecap="round" />
                      <text x="379" y="142" textAnchor="middle" fill="#e3b23c" fontSize="10.5" fontWeight="800" fontFamily="monospace">
                        BLENDED WACC
                      </text>
                      <text x="379" y="178" textAnchor="middle" fill="#ffffff" fontSize="28" fontWeight="800" fontFamily="Space Grotesk, sans-serif">
                        11.7%
                      </text>
                      <text x="379" y="200" textAnchor="middle" fill="#fde68a" fontSize="11" fontWeight="700" fontFamily="Space Grotesk, sans-serif">
                        Annual Hurdle Rate
                      </text>
                      <text x="379" y="228" textAnchor="middle" fill="#94a3b8" fontSize="10" fontFamily="Space Grotesk, sans-serif">
                        (0.75 × Ke) + (0.25 × Kd)
                      </text>
                      <text x="379" y="246" textAnchor="middle" fill="#64748b" fontSize="9" fontFamily="Space Grotesk, sans-serif">
                        Capital Structure Blended
                      </text>

                      {/* Streaming Outflow Arrow into Discounting Exhibit */}
                      <path d="M 448 191 L 490 191" stroke="#e3b23c" strokeOpacity="0.85" strokeWidth="2" strokeDasharray="4 4" className="flow-wacc-fast" />
                      <circle r="3.5" fill="#e3b23c">
                        <animateMotion
                          path="M 448 191 L 490 191"
                          dur="1.2s"
                          repeatCount="indefinite"
                        />
                      </circle>
                    </g>

                    {/* Middle Divider */}
                    <line x1="475" y1="20" x2="475" y2="355" stroke="#f4eedf" strokeOpacity="0.08" strokeWidth="1" />

                    {/* ========================================================================= */}
                    {/* RIGHT PANEL: Present Value Discounting (True Liquid Glassmorphism)        */}
                    {/* ========================================================================= */}
                    <g>
                      <text x="495" y="28" fill="#f4eedf" fontSize="15" fontWeight="700" fontFamily="Space Grotesk, sans-serif">
                        B. Time Value Discounting: Present Value Decay
                      </text>

                      {/* Matching Glassmorphic Panel Backplate */}
                      <rect x="490" y="45" width="455" height="310" rx="16" fill="url(#panelGlassGrad)" stroke="rgba(255, 255, 255, 0.08)" strokeWidth="1" />
                      <line x1="505" y1="46" x2="930" y2="46" stroke="rgba(255, 255, 255, 0.15)" strokeWidth="1" strokeLinecap="round" />

                      {/* Clean Top Header Row (Zero Collision: Title on Left, Legend on Far Right) */}
                      <text x="510" y="70" fill="#94a3b8" fontSize="10.5" fontWeight="700" fontFamily="Space Grotesk, sans-serif" letterSpacing="0.05em">
                        NOMINAL: ₹100 FUTURE CASH BASE
                      </text>
                      <g transform="translate(725, 62)">
                        <rect x="0" y="0" width="8" height="8" rx="2" fill="#10b981" />
                        <text x="13" y="8" fill="#34d399" fontSize="10.5" fontWeight="600" fontFamily="Space Grotesk, sans-serif">Present Value</text>
                        <rect x="94" y="0" width="8" height="8" rx="2" fill="none" stroke="rgba(255, 255, 255, 0.4)" strokeDasharray="2 2" />
                        <text x="107" y="8" fill="#94a3b8" fontSize="10.5" fontWeight="600" fontFamily="Space Grotesk, sans-serif">Discount Loss</text>
                      </g>

                      {/* Header Divider Hairline */}
                      <line x1="505" y1="84" x2="930" y2="84" stroke="rgba(255, 255, 255, 0.08)" strokeWidth="1" />

                      {/* 100% Future Cash Nominal Benchmark Guideline (Label on Far-Right Margin - Zero Column Collision) */}
                      <line x1="515" y1="120" x2="925" y2="120" stroke="rgba(255, 255, 255, 0.12)" strokeDasharray="3 3" strokeWidth="1" />
                      <text x="928" y="123" fill="#64748b" fontSize="9.5" fontFamily="monospace">
                        100%
                      </text>

                      {/* Baseline */}
                      <line x1="515" y1="265" x2="925" y2="265" stroke="#f4eedf" strokeOpacity="0.15" strokeWidth="1" />

                      {/* 5 Frosted Glass Pillars (Liquid Emerald Present Value inside Frosted Glass Envelopes) */}
                      {[
                        { x: 545, pvTop: 130, lossPct: '−7%', pvAmount: '₹93', yr: 'Yr 1', t: 't = 0.5', ret: '93% Value' },
                        { x: 625, pvTop: 144, lossPct: '−18%', pvAmount: '₹82', yr: 'Yr 2', t: 't = 1.5', ret: '82% Value' },
                        { x: 705, pvTop: 158, lossPct: '−27%', pvAmount: '₹73', yr: 'Yr 3', t: 't = 2.5', ret: '73% Value' },
                        { x: 785, pvTop: 172, lossPct: '−36%', pvAmount: '₹64', yr: 'Yr 4', t: 't = 3.5', ret: '64% Value' },
                        { x: 865, pvTop: 183, lossPct: '−43%', pvAmount: '₹57', yr: 'Yr 5', t: 't = 4.5', ret: '57% Value' },
                      ].map((b, i) => (
                        <g key={i}>
                          {/* Floating Discount Haircut Pill (In Dedicated Space Between Header & Pillar - ZERO Overlap) */}
                          <rect
                            x={b.x - 18}
                            y={95}
                            width="36"
                            height="18"
                            rx="4"
                            fill="rgba(251, 191, 36, 0.12)"
                            stroke="rgba(251, 191, 36, 0.3)"
                            strokeWidth="0.8"
                          />
                          <text
                            x={b.x}
                            y={108}
                            textAnchor="middle"
                            fill="#fbbf24"
                            fontSize="10"
                            fontWeight="700"
                            fontFamily="Space Grotesk, sans-serif"
                          >
                            {b.lossPct}
                          </text>

                          {/* Outer Frosted Glass Pillar (100% Future Cash Container) */}
                          <rect
                            x={b.x - 23}
                            y={120}
                            width="46"
                            height={145}
                            rx="8"
                            fill="url(#pillarGlassGrad)"
                            stroke="rgba(255, 255, 255, 0.1)"
                            strokeWidth="1"
                          />

                          {/* Liquid Emerald Glass Fill (Present Value in Today's Pocket) */}
                          <rect
                            x={b.x - 22}
                            y={b.pvTop}
                            width="44"
                            height={265 - b.pvTop}
                            rx="7"
                            fill="url(#pvLiquidGlass)"
                            stroke="rgba(52, 211, 153, 0.7)"
                            strokeWidth="1.2"
                          />

                          {/* Luminous Specular Top Edge */}
                          <line
                            x1={b.x - 17}
                            y1={b.pvTop + 1}
                            x2={b.x + 17}
                            y2={b.pvTop + 1}
                            stroke="#a7f3d0"
                            strokeOpacity="0.9"
                            strokeWidth="1.5"
                            strokeLinecap="round"
                          />

                          {/* Currency Value in Today's Real Purchasing Power */}
                          <text
                            x={b.x}
                            y={b.pvTop + 24}
                            textAnchor="middle"
                            fill="#ffffff"
                            fontSize="14"
                            fontWeight="800"
                            fontFamily="Space Grotesk, sans-serif"
                          >
                            {b.pvAmount}
                          </text>

                          {/* Clean 3-Line X-Axis Labels (Generous Margins, Zero Cramping) */}
                          <text
                            x={b.x}
                            y="288"
                            textAnchor="middle"
                            fill="#f8fafc"
                            fontSize="12"
                            fontWeight="700"
                            fontFamily="Space Grotesk, sans-serif"
                          >
                            {b.yr}
                          </text>
                          <text
                            x={b.x}
                            y="306"
                            textAnchor="middle"
                            fill="#64748b"
                            fontSize="10"
                            fontWeight="600"
                            fontFamily="monospace"
                          >
                            {b.t}
                          </text>
                          <text
                            x={b.x}
                            y="324"
                            textAnchor="middle"
                            fill="#34d399"
                            fontSize="10.5"
                            fontWeight="700"
                            fontFamily="Space Grotesk, sans-serif"
                          >
                            {b.ret}
                          </text>
                        </g>
                      ))}

                      {/* Smooth Discount Factor Trajectory Curve (Flowing Cleanly Along Specular Tops) */}
                      <path
                        fill="none"
                        stroke="#38bdf8"
                        strokeWidth="2"
                        strokeDasharray="5 5"
                        className="flow-curve"
                        d="M 545 130 C 585 137, 585 144, 625 144 C 665 151, 665 158, 705 158 C 745 165, 745 172, 785 172 C 825 178, 825 183, 865 183"
                      />

                      {/* Traveling Cyan Discount Beacon */}
                      <circle r="3.5" fill="#38bdf8" filter="url(#glowSky)">
                        <animateMotion
                          path="M 545 130 C 585 137, 585 144, 625 144 C 665 151, 665 158, 705 158 C 745 165, 745 172, 785 172 C 825 178, 825 183, 865 183"
                          dur="3.2s"
                          repeatCount="indefinite"
                        />
                      </circle>
                    </g>
                  </svg>
                </div>
              </section>

              {/* CHAPTER 03: CHOLESKY DECOMPOSITION & FAT-TAILED MONTE CARLO */}
              <section id="cholesky-section" className="space-y-8">
                <div>
                  <span className="text-sm sm:text-base md:text-lg font-mono uppercase tracking-[0.22em] text-[#e3b23c] block mb-3 font-bold">
                    03 · Correlated Monte Carlo &amp; Stress Testing
                  </span>
                  <h2 className="font-display text-3xl sm:text-4xl lg:text-5xl font-bold text-[#f4eedf] tracking-tight mb-4">
                    Why We Model 10,000 Worlds Instead of One Target
                  </h2>
                  <p className="text-base sm:text-lg text-[#d1d7e0] leading-relaxed max-w-4xl">
                    In the real world, financial variables do not move independently. When revenue growth accelerates, operating leverage often expands EBIT margins at the same time. ValuationLabs uses <strong className="text-[#f4eedf] font-semibold">Cholesky Matrix Decomposition</strong> paired with <strong className="text-[#f4eedf] font-semibold">heavy-tailed distributions</strong> across 10,000 verified simulations.
                  </p>
                </div>

                {/* Clean 3-Column Editorial Explanations (Perfect Horizontal Alignment) */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-8 py-2 items-start">
                  <div className="space-y-2.5">
                    <h3 className="font-display text-xl sm:text-2xl font-bold text-[#f4eedf] leading-snug md:min-h-[3.25rem] flex items-start">
                      Covariance Modeling
                    </h3>
                    <p className="text-base text-[#d1d7e0] leading-relaxed">
                      Preserves real-world statistical relationships between Revenue Growth, Margins, Sovereign Yields, Beta, Equity Risk Premium, and Debt Costs based on empirical market co-movements.
                    </p>
                  </div>

                  <div className="space-y-2.5">
                    <h3 className="font-display text-xl sm:text-2xl font-bold text-[#f4eedf] leading-snug md:min-h-[3.25rem] flex items-start">
                      Fat-Tailed Crisis Risk
                    </h3>
                    <p className="text-base text-[#d1d7e0] leading-relaxed">
                      Replaces naive Gaussian bell curves with fat-tailed distributions to accurately capture sudden economic turbulence, credit freezes, and severe bear-market black swans.
                    </p>
                  </div>

                  <div className="space-y-2.5">
                    <h3 className="font-display text-xl sm:text-2xl font-bold text-[#f4eedf] leading-snug md:min-h-[3.25rem] flex items-start">
                      Economic Sanity Filter
                    </h3>
                    <p className="text-base text-[#d1d7e0] leading-relaxed">
                      Filters 30,000 candidate draws to discard impossible states (such as hurdle rates dropping below terminal GDP growth or negative borrowing costs), retaining 10,000 valid valuations.
                    </p>
                  </div>
                </div>

                {/* Exhibit: Clean Financial Model (Zero Glowing Boxes, Sleek Typography) */}
                <div className="bg-[#0c121d] rounded-2xl p-6 sm:p-9 border border-[#f4eedf]/10 space-y-6">
                  <div className="flex flex-wrap justify-between items-center gap-3 pb-5 border-b border-[#f4eedf]/10">
                    <span className="text-xs sm:text-sm font-mono uppercase tracking-[0.2em] text-[#f4eedf] font-bold">
                      Quantitative Simulation Architecture
                    </span>
                    <span className="text-xs sm:text-sm font-mono text-[#8b9bb4]">
                      30,000 Raw Draws ➔ 10,000 Economically Valid Worlds
                    </span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8 items-stretch">
                    {/* Step 1 */}
                    <div className="flex flex-col h-full justify-between space-y-4">
                      <div className="space-y-2.5">
                        <span className="font-mono text-xs font-bold text-[#e3b23c] uppercase tracking-wider block">
                          STEP 01
                        </span>
                        <h4 className="font-display text-lg sm:text-xl font-bold text-[#f4eedf] leading-snug min-h-[3.25rem] sm:min-h-[3.5rem] flex flex-col justify-start">
                          <span>Covariance Matrix</span>
                          <span className="text-xs sm:text-sm font-normal text-[#94a3b8] font-mono mt-0.5">7 Macro Drivers</span>
                        </h4>
                        <p className="text-sm sm:text-base text-[#d1d7e0] leading-relaxed">
                          Empirically models joint movements across revenue growth, operating margins, 10Y sovereign yields, company beta, equity risk premium, and corporate borrowing rates.
                        </p>
                      </div>
                      <div className="mt-auto pt-4 border-t border-[#f4eedf]/10 space-y-1">
                        <div className="flex items-center justify-between text-xs font-mono">
                          <span className="font-semibold text-[#e3b23c] flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-[#e3b23c]"></span>
                            Contagion Preserved
                          </span>
                          <span className="text-[#8b9bb4]">7 Drivers</span>
                        </div>
                        <div className="text-[11px] text-[#64748b] font-mono">
                          Empirical cross-asset matrix
                        </div>
                      </div>
                    </div>

                    {/* Step 2 */}
                    <div className="flex flex-col h-full justify-between space-y-4">
                      <div className="space-y-2.5">
                        <span className="font-mono text-xs font-bold text-[#5b8fd9] uppercase tracking-wider block">
                          STEP 02
                        </span>
                        <h4 className="font-display text-lg sm:text-xl font-bold text-[#f4eedf] leading-snug min-h-[3.25rem] sm:min-h-[3.5rem] flex flex-col justify-start">
                          <span>Cholesky Factorization</span>
                          <span className="text-xs sm:text-sm font-normal text-[#94a3b8] font-mono mt-0.5">Lower-Triangular L</span>
                        </h4>
                        <p className="text-sm sm:text-base text-[#d1d7e0] leading-relaxed">
                          Decomposes the covariance matrix into a lower-triangular form, converting independent shocks into correlated economic regimes with heavy-tailed downside risk.
                        </p>
                      </div>
                      <div className="mt-auto pt-4 border-t border-[#f4eedf]/10 space-y-1">
                        <div className="flex items-center justify-between text-xs font-mono">
                          <span className="font-semibold text-[#5b8fd9] flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-[#5b8fd9]"></span>
                            L · Lᵀ Transformation
                          </span>
                          <span className="text-[#8b9bb4]">Heavy Tails</span>
                        </div>
                        <div className="text-[11px] text-[#64748b] font-mono">
                          Multi-variable shock engine
                        </div>
                      </div>
                    </div>

                    {/* Step 3 */}
                    <div className="flex flex-col h-full justify-between space-y-4">
                      <div className="space-y-2.5">
                        <span className="font-mono text-xs font-bold text-[#e07a5f] uppercase tracking-wider block">
                          STEP 03
                        </span>
                        <h4 className="font-display text-lg sm:text-xl font-bold text-[#f4eedf] leading-snug min-h-[3.25rem] sm:min-h-[3.5rem] flex flex-col justify-start">
                          <span>Economic Guardrails</span>
                          <span className="text-xs sm:text-sm font-normal text-[#94a3b8] font-mono mt-0.5">Sanity Stress Filter</span>
                        </h4>
                        <p className="text-sm sm:text-base text-[#d1d7e0] leading-relaxed">
                          Filters 30,000 raw simulation paths to discard invalid states—such as hurdle rates dropping below long-term GDP growth or negative corporate borrowing spreads.
                        </p>
                      </div>
                      <div className="mt-auto pt-4 border-t border-[#f4eedf]/10 space-y-1">
                        <div className="flex items-center justify-between text-xs font-mono">
                          <span className="font-semibold text-[#e07a5f] flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-[#e07a5f]"></span>
                            Sanity Stress Filter
                          </span>
                          <span className="text-[#34b38a] font-bold">10K Valid</span>
                        </div>
                        <div className="text-[11px] text-[#64748b] font-mono">
                          20,000 invalid paths pruned
                        </div>
                      </div>
                    </div>

                    {/* Step 4 */}
                    <div className="flex flex-col h-full justify-between space-y-4">
                      <div className="space-y-2.5">
                        <span className="font-mono text-xs font-bold text-[#34b38a] uppercase tracking-wider block">
                          STEP 04
                        </span>
                        <h4 className="font-display text-lg sm:text-xl font-bold text-[#f4eedf] leading-snug min-h-[3.25rem] sm:min-h-[3.5rem] flex flex-col justify-start">
                          <span>Fair Value Spectrum</span>
                          <span className="text-xs sm:text-sm font-normal text-[#94a3b8] font-mono mt-0.5">90% Confidence Band</span>
                        </h4>
                        <p className="text-sm sm:text-base text-[#d1d7e0] leading-relaxed">
                          Constructs a full 90% confidence distribution across 10,000 valid paths, mapping intrinsic equity value from the 5th percentile bear to 95th percentile bull case.
                        </p>
                      </div>
                      <div className="mt-auto pt-4 border-t border-[#f4eedf]/10 space-y-1">
                        <div className="flex items-center justify-between text-xs font-mono">
                          <span className="font-semibold text-[#34b38a] flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-[#34b38a]"></span>
                            P5 ➔ P50 ➔ P95
                          </span>
                          <span className="text-[#34b38a] font-bold">90% Range</span>
                        </div>
                        <div className="text-[11px] text-[#64748b] font-mono">
                          Full probabilistic fair value
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </section>

              {/* CHAPTER 04: PORTFOLIO GUIDE (Clean 2-Column Editorial, Balanced Height & Zero Dead Space) */}
              <section id="portfolio-guide" className="space-y-8">
                <div>
                  <span className="text-sm sm:text-base md:text-lg font-mono uppercase tracking-[0.22em] text-[#e07a5f] block mb-3 font-bold">
                    04 · Practical Application &amp; Portfolio Construction
                  </span>
                  <h2 className="font-display text-3xl sm:text-4xl lg:text-5xl font-bold text-[#f4eedf] tracking-tight mb-4">
                    Four Rules for Applying DCF Valuations in Your Portfolio
                  </h2>
                  <p className="text-base sm:text-lg text-[#d1d7e0] leading-relaxed max-w-4xl">
                    Actionable institutional principles for applying DCF fair value estimates, multiple cross-checks, and probability distributions in your daily investing decisions.
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-10 lg:gap-14 items-start">
                  {/* Rule 01 */}
                  <div className="space-y-4">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm sm:text-base font-bold text-[#e3b23c]">01</span>
                      <span className="text-xs sm:text-sm font-mono text-[#e3b23c] uppercase tracking-wider font-semibold">
                        · Value &amp; Cyclical Strategy
                      </span>
                    </div>
                    <h3 className="font-display text-xl sm:text-2xl lg:text-[26px] font-bold text-[#f4eedf] leading-snug md:min-h-[4.25rem] flex items-start">
                      Demand a Margin of Safety on Cyclical &amp; Value Stocks
                    </h3>
                    <ul className="space-y-4 text-base sm:text-[16.5px] text-[#d1d7e0] leading-relaxed">
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#e3b23c] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#f4eedf] font-semibold">Entry Signal:</strong> Accumulate when today&apos;s market price trades below DCF Fair Value and sits near the lower half (25th to 50th percentile) of the Monte Carlo simulation distribution.
                        </p>
                      </li>
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#e3b23c] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#f4eedf] font-semibold">Target Discount:</strong> Require a 15% to 25% margin of safety before initiating a position to protect against ordinary or sub-par economic growth.
                        </p>
                      </li>
                    </ul>
                  </div>

                  {/* Rule 02 */}
                  <div className="space-y-4">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm sm:text-base font-bold text-[#5b8fd9]">02</span>
                      <span className="text-xs sm:text-sm font-mono text-[#5b8fd9] uppercase tracking-wider font-semibold">
                        · Compounders &amp; Moats
                      </span>
                    </div>
                    <h3 className="font-display text-xl sm:text-2xl lg:text-[26px] font-bold text-[#f4eedf] leading-snug md:min-h-[4.25rem] flex items-start">
                      Reverse-Engineer What the Market is Pricing In
                    </h3>
                    <ul className="space-y-4 text-base sm:text-[16.5px] text-[#d1d7e0] leading-relaxed">
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#5b8fd9] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#f4eedf] font-semibold">Reverse-DCF Technique:</strong> Use interactive model sliders to raise growth or margins until Fair Value matches today&apos;s share price, revealing implied market expectations.
                        </p>
                      </li>
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#5b8fd9] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#f4eedf] font-semibold">Sanity Question:</strong> Ask: <em>&quot;Can this franchise realistically deliver this implied growth rate for 5 consecutive years against competitors?&quot;</em>
                        </p>
                      </li>
                    </ul>
                  </div>

                  {/* Rule 03 */}
                  <div className="space-y-4">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm sm:text-base font-bold text-[#34b38a]">03</span>
                      <span className="text-xs sm:text-sm font-mono text-[#34b38a] uppercase tracking-wider font-semibold">
                        · Multiple Cross-Check
                      </span>
                    </div>
                    <h3 className="font-display text-xl sm:text-2xl lg:text-[26px] font-bold text-[#f4eedf] leading-snug md:min-h-[4.25rem] flex items-start">
                      Interpret Model Validation Badges at a Glance
                    </h3>
                    <ul className="space-y-4 text-base sm:text-[16.5px] text-[#d1d7e0] leading-relaxed">
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#34b38a] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#34b38a] font-semibold">Verified Badge:</strong> Less than 50% gap between DCF value and peer EV/EBITDA multiples indicates strong institutional model alignment.
                        </p>
                      </li>
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#e3b23c] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#e3b23c] font-semibold">Warning / Flagged:</strong> 50% to 80%+ multiple gap indicates the market is pricing in either massive speculative growth or negative operating earnings.
                        </p>
                      </li>
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#e07a5f] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#e07a5f] font-semibold">Distressed Flag:</strong> Excessive debt or greater than 20% wipeout probability means standard cash flow discounting is unreliable.
                        </p>
                      </li>
                    </ul>
                  </div>

                  {/* Rule 04: Perfectly Aligned 3-Point Counterpart to Rule 03 */}
                  <div className="space-y-4">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm sm:text-base font-bold text-[#e07a5f]">04</span>
                      <span className="text-xs sm:text-sm font-mono text-[#e07a5f] uppercase tracking-wider font-semibold">
                        · Risk-Adjusted Position Sizing
                      </span>
                    </div>
                    <h3 className="font-display text-xl sm:text-2xl lg:text-[26px] font-bold text-[#f4eedf] leading-snug md:min-h-[4.25rem] flex items-start">
                      Position Sizing: Bet Bigger on Certainty
                    </h3>
                    <ul className="space-y-4 text-base sm:text-[16.5px] text-[#d1d7e0] leading-relaxed">
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#34b38a] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#34b38a] font-semibold">Narrow Range (5%–8% Core Position):</strong> When the gap between bear-case and bull-case valuations is tight, cash flows are predictable. Low uncertainty justifies a high-conviction core portfolio allocation.
                        </p>
                      </li>
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#e3b23c] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#e3b23c] font-semibold">Wide Range (1%–3% Tactical Position):</strong> When the gap between bear and bull is wide (cyclicals or high-beta growth), macro swings dominate fair value. Keep bet sizes small to protect overall portfolio capital.
                        </p>
                      </li>
                      <li className="flex items-start gap-3">
                        <span className="w-2 h-2 rounded-full bg-[#5b8fd9] mt-2.5 shrink-0" />
                        <p>
                          <strong className="text-[#5b8fd9] font-semibold">Disciplined Rebalancing &amp; Trimming:</strong> When market prices surge past the 75th percentile valuation on momentum, systematically harvest gains back to target weighting rather than chasing multiple expansion.
                        </p>
                      </li>
                    </ul>
                  </div>
                </div>
              </section>

              {/* CHAPTER 05: LIVE ENGINE SHOWCASE (Full Width, Snug Top Spacing) */}
              <section id="live-showcase" className="space-y-8 pt-6 border-t border-[#f4eedf]/10">
                <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
                  <div>
                    <span className="text-sm sm:text-base md:text-lg font-mono uppercase tracking-[0.22em] text-[#e3b23c] block mb-3 font-bold">
                      05 · Verified Engine Benchmarks
                    </span>
                    <h2 className="font-display text-3xl sm:text-4xl lg:text-5xl font-bold text-[#f4eedf] tracking-tight">
                      Inspect Sample DCF Valuations Live
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
                          className={`text-xs font-bold px-4 py-2 rounded-xl transition cursor-pointer ${
                            isSelected
                              ? 'bg-[#e3b23c] text-[#0c1017]'
                              : 'bg-[#182334] text-[#a6b0c3] hover:text-[#f4eedf] border border-[#f4eedf]/10'
                          }`}
                        >
                          {item.tabLabel}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="bg-[#101722] rounded-2xl p-6 sm:p-8 border border-[#f4eedf]/12 shadow-xl space-y-6">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 pb-6 border-b border-[#f4eedf]/10">
                    <div>
                      <span className="text-xs text-[#a6b0c3] block mb-1">DCF Intrinsic Fair Value</span>
                      <span className={`font-display text-3xl sm:text-4xl font-bold tabular-nums ${
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
                      <span className="font-display text-3xl sm:text-4xl font-bold text-[#f4eedf] tabular-nums">
                        {currentPreview.currentPrice}
                      </span>
                      <span className="text-xs text-[#a6b0c3] block mt-1">
                        {currentPreview.name}
                      </span>
                    </div>

                    <div>
                      <span className="text-xs text-[#a6b0c3] block mb-1">Blended WACC</span>
                      <span className="font-display text-3xl sm:text-4xl font-bold text-[#f4eedf] tabular-nums">
                        {currentPreview.wacc}
                      </span>
                      <span className="text-xs text-[#a6b0c3] block mt-1">
                        {currentPreview.waccNote}
                      </span>
                    </div>

                    <div>
                      <span className="text-xs text-[#a6b0c3] block mb-1">Monte Carlo (P5 – P95)</span>
                      <span className="font-display text-2xl sm:text-3xl font-bold text-[#8ab4f8] tabular-nums">
                        {currentPreview.mcRange}
                      </span>
                      <span className="text-xs text-[#a6b0c3] block mt-1">
                        10,000 Cholesky runs
                      </span>
                    </div>
                  </div>

                  <div className="space-y-4">
                    <div className="flex justify-between text-xs font-semibold text-[#a6b0c3]">
                      <span>Share Price vs. DCF Fair Value Scale</span>
                      <span className="text-[#f4eedf]">{currentPreview.upsideNote}</span>
                    </div>
                    <div className="relative h-4 rounded-full bg-[#0d121a] border border-[#f4eedf]/12 overflow-hidden">
                      <div
                        className="absolute inset-y-0 left-0 bg-[#34b38a]/25"
                        style={{ width: `${prevFairPct}%` }}
                      />
                      <div
                        className="absolute inset-y-0 right-0 bg-[#e07a5f]/25"
                        style={{ left: `${prevFairPct}%` }}
                      />
                      <div
                        className="absolute inset-y-0 w-1.5 bg-[#e3b23c]"
                        style={{ left: `${prevFairPct}%` }}
                      />
                      <div
                        className="absolute inset-y-0 w-1.5 bg-[#f4eedf]"
                        style={{ left: `${prevPricePct}%` }}
                      />
                    </div>
                    <div className="flex flex-wrap justify-between items-center gap-4 pt-2">
                      <div className="flex gap-6 text-xs font-bold">
                        <span className="text-[#e3b23c]">● DCF Fair Value: {currentPreview.fairValue}</span>
                        <span className="text-[#f4eedf]">● Market Price: {currentPreview.currentPrice}</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleQuickLaunch(currentPreview.ticker, currentPreview.market)}
                        className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-[#e3b23c] hover:bg-[#ecc052] text-[#0f141c] font-bold text-xs shadow-md transition cursor-pointer"
                      >
                        <span>Analyze {currentPreview.name} Live</span>
                        <FiArrowRight />
                      </button>
                    </div>
                  </div>
                </div>
              </section>

              {/* CHAPTER 06: PLATFORM ROADMAP, CONTACT ME & COMMUNITY FEEDBACK */}
              <ContactAndFeedback currentTicker={ticker} />

            </div>

            {/* Footer */}
            <footer className="border-t border-[#f4eedf]/10 py-10 px-4 sm:px-8 text-center text-xs text-[#a6b0c3]">
              <div className="max-w-4xl mx-auto space-y-4">
                <div className="flex flex-wrap items-center justify-center gap-6 text-xs font-semibold text-[#f4eedf]/80">
                  <a
                    href="https://www.linkedin.com/in/sarandeepaneja/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 hover:text-[#e3b23c] transition"
                  >
                    <FaLinkedin className="text-[#0a66c2] text-sm" />
                    <span>Sarandeep Aneja on LinkedIn</span>
                  </a>
                  <span className="text-[#f4eedf]/20">·</span>
                  <a
                    href="mailto:sarandeepaneja@gmail.com"
                    className="flex items-center gap-1.5 hover:text-[#e3b23c] transition"
                  >
                    <FiMail className="text-[#e3b23c] text-sm" />
                    <span>sarandeepaneja@gmail.com</span>
                  </a>
                  <span className="text-[#f4eedf]/20">·</span>
                  <button
                    type="button"
                    onClick={() => scrollToSection('contact-feedback')}
                    className="hover:text-[#e3b23c] transition cursor-pointer"
                  >
                    Leave Feedback &amp; Report Errors
                  </button>
                </div>
                <p className="text-[#f4eedf]/80 font-display font-bold">
                  ValuationLab — Institutional DCF &amp; Cholesky Monte Carlo Equity Research Platform
                </p>
                <p>
                  Audited financial statements via Yahoo Finance; live sovereign bond yields via FRED API &amp; RBI. We continually update the platform with new valuation models and features.
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

            {/* Workspace Footer */}
            <footer className="border-t border-[#f4eedf]/10 pt-8 pb-12 px-4 sm:px-6 text-xs text-[#a6b0c3]">
              <div className="max-w-[1680px] mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
                <p className="text-[#f4eedf]/80 font-medium">
                  ValuationLab — {analysisData?.company?.name || analysisData?.company?.ticker} DCF Analysis &amp; Monte Carlo Modeling
                </p>
                <div className="flex flex-wrap items-center justify-center gap-5 text-xs font-semibold">
                  <a
                    href="https://www.linkedin.com/in/sarandeepaneja/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-[#a6b0c3] hover:text-[#e3b23c] transition"
                  >
                    <FaLinkedin className="text-[#0a66c2]" />
                    <span>Sarandeep Aneja on LinkedIn</span>
                  </a>
                  <a
                    href="mailto:sarandeepaneja@gmail.com"
                    className="flex items-center gap-1.5 text-[#a6b0c3] hover:text-[#e3b23c] transition"
                  >
                    <FiMail className="text-[#e3b23c]" />
                    <span>sarandeepaneja@gmail.com</span>
                  </a>
                  <button
                    type="button"
                    onClick={() => setShowFeedbackModal(true)}
                    className="text-[#e3b23c] hover:underline cursor-pointer font-bold flex items-center gap-1"
                  >
                    <FiMessageSquare className="text-xs" />
                    <span>Leave Feedback / Report Error</span>
                  </button>
                </div>
              </div>
            </footer>
          </div>
        )}
      </main>

      <Analytics />
    </div>
  );
}
