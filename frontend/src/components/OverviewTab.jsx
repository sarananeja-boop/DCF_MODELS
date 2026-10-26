import React from 'react';
import { FiCpu, FiCheckCircle, FiAlertTriangle, FiDownload } from 'react-icons/fi';
import AIReportRenderer from './AIReportRenderer';

const formatCurrency = (value, symbol, compact) => {
  if (value == null || isNaN(value)) return 'N/A';
  if (!compact) {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: symbol === '₹' ? 'INR' : 'USD' }).format(value);
  }
  
  const sign = value < 0 ? '-' : '';
  const abs = Math.abs(value);
  if (symbol === '₹') {
    if (abs >= 1000000000000) return sign + '₹' + (abs / 1000000000000).toFixed(2) + 'L Cr';
    if (abs >= 10000000) return sign + '₹' + (abs / 10000000).toFixed(2) + ' Cr';
    return sign + '₹' + abs.toLocaleString('en-IN', { maximumFractionDigits: 2 });
  } else {
    if (abs >= 1000000000000) return sign + symbol + (abs / 1000000000000).toFixed(2) + 'T';
    if (abs >= 1000000000) return sign + symbol + (abs / 1000000000).toFixed(2) + 'B';
    if (abs >= 1000000) return sign + symbol + (abs / 1000000).toFixed(2) + 'M';
    return sign + symbol + abs.toLocaleString('en-US', { maximumFractionDigits: 2 });
  }
};

const formatPercent = (value, digits = 1) => {
  if (value == null || isNaN(value)) return 'N/A';
  return (value * 100).toFixed(digits) + '%';
};

const formatNumber = (value, digits = 2) => {
  if (value == null || isNaN(value)) return 'N/A';
  return value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
};

const formatShares = (shares, market) => {
  if (!shares) return 'N/A';
  if (market === 'IN') {
    if (shares >= 1e7) return (shares / 1e7).toFixed(2) + ' Cr';
    return shares.toLocaleString('en-IN');
  }
  if (shares >= 1e9) return (shares / 1e9).toFixed(2) + 'B';
  if (shares >= 1e6) return (shares / 1e6).toFixed(2) + 'M';
  return shares.toLocaleString('en-US');
};

const OverviewTab = ({ data, aiSummary, aiLoading, onFetchAISummary }) => {
  if (!data) return <div className="p-8 text-center text-[#a6b0c3]">No data available</div>;

  const { company, market_data, wacc: wacc_details, dcf_result, monte_carlo, validation, diagnostics, historicals } = data;
  const isFinancial = Boolean(company?.is_financial || diagnostics?.is_financial || dcf_result?.is_financial);
  const symbol = company?.currency === 'INR' ? '₹' : '$';
  const market = company?.market || 'US';

  const handleDownloadPDF = async () => {
    const element = document.getElementById('ai-summary-content');
    if (!element) return;
    
    try {
      const html2pdfModule = await import('html2pdf.js');
      const html2pdf = html2pdfModule.default || html2pdfModule;
      
      const originalBg = element.style.backgroundColor;
      const originalPadding = element.style.padding;
      element.style.backgroundColor = '#141b26';
      element.style.padding = '2rem';
      
      const opt = {
        margin: 0,
        filename: `${company.ticker}_Equity_Research.pdf`,
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: { scale: 2, backgroundColor: '#141b26' },
        jsPDF: { unit: 'in', format: 'letter', orientation: 'portrait' }
      };
      
      await html2pdf().set(opt).from(element).save();
      
      element.style.backgroundColor = originalBg;
      element.style.padding = originalPadding;
    } catch (err) {
      console.error("Failed to export PDF:", err);
    }
  };

  const renderValidationBadge = () => {
    const status = validation?.status || 'UNKNOWN';
    if (status === 'PASS') {
      return (
        <span className="inline-flex items-center gap-1.5 text-xs font-bold text-[#34b38a]">
          <FiCheckCircle className="w-3.5 h-3.5 text-[#34b38a]" />
          <span>VERIFIED</span>
        </span>
      );
    }
    if (status === 'WARNING') {
      return (
        <span className="inline-flex items-center gap-1.5 text-xs font-bold text-[#e3b23c]">
          <FiAlertTriangle className="w-3.5 h-3.5 text-[#e3b23c]" />
          <span>WARNING</span>
        </span>
      );
    }
    if (status === 'FAIL' || status === 'FLAG') {
      return (
        <span className="inline-flex items-center gap-1.5 text-xs font-bold text-[#e07a5f]">
          <FiAlertTriangle className="w-3.5 h-3.5 text-[#e07a5f]" />
          <span>FLAGGED</span>
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 text-xs font-semibold text-[#a6b0c3]">
        <span>{status}</span>
      </span>
    );
  };

  const impliedPrice = dcf_result?.implied_price || 0;
  const currentPrice = market_data?.current_price || 1;
  const dcfUpside = (impliedPrice / currentPrice) - 1.0;
  const isPositive = dcfUpside >= 0;

  // Simply Wall St-style Fair Value Scale
  const p5 = monte_carlo?.stats?.p5 || impliedPrice * 0.65;
  const p25 = monte_carlo?.stats?.p25 || impliedPrice * 0.82;
  const p75 = monte_carlo?.stats?.p75 || impliedPrice * 1.18;
  const p95 = monte_carlo?.stats?.p95 || impliedPrice * 1.45;
  const exitImpliedPrice = validation?.exit_implied_price ?? diagnostics?.exit_implied_price;

  const scaleMax = Math.max(currentPrice, impliedPrice, p95, exitImpliedPrice || 0) * 1.16 || 100;
  const pricePosPct = Math.min(95, Math.max(5, (currentPrice / scaleMax) * 100));
  const fairPosPct = Math.min(95, Math.max(5, (impliedPrice / scaleMax) * 100));
  const p5PosPct = Math.min(92, Math.max(2, (p5 / scaleMax) * 100));
  const p95PosPct = Math.min(98, Math.max(p5PosPct + 4, (p95 / scaleMax) * 100));

  // PV of 5-yr vs Terminal Value composition
  const pv5Yr = dcf_result?.pv_ufcf || 0;
  const pvTv = dcf_result?.pv_terminal_value || 0;
  const totalEvPieces = Math.max(1, pv5Yr + pvTv);
  const pv5YrShare = Math.min(100, Math.max(0, (pv5Yr / totalEvPieces) * 100));
  const pvTvShare = 100 - pv5YrShare;

  // Latest historicals
  const latestRev = historicals?.revenue?.length ? historicals.revenue[historicals.revenue.length - 1] : validation?.trailing_revenue;
  const latestEbit = historicals?.ebit?.length ? historicals.ebit[historicals.ebit.length - 1] : null;
  const latestNi = historicals?.net_income?.length ? historicals.net_income[historicals.net_income.length - 1] : null;
  const latestBv = historicals?.book_value?.length ? historicals.book_value[historicals.book_value.length - 1] : null;
  const latestDiv = historicals?.dividends_paid?.length ? historicals.dividends_paid[historicals.dividends_paid.length - 1] : null;
  const totalCash = wacc_details?.total_cash ?? historicals?.cash_and_equivalents ?? 0;
  const totalDebt = wacc_details?.total_debt ?? 0;
  const mktCap = market_data?.market_cap || (market_data?.shares_outstanding || 0) * currentPrice;

  // Multiple bar scaling
  const mktMult = validation?.market_multiple || 0;
  const modMult = validation?.model_multiple || 0;
  const benchMult = validation?.benchmark_exit_multiple ?? diagnostics?.benchmark_exit_multiple ?? 10;
  const maxMult = Math.max(mktMult, modMult, benchMult, 1) * 1.15;

  return (
    <div className="space-y-4 text-[#f4eedf]">

      {/* =================================================================== */}
      {/* ROW 1: SIMPLY WALL ST PRICE VS FAIR VALUE BAR + EQUITY VALUE BRIDGE */}
      {/* =================================================================== */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4 items-stretch">
        
        {/* Left 7 Cols: Share Price vs Fair Value Visual Scale & Valuation Range Stats */}
        <div className="xl:col-span-7 bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
          <div>
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2.5">
                <h3 className="font-display font-bold text-base sm:text-lg text-[#f4eedf] tracking-tight">
                  Share Price vs. DCF Fair Value &amp; Probability Band
                </h3>
              </div>
              <div className="flex items-center gap-2">
                <span className={`text-sm font-display font-bold tabular-nums ${
                  isPositive ? 'text-[#34b38a]' : 'text-[#e07a5f]'
                }`}>
                  {isPositive
                    ? `▲ ${Math.abs(dcfUpside * 100).toFixed(1)}% Undervalued`
                    : `▼ ${Math.abs(dcfUpside * 100).toFixed(1)}% Overvalued`}
                </span>
              </div>
            </div>

            {/* Horizontal Bar Visualization (Simply Wall St style) */}
            <div className="relative pt-9 pb-9 px-2 my-2">
              {/* Fair Value Marker (Top Callout) */}
              <div
                className="absolute top-0 -translate-x-1/2 flex flex-col items-center transition-all duration-300 z-20"
                style={{ left: `${fairPosPct}%` }}
              >
                <div className="px-3 py-1 rounded-lg bg-[#e3b23c] text-[#0f141c] font-display text-xs font-bold whitespace-nowrap shadow-md tabular-nums">
                  DCF Fair Value: {symbol}{formatNumber(impliedPrice)}
                </div>
                <div className="w-0.5 h-3 bg-[#e3b23c]" />
              </div>

              {/* Track with Under/Overvalued Zones & Monte Carlo 90% Confidence Band */}
              <div className="relative h-6 rounded-xl bg-[#0d121a] border border-[#f4eedf]/15 overflow-hidden">
                <div
                  className="absolute inset-y-0 left-0 bg-gradient-to-r from-[#34b38a]/40 to-[#34b38a]/15"
                  style={{ width: `${fairPosPct}%` }}
                />
                <div
                  className="absolute inset-y-0 right-0 bg-gradient-to-r from-[#e3b23c]/15 via-[#e07a5f]/20 to-[#e07a5f]/40"
                  style={{ left: `${fairPosPct}%` }}
                />
                <div
                  className="absolute inset-y-1 rounded-lg bg-[#5b8fd9]/30 border border-[#5b8fd9]/60"
                  style={{ left: `${p5PosPct}%`, width: `${Math.max(2, p95PosPct - p5PosPct)}%` }}
                  title={`90% Monte Carlo Band: ${symbol}${formatNumber(p5)} – ${symbol}${formatNumber(p95)}`}
                />
                <div
                  className="absolute inset-y-0 w-0.5 bg-[#e3b23c] z-10"
                  style={{ left: `${fairPosPct}%` }}
                />
                <div
                  className="absolute inset-y-0 w-0.5 bg-[#f4eedf] z-10"
                  style={{ left: `${pricePosPct}%` }}
                />
              </div>

              {/* Current Price Marker (Bottom Callout) */}
              <div
                className="absolute bottom-0 -translate-x-1/2 flex flex-col items-center transition-all duration-300 z-20"
                style={{ left: `${pricePosPct}%` }}
              >
                <div className="w-0.5 h-3 bg-[#f4eedf]" />
                <div className="px-3 py-1 rounded-lg bg-[#f4eedf] text-[#0f141c] font-display text-xs font-bold whitespace-nowrap shadow-md tabular-nums">
                  Current Price: {symbol}{formatNumber(currentPrice)}
                </div>
              </div>
            </div>

            {/* Middle Insight Strip (Eliminates Empty Space with Rich Valuation Insights) */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 my-3 py-3 border-t border-b border-[#f4eedf]/10">
              <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/8">
                <div className="text-[10px] uppercase font-bold tracking-wider text-[#a6b0c3]">
                  {isPositive ? 'Margin of Safety' : 'Valuation Premium'}
                </div>
                <div className={`font-display text-base font-bold tabular-nums mt-0.5 ${isPositive ? 'text-[#34b38a]' : 'text-[#e07a5f]'}`}>
                  {isPositive ? '+' : '-'}{symbol}{formatNumber(Math.abs(impliedPrice - currentPrice))} ({Math.abs(dcfUpside * 100).toFixed(1)}%)
                </div>
                <div className="text-[10px] text-[#a6b0c3] mt-0.5">
                  {isPositive ? 'Discount below DCF fair value' : 'Premium above DCF fair value'}
                </div>
              </div>

              <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/8">
                <div className="text-[10px] uppercase font-bold tracking-wider text-[#a6b0c3]">
                  Monte Carlo Upside Odds
                </div>
                <div className="font-display text-base font-bold tabular-nums text-[#8ab4f8] mt-0.5">
                  {Array.isArray(monte_carlo?.simulated_prices) && monte_carlo.simulated_prices.length > 0
                    ? `${((monte_carlo.simulated_prices.filter(p => p > currentPrice).length / monte_carlo.simulated_prices.length) * 100).toFixed(1)}%`
                    : currentPrice > p95
                    ? '< 5.0%'
                    : currentPrice > (monte_carlo?.stats?.median || impliedPrice)
                    ? '35–45%'
                    : '> 75.0%'}
                </div>
                <div className="text-[10px] text-[#a6b0c3] mt-0.5">
                  Probability of outcome &gt; current market price
                </div>
              </div>

              <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/8">
                <div className="text-[10px] uppercase font-bold tracking-wider text-[#a6b0c3]">
                  Interquartile Band (P25–P75)
                </div>
                <div className="font-display text-base font-bold tabular-nums text-[#f4eedf] mt-0.5">
                  {symbol}{formatNumber(p25)} – {symbol}{formatNumber(p75)}
                </div>
                <div className="text-[10px] text-[#a6b0c3] mt-0.5">
                  Middle 50% probability corridor
                </div>
              </div>
            </div>
          </div>

          {/* 6-Metric Valuation Range Strip (All Key Price Benchmarks On-Face, Clean & Uniform) */}
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 pt-2">
            <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/10 text-center">
              <div className="text-[10px] uppercase tracking-wider text-[#e3b23c] font-bold">DCF Value</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#f4eedf] tabular-nums mt-1">
                {symbol}{formatNumber(impliedPrice)}
              </div>
            </div>
            <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/10 text-center">
              <div className="text-[10px] uppercase tracking-wider text-[#a6b0c3] font-semibold">Exit Mult.</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#f4eedf] tabular-nums mt-1">
                {exitImpliedPrice ? `${symbol}${formatNumber(exitImpliedPrice)}` : 'N/A'}
              </div>
            </div>
            <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/10 text-center">
              <div className="text-[10px] uppercase tracking-wider text-[#a6b0c3] font-semibold">MC P5 (Bear)</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#e07a5f] tabular-nums mt-1">
                {symbol}{formatNumber(p5)}
              </div>
            </div>
            <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/10 text-center">
              <div className="text-[10px] uppercase tracking-wider text-[#a6b0c3] font-semibold">MC P25</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#f4eedf] tabular-nums mt-1">
                {symbol}{formatNumber(p25)}
              </div>
            </div>
            <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/10 text-center">
              <div className="text-[10px] uppercase tracking-wider text-[#8ab4f8] font-bold">MC Median</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#f4eedf] tabular-nums mt-1">
                {symbol}{formatNumber(monte_carlo?.stats?.median)}
              </div>
            </div>
            <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/10 text-center">
              <div className="text-[10px] uppercase tracking-wider text-[#a6b0c3] font-semibold">MC P95 (Bull)</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#34b38a] tabular-nums mt-1">
                {symbol}{formatNumber(p95)}
              </div>
            </div>
          </div>
        </div>

        {/* Right 5 Cols: Enterprise-to-Equity Bridge & Horizon Split (With Arithmetic Operators & Bank Support) */}
        <div className="xl:col-span-5 bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-display font-bold text-base sm:text-lg text-[#f4eedf] tracking-tight">
                {isFinancial ? 'Terminal Value & Bank Equity Bridge' : 'Enterprise-to-Equity Value Bridge'}
              </h3>
              <span className="text-xs font-semibold text-[#a6b0c3] tabular-nums">
                TV Share: <strong className="text-[#8ab4f8]">{pvTvShare.toFixed(1)}%</strong>
              </span>
            </div>

            {/* Stacked Horizon Composition Bar */}
            <div className="mb-4">
              <div className="flex h-3 rounded-full overflow-hidden bg-[#0d121a] border border-[#f4eedf]/10">
                <div
                  className="bg-[#34b38a] h-full transition-all duration-300"
                  style={{ width: `${pv5YrShare}%` }}
                />
                <div
                  className="bg-[#5b8fd9] h-full transition-all duration-300"
                  style={{ width: `${pvTvShare}%` }}
                />
              </div>
              <div className="flex justify-between text-[11px] font-semibold mt-1.5 tabular-nums">
                <span className="text-[#34b38a]">
                  ● {isFinancial ? '5-Yr FCFE PV' : '5-Yr Cash Flows PV'}: {formatCurrency(pv5Yr, symbol, true)} ({pv5YrShare.toFixed(1)}%)
                </span>
                <span className="text-[#8ab4f8]">
                  ● Terminal Value PV: {formatCurrency(pvTv, symbol, true)} ({pvTvShare.toFixed(1)}%)
                </span>
              </div>
            </div>

            {/* Bridge Numbers Table with Arithmetic Signs */}
            <div className="space-y-2 text-xs border-t border-[#f4eedf]/10 pt-3">
              {isFinancial ? (
                /* Bank Equity Bridge */
                <>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3] flex items-center gap-1.5">
                      <span className="w-5 text-center font-bold text-[#34b38a]">(+)</span>
                      <span>PV of 5-Year Regulatory Capital FCFE</span>
                    </span>
                    <span className="font-display font-bold tabular-nums text-[#34b38a]">+{formatCurrency(pv5Yr, symbol, true)}</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3] flex items-center gap-1.5">
                      <span className="w-5 text-center font-bold text-[#8ab4f8]">(+)</span>
                      <span>PV of Terminal Equity Value (Justified P/B)</span>
                    </span>
                    <span className="font-display font-bold tabular-nums text-[#8ab4f8]">+{formatCurrency(pvTv, symbol, true)}</span>
                  </div>
                  <div className="flex justify-between items-center py-1.5 border-b border-[#f4eedf]/10 font-semibold bg-[#0d121a]/50 px-2 rounded-lg">
                    <span className="text-[#f4eedf] flex items-center gap-1.5">
                      <span className="w-5 text-center font-bold text-[#e3b23c]">(=)</span>
                      <span>Implied Total Equity Value</span>
                    </span>
                    <span className="font-display font-bold text-sm tabular-nums text-[#e3b23c]">{formatCurrency(dcf_result?.equity_value, symbol, true)}</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3] flex items-center gap-1.5">
                      <span className="w-5 text-center font-bold text-[#a6b0c3]">(÷)</span>
                      <span>Diluted Shares Outstanding</span>
                    </span>
                    <span className="font-display font-bold tabular-nums text-[#f4eedf]">{formatShares(market_data?.shares_outstanding, market)}</span>
                  </div>
                  <div className="flex justify-between items-center pt-2">
                    <span className="text-[#f4eedf] flex items-center gap-1.5">
                      <span className="w-5 text-center font-bold text-[#e3b23c]">(=)</span>
                      <span className="font-bold">DCF Intrinsic Fair Value per Share</span>
                    </span>
                    <span className="font-display font-bold text-lg tabular-nums text-[#e3b23c]">{symbol}{formatNumber(impliedPrice)}</span>
                  </div>
                  <div className="mt-2 text-[10px] text-[#a6b0c3] bg-[#0d121a] p-2 rounded-lg border border-[#f4eedf]/8">
                    🏦 <strong className="text-[#f4eedf]">Bank Framework:</strong> Customer deposits &amp; borrowings are operational funding rather than capital structure debt. Valued directly to Equity via Regulatory Capital FCFE.
                  </div>
                </>
              ) : (
                /* Corporate / Industrial FCFF Bridge */
                <>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3] flex items-center gap-1.5">
                      <span className="w-5 text-center font-bold text-[#34b38a]">(+)</span>
                      <span>PV of 5-Year Unlevered Free Cash Flow (FCFF)</span>
                    </span>
                    <span className="font-display font-bold tabular-nums text-[#34b38a]">+{formatCurrency(pv5Yr, symbol, true)}</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3] flex items-center gap-1.5">
                      <span className="w-5 text-center font-bold text-[#8ab4f8]">(+)</span>
                      <span>PV of Terminal Value (g = {formatPercent(dcf_result?.terminal_growth ?? data.macro?.terminal_growth)})</span>
                    </span>
                    <span className="font-display font-bold tabular-nums text-[#8ab4f8]">+{formatCurrency(pvTv, symbol, true)}</span>
                  </div>
                  <div className="flex justify-between items-center py-1.5 border-b border-[#f4eedf]/10 font-semibold bg-[#0d121a]/50 px-2 rounded-lg">
                    <span className="text-[#f4eedf] flex items-center gap-1.5">
                      <span className="w-5 text-center font-bold text-[#f4eedf]">(=)</span>
                      <span>Implied Enterprise Value (EV)</span>
                    </span>
                    <span className="font-display font-bold text-sm tabular-nums text-[#f4eedf]">{formatCurrency(dcf_result?.enterprise_value, symbol, true)}</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3] flex items-center gap-1.5">
                      <span className="w-5 text-center font-bold text-[#e07a5f]">(−)</span>
                      <span>Total Balance Sheet Debt</span>
                    </span>
                    <span className="font-display font-bold tabular-nums text-[#e07a5f]">−{formatCurrency(totalDebt, symbol, true)}</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3] flex items-center gap-1.5">
                      <span className="w-5 text-center font-bold text-[#34b38a]">(+)</span>
                      <span>Cash &amp; Marketable Securities</span>
                    </span>
                    <span className="font-display font-bold tabular-nums text-[#34b38a]">+{formatCurrency(totalCash, symbol, true)}</span>
                  </div>
                  <div className="flex justify-between items-center py-1.5 border-b border-[#f4eedf]/10 font-semibold bg-[#0d121a]/50 px-2 rounded-lg">
                    <span className="text-[#f4eedf] flex items-center gap-1.5">
                      <span className="w-5 text-center font-bold text-[#e3b23c]">(=)</span>
                      <span>Implied Equity Value</span>
                    </span>
                    <span className="font-display font-bold text-sm tabular-nums text-[#e3b23c]">{formatCurrency(dcf_result?.equity_value, symbol, true)}</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3] flex items-center gap-1.5">
                      <span className="w-5 text-center font-bold text-[#a6b0c3]">(÷)</span>
                      <span>Diluted Shares Outstanding</span>
                    </span>
                    <span className="font-display font-bold tabular-nums text-[#f4eedf]">{formatShares(market_data?.shares_outstanding, market)}</span>
                  </div>
                  <div className="flex justify-between items-center pt-2">
                    <span className="text-[#f4eedf] flex items-center gap-1.5">
                      <span className="w-5 text-center font-bold text-[#e3b23c]">(=)</span>
                      <span className="font-bold">DCF Intrinsic Fair Value per Share</span>
                    </span>
                    <span className="font-display font-bold text-lg tabular-nums text-[#e3b23c]">{symbol}{formatNumber(impliedPrice)}</span>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>

      </div>

      {/* =================================================================== */}
      {/* ROW 2: 3-COLUMN FULL-WIDTH STATS GRID                               */}
      {/* (1. Company & Financial Stats | 2. WACC Breakdown | 3. Multiples)   */}
      {/* =================================================================== */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-stretch">

        {/* COLUMN 1: Company Details & Audited Baseline Stats */}
        <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3.5 pb-2.5 border-b border-[#f4eedf]/10">
              <h3 className="font-display font-bold text-base sm:text-lg text-[#f4eedf] tracking-tight">
                Company &amp; Financial Snapshot
              </h3>
              <span className="text-[11px] font-semibold px-2 py-0.5 rounded bg-[#0d121a] text-[#a6b0c3] border border-[#f4eedf]/10">
                {company?.sector || 'Equities'}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2.5 mb-3">
              <div className="bg-[#0d121a] p-2.5 rounded-xl border border-[#f4eedf]/6">
                <div className="text-[11px] text-[#a6b0c3]">Market Cap</div>
                <div className="font-display font-bold text-sm sm:text-base text-[#f4eedf] tabular-nums mt-0.5">
                  {formatCurrency(mktCap, symbol, true)}
                </div>
              </div>
              <div className="bg-[#0d121a] p-2.5 rounded-xl border border-[#f4eedf]/6">
                <div className="text-[11px] text-[#a6b0c3]">Market Enterprise Val</div>
                <div className="font-display font-bold text-sm sm:text-base text-[#f4eedf] tabular-nums mt-0.5">
                  {formatCurrency(validation?.market_ev || (mktCap + totalDebt - totalCash), symbol, true)}
                </div>
              </div>
            </div>

            <div className="space-y-2 text-xs">
              <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                <span className="text-[#a6b0c3]">Industry</span>
                <span className="font-semibold text-[#f4eedf] truncate max-w-[180px]">{company?.industry || company?.sector || 'N/A'}</span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                <span className="text-[#a6b0c3]">Shares Outstanding</span>
                <span className="font-display font-bold tabular-nums text-[#f4eedf]">{formatShares(market_data?.shares_outstanding, market)}</span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                <span className="text-[#a6b0c3]">Latest Audited Revenue</span>
                <span className="font-display font-bold tabular-nums text-[#f4eedf]">{formatCurrency(latestRev, symbol, true)}</span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                <span className="text-[#a6b0c3]">Trailing EBITDA</span>
                <span className="font-display font-bold tabular-nums text-[#f4eedf]">{formatCurrency(validation?.trailing_ebitda, symbol, true)}</span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                <span className="text-[#a6b0c3]">Operating Income (EBIT)</span>
                <span className="font-display font-bold tabular-nums text-[#f4eedf]">{formatCurrency(latestEbit, symbol, true)}</span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                <span className="text-[#a6b0c3]">Net Profit / Net Income</span>
                <span className="font-display font-bold tabular-nums text-[#34b38a]">{formatCurrency(latestNi, symbol, true)}</span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                <span className="text-[#a6b0c3]">Book Value of Equity</span>
                <span className="font-display font-bold tabular-nums text-[#f4eedf]">{formatCurrency(latestBv, symbol, true)}</span>
              </div>
              <div className="flex justify-between items-center pt-1">
                <span className="text-[#a6b0c3]">Annual Dividends Paid</span>
                <span className="font-display font-bold tabular-nums text-[#e3b23c]">{formatCurrency(latestDiv, symbol, true)}</span>
              </div>
            </div>
          </div>
        </div>

        {/* COLUMN 2: WACC & Capital Structure Breakdown */}
        <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3.5 pb-2.5 border-b border-[#f4eedf]/10">
              <h3 className="font-display font-bold text-base sm:text-lg text-[#f4eedf] tracking-tight">
                {isFinancial ? 'Cost of Capital (FIG Model)' : 'WACC & Capital Structure'}
              </h3>
              <span className="text-xs font-display font-bold text-[#e3b23c] tabular-nums">
                WACC: {formatPercent(wacc_details?.wacc)}
              </span>
            </div>

            {/* Equity vs Debt Weight Bar */}
            <div className="mb-3.5">
              <div className="flex h-3 rounded-full overflow-hidden bg-[#0d121a] border border-[#f4eedf]/10">
                <div 
                  className="bg-[#5b8fd9] h-full" 
                  style={{ width: `${(wacc_details?.weight_equity || 0) * 100}%` }}
                />
                <div 
                  className="bg-[#e3b23c] h-full" 
                  style={{ width: `${(wacc_details?.weight_debt || 0) * 100}%` }}
                />
              </div>
              <div className="flex justify-between text-[11px] font-semibold mt-1.5 text-[#a6b0c3] tabular-nums">
                <span className="text-[#8ab4f8]">
                  {isFinancial ? 'Equity Weight: 100%' : `Equity Weight: ${formatPercent(wacc_details?.weight_equity)}`}
                </span>
                <span className="text-[#e3b23c]">
                  {isFinancial ? 'Deposits: Operational' : `Debt Weight: ${formatPercent(wacc_details?.weight_debt)}`}
                </span>
              </div>
            </div>

            {/* 4 Key WACC Boxes */}
            <div className="grid grid-cols-2 gap-2.5 mb-3">
              <div className="bg-[#0d121a] p-2.5 rounded-xl border border-[#f4eedf]/6">
                <div className="text-[11px] text-[#a6b0c3]">Cost of Equity (Ke)</div>
                <div className="font-display font-bold text-base text-[#34b38a] tabular-nums mt-0.5">
                  {formatPercent(wacc_details?.cost_of_equity)}
                </div>
              </div>
              <div className="bg-[#0d121a] p-2.5 rounded-xl border border-[#f4eedf]/6">
                <div className="text-[11px] text-[#a6b0c3]">After-Tax Debt (Kd)</div>
                <div className="font-display font-bold text-base text-[#f4eedf] tabular-nums mt-0.5">
                  {isFinancial ? 'Direct FCFE' : formatPercent(wacc_details?.cost_of_debt)}
                </div>
              </div>
            </div>

            <div className="space-y-2 text-xs">
              <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                <span className="text-[#a6b0c3]">Pre-Tax Cost of Debt</span>
                <span className="font-display font-bold tabular-nums text-[#f4eedf]">
                  {isFinancial ? 'N/A' : formatPercent(wacc_details?.pretax_cost_of_debt)}
                </span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                <span className="text-[#a6b0c3]">Synthetic Credit Rating</span>
                <span className="font-display font-bold text-[#e3b23c]">
                  {wacc_details?.synthetic_rating || 'N/A'}
                  {wacc_details?.default_spread != null && ` (+${(wacc_details.default_spread * 100).toFixed(2)}% spread)`}
                </span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                <span className="text-[#a6b0c3]">Interest Coverage (EBIT / Int)</span>
                <span className="font-display font-bold tabular-nums text-[#f4eedf]">
                  {wacc_details?.interest_coverage ? `${wacc_details.interest_coverage.toFixed(1)}x` : 'N/A'}
                </span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                <span className="text-[#a6b0c3]">Total Debt vs. Cash</span>
                <span className="font-display font-bold tabular-nums text-[#f4eedf]">
                  {formatCurrency(totalDebt, symbol, true)} / <span className="text-[#34b38a]">{formatCurrency(totalCash, symbol, true)}</span>
                </span>
              </div>
              <div className="flex justify-between items-center pt-1">
                <span className="text-[#a6b0c3]">Minimum WACC Floor</span>
                <span className="font-display font-bold tabular-nums text-[#a6b0c3]">
                  {formatPercent(wacc_details?.min_wacc)}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* COLUMN 3: Market Multiple Cross-Check & Historical Ratios */}
        <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3.5 pb-2.5 border-b border-[#f4eedf]/10">
              <h3 className="font-display font-bold text-base sm:text-lg text-[#f4eedf] tracking-tight">
                {isFinancial ? 'P/B Multiple Cross-Check' : 'Valuation Multiples & Ratios'}
              </h3>
              {renderValidationBadge()}
            </div>

            {/* Visual Multiple Comparison Bars */}
            {!isFinancial && (
              <div className="space-y-2.5 mb-4 bg-[#0d121a] p-3 rounded-xl border border-[#f4eedf]/6">
                <div>
                  <div className="flex justify-between text-[11px] mb-1">
                    <span className="text-[#a6b0c3]">Current Market {validation?.metric_used === 'ev_revenue' ? 'EV/Sales' : 'EV/EBITDA'}</span>
                    <span className="font-display font-bold text-[#f4eedf] tabular-nums">{formatNumber(mktMult)}x</span>
                  </div>
                  <div className="h-2 rounded-full bg-[#18202c] overflow-hidden">
                    <div className="h-full bg-[#e07a5f]" style={{ width: `${Math.min(100, (mktMult / maxMult) * 100)}%` }} />
                  </div>
                </div>
                <div>
                  <div className="flex justify-between text-[11px] mb-1">
                    <span className="text-[#a6b0c3]">DCF Implied {validation?.metric_used === 'ev_revenue' ? 'EV/Sales' : 'EV/EBITDA'}</span>
                    <span className="font-display font-bold text-[#e3b23c] tabular-nums">{formatNumber(modMult)}x</span>
                  </div>
                  <div className="h-2 rounded-full bg-[#18202c] overflow-hidden">
                    <div className="h-full bg-[#e3b23c]" style={{ width: `${Math.min(100, (modMult / maxMult) * 100)}%` }} />
                  </div>
                </div>
              </div>
            )}

            <div className="space-y-2 text-xs">
              {isFinancial ? (
                <>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3]">Current Market P/B</span>
                    <span className="font-display font-bold tabular-nums text-[#f4eedf]">{formatNumber(validation?.market_multiple)}x</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3]">Model Implied P/B</span>
                    <span className="font-display font-bold tabular-nums text-[#f4eedf]">{formatNumber(validation?.model_multiple)}x</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3]">Justified P/B (Gordon ROE)</span>
                    <span className="font-display font-bold tabular-nums text-[#e3b23c]">{formatNumber(validation?.justified_pb)}x</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3]">Book Value / Share (BVPS)</span>
                    <span className="font-display font-bold tabular-nums text-[#f4eedf]">{symbol}{formatNumber(validation?.bvps)}</span>
                  </div>
                </>
              ) : (
                <>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3]">Multiple Divergence Gap</span>
                    <span className={`font-display font-bold tabular-nums ${(validation?.multiple_gap_pct || 0) < 0.5 ? 'text-[#34b38a]' : 'text-[#e3b23c]'}`}>
                      {formatPercent(validation?.multiple_gap_pct)}
                    </span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3]">Implied Yr-5 Exit Multiple (vs {benchMult}x Bench)</span>
                    <span className="font-display font-bold tabular-nums text-[#f4eedf]">
                      {formatNumber(validation?.implied_exit_multiple ?? diagnostics?.implied_exit_multiple)}x
                    </span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3]">Exit-Multiple Implied Share Price</span>
                    <span className="font-display font-bold tabular-nums text-[#8ab4f8]">
                      {exitImpliedPrice ? `${symbol}${formatNumber(exitImpliedPrice)}` : 'N/A'}
                    </span>
                  </div>
                </>
              )}
              <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                <span className="text-[#a6b0c3]">4-Yr Avg Return on Equity (ROE)</span>
                <span className="font-display font-bold tabular-nums text-[#34b38a]">{formatPercent(historicals?.avg_roe)}</span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                <span className="text-[#a6b0c3]">4-Yr Avg EBIT Margin / Rev Growth</span>
                <span className="font-display font-bold tabular-nums text-[#f4eedf]">
                  {formatPercent(historicals?.avg_ebit_margin)} / {formatPercent(historicals?.avg_rev_growth)}
                </span>
              </div>
              <div className="flex justify-between items-center pt-1">
                <span className="text-[#a6b0c3]">4-Yr Avg CapEx % / Dividend Payout</span>
                <span className="font-display font-bold tabular-nums text-[#f4eedf]">
                  {formatPercent(historicals?.avg_capex_pct)} / {formatPercent(historicals?.avg_payout)}
                </span>
              </div>
            </div>
          </div>
        </div>

      </div>

      {/* =================================================================== */}
      {/* ROW 3: AI VALUATION SUMMARY                                         */}
      {/* =================================================================== */}
      <div className="bg-[#141b26] rounded-2xl p-5 shadow-lg border border-[#f4eedf]/10">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center space-x-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#0d121a] border border-[#f4eedf]/12 flex items-center justify-center text-[#e3b23c]">
              <FiCpu className="text-base" />
            </div>
            <div>
              <h3 className="font-display font-bold text-base sm:text-lg text-[#f4eedf]">AI Valuation Summary</h3>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            {aiSummary && (
              <button 
                onClick={handleDownloadPDF}
                className="flex items-center space-x-2 text-xs font-bold bg-[#1f2937] hover:bg-[#283548] text-[#f4eedf] border border-[#f4eedf]/15 px-3.5 py-2 rounded-xl transition-colors cursor-pointer"
              >
                <FiDownload /> <span>Download PDF</span>
              </button>
            )}
            {!aiSummary && !aiLoading && (
              <button 
                onClick={onFetchAISummary}
                className="bg-[#e3b23c] hover:bg-[#ecc052] text-[#0f141c] font-display text-xs font-bold rounded-xl px-4 py-2 transition-all shadow-md cursor-pointer"
              >
                Generate AI Summary
              </button>
            )}
          </div>
        </div>
        
        {aiLoading && (
          <div className="flex items-center justify-center gap-3 py-6 mt-3 border-t border-[#f4eedf]/10">
            <div className="animate-spin rounded-full h-5 w-5 border-t-2 border-b-2 border-[#e3b23c]"></div>
            <div className="text-[#a6b0c3] text-xs font-semibold">Generating AI valuation analysis...</div>
          </div>
        )}

        {aiSummary && (
          <div className="mt-4 pt-4 border-t border-[#f4eedf]/10">
            <AIReportRenderer jsonString={aiSummary} />
          </div>
        )}
      </div>

    </div>
  );
};

export default OverviewTab;
