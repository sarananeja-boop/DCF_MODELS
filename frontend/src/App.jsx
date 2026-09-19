import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Toaster, toast } from 'react-hot-toast';
import { 
  FiTrendingUp, 
  FiBarChart2, 
  FiGrid, 
  FiActivity, 
  FiCpu, 
  FiRefreshCw, 
  FiMessageSquare,
  FiRotateCcw
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

export default function App() {
  const [analysisData, setAnalysisData] = useState(() => {
    const saved = sessionStorage.getItem('vl_analysisData');
    return saved ? JSON.parse(saved) : null;
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  
  const [activeTab, setActiveTab] = useState(() => sessionStorage.getItem('vl_activeTab') || 'overview');
  const [aiSummary, setAiSummary] = useState(() => sessionStorage.getItem('vl_aiSummary') || '');
  const [aiLoading, setAiLoading] = useState(false);
  
  const [ticker, setTicker] = useState(() => sessionStorage.getItem('vl_ticker') || '');
  const [market, setMarket] = useState(() => sessionStorage.getItem('vl_market') || 'auto');
  const [overrides, setOverrides] = useState(() => {
    const saved = sessionStorage.getItem('vl_overrides');
    return saved ? JSON.parse(saved) : {};
  });
  const [monteCarloIterations, setMonteCarloIterations] = useState(10000);
  const [resetKey, setResetKey] = useState(0);

  // Sync state to sessionStorage
  useEffect(() => {
    if (analysisData) sessionStorage.setItem('vl_analysisData', JSON.stringify(analysisData));
    else sessionStorage.removeItem('vl_analysisData');
  }, [analysisData]);

  useEffect(() => sessionStorage.setItem('vl_activeTab', activeTab), [activeTab]);
  useEffect(() => sessionStorage.setItem('vl_aiSummary', aiSummary), [aiSummary]);
  useEffect(() => sessionStorage.setItem('vl_ticker', ticker), [ticker]);
  useEffect(() => sessionStorage.setItem('vl_market', market), [market]);
  useEffect(() => sessionStorage.setItem('vl_overrides', JSON.stringify(overrides)), [overrides]);

  // Auto-refresh on page reload (Cmd+R)
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
      }).finally(() => {
        setLoading(false);
      });
    }
  }, []);

  const handleAnalyze = async (overrideParams = null, isNewSearch = false) => {
    if (!ticker) {
      toast.error('Please enter a ticker symbol');
      return;
    }
    setLoading(true);
    setError(null);
    
    // Check if analyzing a different company/market
    const isDifferentCompany = !analysisData || 
        analysisData.company.ticker.toUpperCase() !== ticker.toUpperCase() ||
        analysisData.company.market !== market;

    // Clear AI summary and reset overrides on new company search or explicit isNewSearch
    if (isDifferentCompany || isNewSearch) {
      setAiSummary('');
      setOverrides({});
      sessionStorage.removeItem('vl_overrides');
    }
    
    // Prevent stale overrides from infecting a new search
    let safeOverrides = {};
    if (!isDifferentCompany && !isNewSearch) {
      if (overrideParams && !overrideParams.nativeEvent && !(overrideParams instanceof Event)) {
        safeOverrides = overrideParams;
      } else {
        safeOverrides = overrides;
      }
    }

    try {
      const response = await axios.post('/api/analyze', {
        ticker,
        market,
        overrides: safeOverrides,
        monte_carlo_iterations: monteCarloIterations
      });
      
      setAnalysisData(response.data);
      toast.success(`Analysis for ${response.data.company.ticker} completed`);
    } catch (err) {
      const errorMsg = err.response?.data?.detail || err.response?.data?.error || err.message || 'An error occurred during analysis';
      setError(errorMsg);
      toast.error(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async () => {
    if (!analysisData) return;
    
    try {
      const response = await axios.post('/api/export/excel', { analysis_data: analysisData }, {
        responseType: 'blob'
      });
      
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      
      const dateStr = new Date().toISOString().split('T')[0];
      link.setAttribute('download', `${analysisData.company.ticker}_DCF_Valuation_${dateStr}.xlsx`);
      document.body.appendChild(link);
      link.click();
      
      link.parentNode.removeChild(link);
      window.URL.revokeObjectURL(url);
      toast.success('Excel file downloaded successfully');
    } catch (err) {
      toast.error('Failed to generate Excel file');
      console.error(err);
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

  const handleGoHome = () => {
    setAnalysisData(null);
    setError(null);
    setTicker('');
    setOverrides({});
    setAiSummary('');
    setActiveTab('overview');
  };

  const tabs = [
    { id: 'overview', label: 'Overview', icon: <FiActivity className="w-4 h-4" /> },
    { id: 'dcf', label: 'DCF Model', icon: <FiTrendingUp className="w-4 h-4" /> },
    { id: 'monte_carlo', label: 'Monte Carlo', icon: <FiCpu className="w-4 h-4" /> },
    { id: 'sensitivity', label: 'Sensitivity', icon: <FiGrid className="w-4 h-4" /> },
    { id: 'trends', label: 'Trends', icon: <FiBarChart2 className="w-4 h-4" /> }
  ];

  return (
    <div className="min-h-screen bg-zinc-950 text-slate-100 font-sans flex flex-col">
      <Toaster position="top-right" toastOptions={{ className: 'bg-zinc-900 text-white' }} />
      
      {/* Header */}
      <header className="sticky top-0 z-50 w-full border-b border-zinc-800/80 bg-zinc-950/90 backdrop-blur-md flex items-center px-6 py-4">
        <div 
          className="flex flex-col cursor-pointer hover:opacity-80 transition-opacity"
          onClick={handleGoHome}
        >
          <h1 className="font-bold tracking-tight text-xl text-zinc-100">
            ValuationLab
          </h1>
          <span className="text-xs text-zinc-500 mt-0.5">Automated DCF & Monte Carlo Valuation</span>
        </div>
      </header>
      {/* Main Content Area */}
      <main className="flex-1 relative overflow-hidden flex flex-col">
        
        {/* Loading Overlay */}
        {loading && (
          <div className="absolute inset-0 bg-zinc-950/80 backdrop-blur-sm z-50 flex flex-col items-center justify-center">
            <FiRefreshCw className="w-12 h-12 text-blue-500 animate-spin mb-4" />
            <h2 className="text-xl font-semibold mb-2">Analyzing {ticker || 'Company'}...</h2>
            <p className="text-slate-400">Fetching financials, calculating WACC, running Monte Carlo simulations</p>
          </div>
        )}

        {/* Error Banner */}
        {error && (
          <div className="bg-accent-red/20 border-l-4 border-accent-red text-red-100 p-4 mx-6 mt-6 flex justify-between items-center rounded shadow-md z-40">
            <div>
              <p className="font-bold">Analysis Failed</p>
              <p className="text-sm">{error}</p>
            </div>
            <button onClick={() => setError(null)} className="text-red-200 hover:text-white px-2">Dismiss</button>
          </div>
        )}

        {/* Landing State */}
        {!analysisData && !loading && !error && (
          <div className="flex-1 flex flex-col items-center justify-center p-8 overflow-y-auto relative">
            {/* Subtle background glow */}
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[400px] bg-blue-500/10 blur-[120px] rounded-full pointer-events-none"></div>
            
            <div className="max-w-4xl w-full text-center mb-16 relative z-50">
              <div className="mb-6 inline-flex items-center rounded-full border border-zinc-800 bg-zinc-900/50 px-3 py-1 text-sm font-medium text-zinc-300 backdrop-blur-sm">
                <span className="flex h-2 w-2 rounded-full bg-blue-500 mr-2"></span>
                ValuationLab
              </div>
              <h2 className="text-5xl md:text-6xl font-extrabold tracking-tight text-zinc-100 mb-6 leading-tight">
                Institutional-Grade <br/> Valuation Engine
              </h2>
              <p className="text-xl text-zinc-400 font-light max-w-2xl mx-auto leading-relaxed mb-10">
                Enter a ticker symbol below to instantly generate a comprehensive Discounted Cash Flow analysis, 
                stress-tested with Monte Carlo simulations and AI-driven insights.
              </p>
              
              <div className="max-w-3xl mx-auto w-full text-left">
                <TickerInput 
                  ticker={ticker}
                  setTicker={setTicker}
                  market={market}
                  setMarket={setMarket}
                  onAnalyze={handleAnalyze}
                  loading={loading}
                />
              </div>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 max-w-5xl w-full relative z-10">
              {[
                { title: 'DCF Analysis', desc: 'Detailed multi-stage discounted cash flow model with terminal value calculations.', icon: <FiTrendingUp className="w-5 h-5 text-zinc-100" /> },
                { title: 'Monte Carlo', desc: '10,000+ iteration simulations to map probability distributions of fair value.', icon: <FiCpu className="w-5 h-5 text-zinc-100" /> },
                { title: 'Sensitivity', desc: 'Two-way data tables modeling WACC against growth and margin assumptions.', icon: <FiGrid className="w-5 h-5 text-zinc-100" /> },
                { title: 'AI Commentary', desc: 'Automated synthesis of model outputs, highlighting key risks and valuation gaps.', icon: <FiMessageSquare className="w-5 h-5 text-zinc-100" /> }
              ].map((feature, i) => (
                <div key={i} className="bg-zinc-900/50 backdrop-blur-sm p-8 rounded-2xl border border-zinc-800/80 hover:bg-zinc-800/50 hover:border-zinc-700 transition-all duration-300 group">
                  <div className="mb-6 bg-zinc-800 w-12 h-12 rounded-xl flex items-center justify-center border border-zinc-700/50 shadow-sm group-hover:scale-110 transition-transform">
                    {feature.icon}
                  </div>
                  <h3 className="text-lg font-semibold mb-3 text-zinc-200">{feature.title}</h3>
                  <p className="text-sm text-zinc-400 leading-relaxed">{feature.desc}</p>
                </div>
              ))}
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
                    className="flex-1 bg-zinc-100 hover:bg-zinc-200 text-zinc-950 py-2 px-4 rounded font-medium flex items-center justify-center transition-colors"
                  >
                    <FiRefreshCw className="mr-2" /> Re-run Analysis
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

            {/* Right Main Panel */}
            <div className="flex-1 flex flex-col overflow-hidden bg-zinc-950">
              
              {/* Tab Navigation */}
              <div className="flex border-b border-zinc-800/80 overflow-x-auto bg-zinc-900/50">
                {tabs.map(tab => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex items-center px-6 py-4 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                      activeTab === tab.id 
                        ? 'border-zinc-100 text-zinc-100 bg-zinc-900/80' 
                        : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-zinc-900/40'
                    }`}
                  >
                    <span className="mr-2">{tab.icon}</span>
                    {tab.label}
                  </button>
                ))}
              </div>
              
              {/* Tab Content */}
              <div className="flex-1 overflow-y-auto p-6">
                <ErrorBoundary key={activeTab}>
                  {activeTab === 'overview' && (
                    <OverviewTab 
                      data={analysisData} 
                      aiSummary={aiSummary} 
                      aiLoading={aiLoading} 
                      onFetchAISummary={handleFetchAISummary} 
                    />
                  )}
                  {activeTab === 'dcf' && <DCFModelTab data={analysisData} />}
                  {activeTab === 'monte_carlo' && <MonteCarloTab data={analysisData} />}
                  {activeTab === 'sensitivity' && <SensitivityTab data={analysisData} />}
                  {activeTab === 'trends' && <TrendsTab data={analysisData} />}
                </ErrorBoundary>
              </div>
              
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
