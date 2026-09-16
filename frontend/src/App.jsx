import React, { useState } from 'react';
import axios from 'axios';
import { Toaster, toast } from 'react-hot-toast';
import { 
  FiTrendingUp, 
  FiBarChart2, 
  FiGrid, 
  FiActivity, 
  FiCpu, 
  FiRefreshCw, 
  FiMessageSquare 
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

export default function App() {
  const [analysisData, setAnalysisData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  
  const [activeTab, setActiveTab] = useState('overview');
  const [aiSummary, setAiSummary] = useState('');
  const [aiLoading, setAiLoading] = useState(false);
  
  const [ticker, setTicker] = useState('');
  const [market, setMarket] = useState('auto');
  const [overrides, setOverrides] = useState({});
  const [monteCarloIterations, setMonteCarloIterations] = useState(10000);

  const handleAnalyze = async (overrideParams = null) => {
    if (!ticker) {
      toast.error('Please enter a ticker symbol');
      return;
    }
    
    setLoading(true);
    setError(null);
    setAiSummary(''); // Clear AI summary on new run
    
    try {
      const response = await axios.post('/api/analyze', {
        ticker,
        market,
        overrides: overrideParams || overrides,
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

  const tabs = [
    { id: 'overview', label: 'Overview', icon: <FiActivity className="w-4 h-4" /> },
    { id: 'dcf', label: 'DCF Model', icon: <FiTrendingUp className="w-4 h-4" /> },
    { id: 'monte_carlo', label: 'Monte Carlo', icon: <FiCpu className="w-4 h-4" /> },
    { id: 'sensitivity', label: 'Sensitivity', icon: <FiGrid className="w-4 h-4" /> },
    { id: 'trends', label: 'Trends', icon: <FiBarChart2 className="w-4 h-4" /> }
  ];

  return (
    <div className="min-h-screen bg-navy-900 text-slate-100 font-sans flex flex-col">
      <Toaster position="top-right" toastOptions={{ className: 'bg-navy-800 text-white' }} />
      
      {/* Header */}
      <header className="bg-gradient-to-r from-navy-800 to-navy-900 border-b border-navy-700 px-6 py-4 flex items-center justify-between z-10">
        <div className="flex flex-col">
          <h1 className="text-2xl font-bold bg-gradient-to-r from-blue-400 to-blue-600 bg-clip-text text-transparent">
            ValuationLab
          </h1>
          <span className="text-xs text-slate-400 mt-1">Automated DCF & Monte Carlo Valuation Platform</span>
        </div>
        
        <div className="w-1/3 min-w-[300px]">
          <TickerInput 
            ticker={ticker}
            setTicker={setTicker}
            market={market}
            setMarket={setMarket}
            onAnalyze={handleAnalyze}
            loading={loading}
          />
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 relative overflow-hidden flex flex-col">
        
        {/* Loading Overlay */}
        {loading && (
          <div className="absolute inset-0 bg-navy-900/80 backdrop-blur-sm z-50 flex flex-col items-center justify-center">
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
          <div className="flex-1 flex flex-col items-center justify-center p-8 overflow-y-auto">
            <div className="max-w-4xl w-full text-center mb-12">
              <h2 className="text-4xl font-bold mb-4">Professional-Grade Valuation, Automated.</h2>
              <p className="text-lg text-slate-400 max-w-2xl mx-auto">
                Enter a ticker symbol above to instantly generate a comprehensive Discounted Cash Flow analysis, 
                stress-tested with Monte Carlo simulations and AI-driven insights.
              </p>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 max-w-5xl w-full">
              {[
                { title: 'DCF Analysis', desc: 'Detailed multi-stage discounted cash flow model with terminal value calculations.', icon: <FiTrendingUp className="w-6 h-6 text-blue-400" /> },
                { title: 'Monte Carlo', desc: '10,000+ iteration simulations to map probability distributions of fair value.', icon: <FiCpu className="w-6 h-6 text-purple-400" /> },
                { title: 'Sensitivity', desc: 'Two-way data tables modeling WACC against growth and margin assumptions.', icon: <FiGrid className="w-6 h-6 text-green-400" /> },
                { title: 'AI Commentary', desc: 'Automated synthesis of model outputs, highlighting key risks and valuation gaps.', icon: <FiMessageSquare className="w-6 h-6 text-amber-400" /> }
              ].map((feature, i) => (
                <div key={i} className="bg-navy-800 p-6 rounded-lg border border-navy-700 hover:border-navy-600 transition-colors">
                  <div className="mb-4 bg-navy-900 w-12 h-12 rounded-full flex items-center justify-center border border-navy-700">
                    {feature.icon}
                  </div>
                  <h3 className="text-lg font-semibold mb-2">{feature.title}</h3>
                  <p className="text-sm text-slate-400">{feature.desc}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Results Layout */}
        {analysisData && (
          <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
            {/* Left Sidebar */}
            <div className="w-full md:w-80 flex-shrink-0 bg-navy-800 border-r border-navy-700 flex flex-col overflow-y-auto h-full p-4 space-y-6">
              
              <div className="flex space-x-2">
                <button 
                  onClick={handleAnalyze}
                  className="flex-1 bg-blue-600 hover:bg-blue-700 text-white py-2 px-4 rounded font-medium flex items-center justify-center transition-colors"
                >
                  <FiRefreshCw className="mr-2" /> Re-run Model
                </button>
                <ExcelDownloadButton data={analysisData} />
              </div>
              
              <div className="space-y-6">
                <AssumptionSliders 
                  data={analysisData}
                  onOverride={(newOverrides) => {
                    setOverrides(newOverrides);
                    handleAnalyze(newOverrides);
                  }}
                  loading={loading}
                />
                
                <MacroDisplay data={analysisData} />
              </div>
            </div>

            {/* Right Main Panel */}
            <div className="flex-1 flex flex-col overflow-hidden bg-navy-900">
              
              {/* Tab Navigation */}
              <div className="flex border-b border-navy-700 overflow-x-auto bg-navy-800/50">
                {tabs.map(tab => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex items-center px-6 py-4 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                      activeTab === tab.id 
                        ? 'border-blue-500 text-blue-400 bg-navy-800/80' 
                        : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-navy-800/40'
                    }`}
                  >
                    <span className="mr-2">{tab.icon}</span>
                    {tab.label}
                  </button>
                ))}
              </div>
              
              {/* Tab Content */}
              <div className="flex-1 overflow-y-auto p-6">
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
              </div>
              
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
