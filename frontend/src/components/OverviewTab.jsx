import React from 'react';
import { FiCpu, FiTrendingUp, FiTrendingDown, FiCheckCircle, FiAlertTriangle } from 'react-icons/fi';
import AIReportRenderer from './AIReportRenderer';
import html2pdf from 'html2pdf.js';
import { FiDownload } from 'react-icons/fi';

// Helper functions
const formatCurrency = (value, symbol, compact) => {
  if (value == null) return 'N/A';
  if (!compact) {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: symbol === '₹' ? 'INR' : 'USD' }).format(value);
  }
  
  if (symbol === '₹') {
    if (value >= 1000000000000) return '₹' + (value / 1000000000000).toFixed(2) + 'L Cr';
    if (value >= 10000000) return '₹' + (value / 10000000).toFixed(2) + 'Cr';
    return '₹' + value.toLocaleString();
  } else {
    if (value >= 1000000000000) return symbol + (value / 1000000000000).toFixed(2) + 'T';
    if (value >= 1000000000) return symbol + (value / 1000000000).toFixed(2) + 'B';
    if (value >= 1000000) return symbol + (value / 1000000).toFixed(2) + 'M';
    return symbol + value.toLocaleString();
  }
};

const formatPercent = (value) => {
  if (value == null) return 'N/A';
  return (value * 100).toFixed(1) + '%';
};

const formatNumber = (value) => {
    if (value == null) return 'N/A';
    return value.toLocaleString('en-US', { maximumFractionDigits: 2 });
};

const OverviewTab = ({ data, aiSummary, aiLoading, onFetchAISummary }) => {
  if (!data) return <div className="p-8 text-center text-slate-400">No data available</div>;

  const { company, market_data, wacc: wacc_details, dcf_result, monte_carlo, validation, verdict } = data;
  const isFinancial = Boolean(company?.is_financial || data.diagnostics?.is_financial || dcf_result?.is_financial);
  const symbol = company?.currency === 'INR' ? '₹' : '$';

  const handleDownloadPDF = () => {
    const element = document.getElementById('ai-summary-content');
    if (!element) return;
    
    // Add temporary styling for PDF export to ensure dark background
    const originalBg = element.style.backgroundColor;
    const originalPadding = element.style.padding;
    element.style.backgroundColor = '#18181b'; // zinc-900
    element.style.padding = '2rem';
    
    const opt = {
      margin:       0,
      filename:     `${company.ticker}_Equity_Research.pdf`,
      image:        { type: 'jpeg', quality: 0.98 },
      html2canvas:  { scale: 2, backgroundColor: '#18181b' },
      jsPDF:        { unit: 'in', format: 'letter', orientation: 'portrait' }
    };
    
    html2pdf().set(opt).from(element).save().then(() => {
      // Restore styles
      element.style.backgroundColor = originalBg;
      element.style.padding = originalPadding;
    });
  };

  // Verdict colors
  let verdictColors = "bg-amber-500/20 text-amber-400 border-amber-500/30";
  if (verdict?.verdict?.includes('BUY')) {
    verdictColors = "bg-green-500/20 text-green-400 border-green-500/30";
  } else if (verdict?.verdict?.includes('SELL')) {
    verdictColors = "bg-red-500/20 text-red-400 border-red-500/30";
  }

  // Validation badge colors
  let validationColors = "bg-amber-500/20 text-amber-400";
  if (validation?.status === 'PASS') {
    validationColors = "bg-green-500/20 text-green-400";
  } else if (validation?.status === 'FAIL' || validation?.status === 'FLAG') {
    validationColors = "bg-red-500/20 text-red-400";
  }

  const impliedPrice = dcf_result?.implied_price || 0;
  const currentPrice = market_data?.current_price || 1;
  const dcfUpside = (impliedPrice / currentPrice) - 1.0;
  const isPositive = dcfUpside >= 0;

  return (
    <div className="space-y-4 text-slate-200">
      {/* 1. Top Stats Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Current Price */}
        <div className="bg-zinc-800/80 rounded-xl p-5 shadow-lg border border-zinc-800">
          <div className="text-sm text-slate-400 mb-1">Current Price</div>
          <div className="text-3xl font-bold text-white">
            {symbol}{formatNumber(market_data?.current_price)}
          </div>
        </div>

        {/* DCF Implied Value */}
        <div className="bg-zinc-800/80 rounded-xl p-5 shadow-lg border border-zinc-800">
          <div className="text-sm text-slate-400 mb-1">DCF Fair Value</div>
          <div className="text-3xl font-bold text-white">
            {symbol}{formatNumber(dcf_result?.implied_price)}
          </div>
          <div className={`mt-2 flex items-center text-sm ${isPositive ? 'text-green-400' : 'text-red-400'}`}>
            {isPositive ? <FiTrendingUp className="mr-1" /> : <FiTrendingDown className="mr-1" />}
            {isPositive ? '▲' : '▼'} {Math.abs(dcfUpside * 100).toFixed(1)}% {isPositive ? 'Upside' : 'Downside'}
          </div>
        </div>

        {/* Monte Carlo Median */}
        <div className="bg-zinc-800/80 rounded-xl p-5 shadow-lg border border-zinc-800">
          <div className="text-sm text-slate-400 mb-1">MC Median</div>
          <div className="text-3xl font-bold text-white">
            {symbol}{formatNumber(monte_carlo?.stats?.median)}
          </div>
          <div className="mt-2 text-xs text-slate-400">
            90% CI: {symbol}{formatNumber(monte_carlo?.stats?.p5)} – {symbol}{formatNumber(monte_carlo?.stats?.p95)}
          </div>
        </div>

        {/* Verdict Badge */}
        <div className="bg-zinc-800/80 rounded-xl p-5 shadow-lg border border-zinc-800 flex flex-col justify-center items-center text-center">
          <div className="text-sm text-slate-400 mb-2">Verdict</div>
          <div className={`px-4 py-2 rounded-lg font-bold text-lg border ${verdictColors}`}>
            {verdict?.verdict || 'N/A'}
          </div>
          {verdict?.description && (
            <div className="mt-2 text-xs text-slate-400 line-clamp-2">
              {verdict.description}
            </div>
          )}
        </div>
      </div>

      {/* 2. Company Info Card */}
      <div className="bg-zinc-800/80 rounded-xl p-5 shadow-lg border border-zinc-800">
        <h3 className="text-lg font-semibold text-white mb-4">Company Details</h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div>
            <div className="text-xs text-slate-400">Name</div>
            <div className="font-medium">{company?.name || 'N/A'}</div>
          </div>
          <div>
            <div className="text-xs text-slate-400">Ticker</div>
            <div className="font-medium">{company?.ticker || 'N/A'}</div>
          </div>
          <div>
            <div className="text-xs text-slate-400">Market</div>
            <div className="font-medium">{company?.market || 'N/A'}</div>
          </div>
          <div>
            <div className="text-xs text-slate-400">Shares Outstanding</div>
            <div className="font-medium">{formatNumber(market_data?.shares_outstanding)}</div>
          </div>
          <div>
            <div className="text-xs text-slate-400">Market Cap</div>
            <div className="font-medium">{formatCurrency((market_data?.shares_outstanding || 0) * (market_data?.current_price || 0), symbol, true)}</div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* 3. Cost of Capital / WACC Breakdown Card */}
        <div className="bg-zinc-800/80 rounded-xl p-5 shadow-lg border border-zinc-800">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-lg font-semibold text-white">
              {isFinancial ? 'Cost of Capital (FIG Framework)' : 'WACC Breakdown'}
            </h3>
            {isFinancial && (
              <span className="text-[11px] font-mono text-emerald-400 bg-emerald-950/40 border border-emerald-500/30 px-2 py-0.5 rounded">
                100% Equity Basis (FCFE)
              </span>
            )}
          </div>

          <div className="mb-4">
            <div className="flex h-3 rounded-full overflow-hidden bg-zinc-900">
              <div 
                className="bg-blue-500 h-full" 
                style={{ width: `${(wacc_details?.weight_equity || 0) * 100}%` }}
              ></div>
              <div 
                className="bg-amber-500 h-full" 
                style={{ width: `${(wacc_details?.weight_debt || 0) * 100}%` }}
              ></div>
            </div>
            <div className="flex justify-between text-xs mt-1 text-slate-400">
              <span>{isFinancial ? 'Equity (Capital Base) 100%' : `Equity ${formatPercent(wacc_details?.weight_equity)}`}</span>
              <span>{isFinancial ? 'Debt: Operational Inventory' : `Debt ${formatPercent(wacc_details?.weight_debt)}`}</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-y-4 gap-x-2">
            <div>
              <div className="text-xs text-slate-400">Cost of Equity (Ke)</div>
              <div className="font-medium text-emerald-400 font-mono">{formatPercent(wacc_details?.cost_of_equity)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-400">
                {isFinancial ? 'Valuation Basis' : 'Cost of Debt (after tax)'}
              </div>
              <div className="font-medium text-slate-200">
                {isFinancial ? 'Direct FCFE / DDM' : formatPercent(wacc_details?.cost_of_debt)}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-400">
                {isFinancial ? 'Discount Rate (Ke)' : 'WACC'}
              </div>
              <div className="font-medium text-lg text-accent-blue font-mono">{formatPercent(wacc_details?.wacc)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-400">
                {isFinancial ? 'Deposits & Borrowings' : 'Total Debt'}
              </div>
              <div className="font-medium text-slate-200">
                {isFinancial 
                  ? (wacc_details?.operational_debt ? formatCurrency(wacc_details.operational_debt, symbol, true) : 'Operational Inventory')
                  : formatCurrency(wacc_details?.total_debt, symbol, true)}
              </div>
            </div>
          </div>

          {isFinancial && (
            <div className="mt-4 pt-3 border-t border-zinc-800 text-[11px] text-slate-400 leading-relaxed">
              <span className="text-slate-300 font-medium">Why 100% Equity?</span> For banks and NBFCs, customer deposits and borrowings are operating raw materials (used to create loans), not capital structure debt. FCFE cash flows are net of interest, so discounting uses 100% Cost of Equity (Ke).
            </div>
          )}
        </div>

        {/* 4. Validation Card */}
        <div className="bg-zinc-800/80 rounded-xl p-5 shadow-lg border border-zinc-800">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-lg font-semibold text-white">
              {isFinancial ? 'Model Validation (P/B Framework)' : 'Model Validation'}
            </h3>
            <span className={`px-2 py-1 text-xs font-semibold rounded-md ${validationColors}`}>
              {validation?.status || 'UNKNOWN'}
            </span>
          </div>
          
          <div className="space-y-4">
            {isFinancial ? (
              <>
                <div className="flex justify-between items-center border-b border-zinc-800 pb-2">
                  <div className="text-sm text-slate-400">Market P/B Multiple</div>
                  <div className="font-medium font-mono">
                    {validation?.market_multiple !== null && validation?.market_multiple !== undefined 
                      ? `${formatNumber(validation.market_multiple)}x` 
                      : 'N/A'}
                  </div>
                </div>
                <div className="flex justify-between items-center border-b border-zinc-800 pb-2">
                  <div className="text-sm text-slate-400">Model Implied P/B</div>
                  <div className="font-medium font-mono">
                    {validation?.model_multiple !== null && validation?.model_multiple !== undefined 
                      ? `${formatNumber(validation.model_multiple)}x` 
                      : 'N/A'}
                  </div>
                </div>
                <div className="flex justify-between items-center border-b border-zinc-800 pb-2">
                  <div className="text-sm text-slate-400">Justified P/B (Residual ROE)</div>
                  <div className="font-medium font-mono">
                    {validation?.justified_pb !== null && validation?.justified_pb !== undefined 
                      ? `${formatNumber(validation.justified_pb)}x` 
                      : 'N/A'}
                  </div>
                </div>
                <div className="flex justify-between items-center border-b border-zinc-800 pb-2">
                  <div className="text-sm text-slate-400">Book Value Per Share (BVPS)</div>
                  <div className="font-medium font-mono">
                    {symbol}{formatNumber(validation?.bvps)}
                  </div>
                </div>
                <div className="flex justify-between items-center border-b border-zinc-800 pb-2">
                  <div className="text-sm text-slate-400">Valuation Gap</div>
                  <div className={`font-medium font-mono ${validation?.gap >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {validation?.gap >= 0 ? '+' : ''}{formatPercent(validation?.gap)}
                  </div>
                </div>
                <div className="text-[11px] text-slate-400 bg-zinc-900/60 p-2.5 rounded-lg border border-zinc-700/50 mt-2">
                  <span className="text-slate-300 font-medium">FIG Benchmarks:</span> Bank valuation cross-checks against Book Value (P/B) and Residual ROE, replacing industrial EV/EBITDA multiples.
                </div>
              </>
            ) : (
              <>
                <div className="flex justify-between items-center border-b border-zinc-800 pb-2">
                  <div className="text-sm text-slate-400">
                    {validation?.metric_used === 'ev_revenue' ? 'Market EV/Revenue' : 'Market EV/EBITDA'}
                  </div>
                  <div className="font-medium">
                    {validation?.market_multiple !== null && validation?.market_multiple !== undefined ? `${formatNumber(validation.market_multiple)}x` : 'N/A'}
                  </div>
                </div>
                <div className="flex justify-between items-center border-b border-zinc-800 pb-2">
                  <div className="text-sm text-slate-400">
                    {validation?.metric_used === 'ev_revenue' ? 'Model EV/Revenue' : 'Model EV/EBITDA'}
                  </div>
                  <div className="font-medium">
                    {validation?.model_multiple !== null && validation?.model_multiple !== undefined ? `${formatNumber(validation.model_multiple)}x` : 'N/A'}
                  </div>
                </div>
                <div className="flex justify-between items-center border-b border-zinc-800 pb-2">
                  <div className="text-sm text-slate-400">Gap</div>
                  <div className="font-medium">{formatPercent(validation?.multiple_gap_pct)}</div>
                </div>
                {validation?.metric_used === 'ev_revenue' && (
                  <div className="text-xs text-blue-400 bg-blue-500/10 p-3 rounded-lg flex items-start mt-2">
                    <span>Negative EBITDA detected. Falling back to EV/Revenue validation.</span>
                  </div>
                )}
                {validation?.warning && (
                  <div className="text-xs text-amber-400 bg-amber-500/10 p-3 rounded-lg flex items-start mt-2">
                    <FiAlertTriangle className="mr-2 mt-0.5 flex-shrink-0" />
                    <span>{validation.warning}</span>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* 5. AI Valuation Summary */}
      <div className="bg-zinc-800/80 rounded-xl p-6 shadow-lg border border-zinc-800 mt-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center space-x-2">
            <FiCpu className="text-accent-blue text-xl" />
            <h3 className="text-lg font-semibold text-white">AI Valuation Summary</h3>
          </div>
          {aiSummary && (
            <button 
              onClick={handleDownloadPDF}
              className="flex items-center space-x-2 text-xs bg-zinc-700 hover:bg-zinc-600 text-white px-3 py-1.5 rounded-md transition-colors"
            >
              <FiDownload /> <span>Download PDF</span>
            </button>
          )}
        </div>
        
        {aiSummary ? (
          <AIReportRenderer jsonString={aiSummary} />
        ) : (
          <div className="flex flex-col items-center justify-center py-6 text-center">
            {aiLoading ? (
              <div className="flex flex-col items-center space-y-3">
                <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-accent-blue"></div>
                <div className="text-slate-400 text-sm">Generating AI analysis...</div>
              </div>
            ) : (
              <div className="space-y-4">
                <p className="text-slate-400 text-sm">No AI summary generated yet. Use AI to analyze the DCF assumptions and output.</p>
                <button 
                  onClick={onFetchAISummary}
                  className="bg-zinc-100 hover:bg-zinc-200 text-zinc-950 font-medium rounded-lg px-6 py-2.5 transition-all shadow-sm"
                >
                  Generate AI Summary
                </button>
              </div>
            )}
          </div>
        )}
      </div>

    </div>
  );
};

export default OverviewTab;
