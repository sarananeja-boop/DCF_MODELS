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

const OverviewTab = ({ data, aiSummary, aiLoading, onFetchAISummary, onTabChange }) => {
  if (!data) return <div className="p-8 text-center text-[#a6b0c3]">No data available</div>;

  const { company, market_data, wacc: wacc_details, dcf_result, monte_carlo, validation, verdict, diagnostics, historicals, metadata } = data;
  const isFinancial = Boolean(company?.is_financial || diagnostics?.is_financial || dcf_result?.is_financial);
  const modelType = String(company?.model_type || dcf_result?.model_type || diagnostics?.model_type || '');
  const isInsurance = Boolean(modelType.startsWith('INSURANCE_') || dcf_result?.is_insurance);
  const isReit = Boolean(modelType === 'REIT_INVIT_AFFO' || dcf_result?.is_reit);
  const isEquityModel = Boolean(
    isFinancial ||
    isInsurance ||
    isReit ||
    company?.is_equity_model ||
    modelType === 'CORPORATE_DDM' ||
    diagnostics?.is_equity_model ||
    dcf_result?.is_equity_model
  );
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
  const justifiedPrice = dcf_result?.justified_price ?? validation?.justified_price;

  const scaleMax = Math.max(currentPrice, impliedPrice, p95, exitImpliedPrice || 0) * 1.16 || 100;
  const pricePosPct = Math.min(94, Math.max(6, (currentPrice / scaleMax) * 100));
  const fairPosPct = Math.min(94, Math.max(6, (impliedPrice / scaleMax) * 100));
  const p5PosPct = Math.min(92, Math.max(2, (p5 / scaleMax) * 100));
  const p95PosPct = Math.min(98, Math.max(p5PosPct + 4, (p95 / scaleMax) * 100));

  // Dynamic alignment helper to ensure callout badges never bleed off the card edges on mobile or desktop
  const getCalloutAlign = (pct) => {
    const clampedPct = Math.min(96, Math.max(4, pct));
    return {
      transform: `translateX(-${Math.round(clampedPct)}%)`,
      pointerLeft: `${Math.round(clampedPct)}%`,
    };
  };
  const fairAlign = getCalloutAlign(fairPosPct);
  const priceAlign = getCalloutAlign(pricePosPct);

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
  const minorityClaim = dcf_result?.minority_interest ?? wacc_details?.minority_interest_claim ?? historicals?.minority_interest_claim ?? 0;
  const preferredClaim = dcf_result?.preferred_stock ?? wacc_details?.preferred_stock_claim ?? historicals?.preferred_stock_claim ?? 0;
  const minorityPreferred = minorityClaim + preferredClaim;
  const valuationShares = dcf_result?.shares_used ?? market_data?.shares_diluted_tsm ?? market_data?.shares_outstanding;
  const mktCap = market_data?.market_cap || (market_data?.shares_outstanding || 0) * currentPrice;

  // Multiple bar scaling
  const mktMult = validation?.market_multiple || 0;
  const modMult = validation?.model_multiple || 0;
  const benchMult = validation?.benchmark_exit_multiple ?? diagnostics?.benchmark_exit_multiple ?? 10;
  const maxMult = Math.max(mktMult, modMult, benchMult, 1) * 1.15;

  // Validation Gate & Scenarios
  const validationGate = data.validation_gate || validation || {};
  const valStatus = validationGate?.validation_status || (validation?.status ? String(validation.status) : null);
  const scenariosObj = data.scenarios && typeof data.scenarios === 'object' ? data.scenarios : null;
  const isUnsupported = Boolean(valStatus === 'UNSUPPORTED_MODEL' || data.model_suitability?.supported === false);

  // Distress & Stressed DCF Diagnostics
  const isDistressed = Boolean(
    verdict?.is_distressed ||
    verdict?.verdict?.includes('DISTRESSED') ||
    verdict?.verdict?.includes('UNRELIABLE') ||
    (dcf_result?.equity_value != null && dcf_result.equity_value <= 0)
  );
  const tvInvalid = dcf_result?.terminal_value_valid === false || diagnostics?.terminal_value_valid === false;
  const negHistFcf = Boolean(diagnostics?.historical_fcf_negative || validation?.metric_used === 'ev_revenue');
  const tvFlag = Boolean(diagnostics?.tv_share_flag);
  const gaapSbcNote = diagnostics?.gaap_sbc_note;
  const rawEqVal = dcf_result?.raw_equity_value ?? ((dcf_result?.enterprise_value || 0) - totalDebt + totalCash - minorityPreferred);

  if (isUnsupported || !dcf_result) {
    const suit = data.model_suitability || company?.model_suitability || {};
    return (
      <div className="space-y-4 text-[#f4eedf]">
        <div className="bg-[#141b26] rounded-2xl p-6 border border-[#e07a5f]/35 shadow-lg space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2.5">
              <FiAlertTriangle className="w-5 h-5 text-[#e07a5f]" />
              <h3 className="font-display font-bold text-lg text-[#f4eedf]">
                Fail-Closed Validation Gate: {valStatus || 'UNSUPPORTED_MODEL'}
              </h3>
            </div>
            <span className="px-2.5 py-1 rounded-lg bg-[#e07a5f]/15 border border-[#e07a5f]/35 text-[#e07a5f] text-xs font-bold">
              {suit?.model_family || 'UNSUPPORTED'}
            </span>
          </div>
          <p className="text-sm text-[#c5cedd] leading-relaxed">
            {suit?.reason || verdict?.description || 'This sector/security cannot be reliably valued with Corporate FCFF DCF or Bank DDM under institutional standards.'}
          </p>
          {suit?.recommended_methodology && (
            <div className="p-3 rounded-xl bg-[#0d121a] border border-[#f4eedf]/10 text-xs text-[#a6b0c3]">
              <strong className="text-[#e3b23c]">Required Valuation Methodology: </strong>
              {suit.recommended_methodology}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 text-[#f4eedf]">

      {/* =================================================================== */}
      {/* STRESSED / DISTRESSED DCF & DIAGNOSTIC EXPLANATION BANNER           */}
      {/* =================================================================== */}
      {(isDistressed || tvInvalid || negHistFcf || tvFlag || gaapSbcNote) && (
        <div className="bg-[#141b26] rounded-2xl p-4 sm:p-5 border border-[#f4eedf]/12 shadow-lg space-y-2.5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <FiAlertTriangle className={`w-4 h-4 shrink-0 ${isDistressed || tvInvalid ? 'text-[#e07a5f]' : 'text-[#e3b23c]'}`} />
              <span className="font-display font-bold text-xs sm:text-sm uppercase tracking-wider text-[#f4eedf]">
                {isDistressed
                  ? 'Why DCF Is Distressed / Unreliable for This Security'
                  : tvInvalid
                  ? 'Terminal Value Warning — Negative Year-5 Cash Flow'
                  : 'DCF Model Diagnostic & Structural Notes'}
              </span>
            </div>
            <span className="text-[11px] font-semibold text-[#a6b0c3]">
              Model Diagnostics
            </span>
          </div>

          <div className="space-y-2 text-xs text-[#c5cedd] leading-relaxed">
            {isDistressed && (
              <div className="border-l-2 border-[#e07a5f] pl-3 py-0.5">
                <strong className="text-[#f4eedf]">Debt Claims Exceed Baseline Cash Flows: </strong>
                {dcf_result?.equity_value != null && dcf_result.equity_value <= 0 ? (
                  <>
                    Discounted 5-Year Operating Cash Flows plus Terminal Value produce an Implied Enterprise Value of{' '}
                    <strong className="text-[#f4eedf]">{formatCurrency(dcf_result?.enterprise_value, symbol, true)}</strong>. After subtracting Total Balance Sheet Debt (<strong className="text-[#e07a5f]">{formatCurrency(totalDebt, symbol, true)}</strong>) and adding Cash (<strong className="text-[#34b38a]">{formatCurrency(totalCash, symbol, true)}</strong>), raw Implied Equity Value is{' '}
                    <strong className="text-[#e07a5f]">{formatCurrency(rawEqVal, symbol, true)}</strong> (floored at <strong className="text-[#f4eedf]">{symbol}0.00/share</strong> due to limited shareholder liability).{' '}
                  </>
                ) : null}
                {verdict?.description && <span>{verdict.description} </span>}
                {!exitImpliedPrice && !isEquityModel && (
                  <span>
                    Similarly, the <strong className="text-[#f4eedf]">Exit-Multiple Share Price is N/A</strong> because Year-5 projected EBITDA at the {benchMult}x peer multiple remains below net debt obligations.
                  </span>
                )}
              </div>
            )}

            {tvInvalid && (
              <div className="border-l-2 border-[#e07a5f] pl-3 py-0.5">
                <strong className="text-[#f4eedf]">Invalid Perpetual Terminal Value: </strong>
                {dcf_result?.terminal_value_note || diagnostics?.terminal_value_note || 'Year-5 projected free cash flow remains negative under baseline assumptions. A negative cash flow cannot be capitalized into perpetuity via Gordon Growth, so Terminal Value is set to zero.'}
              </div>
            )}

            {gaapSbcNote ? (
              <div className="border-l-2 border-[#34b38a] pl-3 py-0.5">
                <strong className="text-[#f4eedf]">GAAP vs. Non-GAAP &amp; Stock-Based Compensation (SBC): </strong>
                {gaapSbcNote.replace(/^GAAP vs\. Non-GAAP & SBC Note:\s*/i, '')}
              </div>
            ) : negHistFcf ? (
              <div className="border-l-2 border-[#e3b23c] pl-3 py-0.5">
                <strong className="text-[#f4eedf]">Negative / Depressed Trailing Operating Profit: </strong>
                {validation?.metric_used === 'ev_revenue' ? (
                  <>
                    Trailing EBITDA ({formatCurrency(validation?.trailing_ebitda, symbol, true)}) is negative or zero. The engine automatically switches the multiple cross-check from EV/EBITDA to <strong className="text-[#f4eedf]">EV/Sales</strong> and models a turnaround operating margin convergence toward <strong className="text-[#f4eedf]">{formatPercent(diagnostics?.target_ebit_margin)}</strong> over 5 years.
                  </>
                ) : (
                  <>
                    Trailing Operating EBIT ({formatCurrency(latestEbit, symbol, true)}, {formatPercent(historicals?.avg_ebit_margin)} 4-yr avg margin) is negative. The engine models a turnaround operating margin convergence from <strong className="text-[#f4eedf]">{formatPercent(diagnostics?.current_ebit_margin)}</strong> toward <strong className="text-[#f4eedf]">{formatPercent(diagnostics?.target_ebit_margin)}</strong> over 5 years.
                  </>
                )}
              </div>
            ) : null}

            {tvFlag && diagnostics?.tv_share_note && (
              <div className="border-l-2 border-[#8ab4f8] pl-3 py-0.5">
                <strong className="text-[#f4eedf]">High Terminal Value Concentration ({pvTvShare.toFixed(1)}% of EV): </strong>
                {diagnostics.tv_share_note}
              </div>
            )}
          </div>
        </div>
      )}

      {/* =================================================================== */}
      {/* ROW 1: SIMPLY WALL ST PRICE VS FAIR VALUE BAR + EQUITY VALUE BRIDGE */}
      {/* =================================================================== */}
      <div className="grid grid-cols-1 2xl:grid-cols-12 gap-4 items-start">
        
        {/* Left 7 Cols: Share Price vs Fair Value Visual Scale & Valuation Range Stats */}
        <div className="2xl:col-span-7 bg-[#141b26] rounded-2xl p-4 sm:p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col gap-3 overflow-hidden">
          <div>
            <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
              <div className="flex items-center gap-2.5">
                <h3 className="font-display font-bold text-base sm:text-lg text-[#f4eedf] tracking-tight">
                  Share Price vs. {isEquityModel ? 'DDM / FCFE' : 'DCF'} Fair Value &amp; Probability Band
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
            <div className="relative pt-8 pb-8 px-2 sm:px-4 my-1">
              {/* Fair Value Marker (Top Callout) */}
              <div
                className="absolute top-0 flex flex-col transition-all duration-300 z-20 max-w-[92vw]"
                style={{ left: `${fairPosPct}%`, transform: fairAlign.transform }}
              >
                <div className="px-2.5 sm:px-3 py-1 rounded-lg bg-[#e3b23c] text-[#0f141c] font-display text-[11px] sm:text-xs font-bold whitespace-nowrap shadow-md tabular-nums">
                  {isEquityModel ? 'DDM Fair Value' : 'DCF Fair Value'}: {symbol}{formatNumber(impliedPrice)}
                </div>
                <div className="relative h-3 w-full">
                  <div className="absolute top-0 w-0.5 h-3 bg-[#e3b23c] -translate-x-1/2" style={{ left: fairAlign.pointerLeft }} />
                </div>
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
                className="absolute bottom-0 flex flex-col transition-all duration-300 z-20 max-w-[92vw]"
                style={{ left: `${pricePosPct}%`, transform: priceAlign.transform }}
              >
                <div className="relative h-3 w-full">
                  <div className="absolute bottom-0 w-0.5 h-3 bg-[#f4eedf] -translate-x-1/2" style={{ left: priceAlign.pointerLeft }} />
                </div>
                <div className="px-2.5 sm:px-3 py-1 rounded-lg bg-[#f4eedf] text-[#0f141c] font-display text-[11px] sm:text-xs font-bold whitespace-nowrap shadow-md tabular-nums">
                  Current Price: {symbol}{formatNumber(currentPrice)}
                </div>
              </div>
            </div>

            {/* Middle Insight Strip (Eliminates Empty Space with Rich Valuation Insights) */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 my-2 py-2.5 border-t border-b border-[#f4eedf]/10">
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
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 pt-1">
            <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/10 text-center">
              <div className="text-[10px] uppercase tracking-wider text-[#e3b23c] font-bold">{isEquityModel ? 'DDM Value' : 'DCF Value'}</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#f4eedf] tabular-nums mt-1 truncate">
                {symbol}{formatNumber(impliedPrice)}
              </div>
            </div>
            <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/10 text-center">
              <div className="text-[10px] uppercase tracking-wider text-[#a6b0c3] font-semibold">
                {isReit ? 'Cap-Rate NAV' : isEquityModel ? 'Justified P/B' : 'Exit Mult.'}
              </div>
              <div className="font-display font-bold text-sm sm:text-base text-[#f4eedf] tabular-nums mt-1 truncate">
                {isEquityModel
                  ? (justifiedPrice ? `${symbol}${formatNumber(justifiedPrice)}` : 'N/A')
                  : (exitImpliedPrice ? `${symbol}${formatNumber(exitImpliedPrice)}` : 'N/A')}
              </div>
            </div>
            <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/10 text-center">
              <div className="text-[10px] uppercase tracking-wider text-[#a6b0c3] font-semibold">MC P5 (Bear)</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#e07a5f] tabular-nums mt-1 truncate">
                {symbol}{formatNumber(p5)}
              </div>
            </div>
            <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/10 text-center">
              <div className="text-[10px] uppercase tracking-wider text-[#a6b0c3] font-semibold">MC P25</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#f4eedf] tabular-nums mt-1 truncate">
                {symbol}{formatNumber(p25)}
              </div>
            </div>
            <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/10 text-center">
              <div className="text-[10px] uppercase tracking-wider text-[#8ab4f8] font-bold">MC Median</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#f4eedf] tabular-nums mt-1 truncate">
                {symbol}{formatNumber(monte_carlo?.stats?.median)}
              </div>
            </div>
            <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/10 text-center">
              <div className="text-[10px] uppercase tracking-wider text-[#a6b0c3] font-semibold">MC P95 (Bull)</div>
              <div className="font-display font-bold text-sm sm:text-base text-[#34b38a] tabular-nums mt-1 truncate">
                {symbol}{formatNumber(p95)}
              </div>
            </div>
          </div>
        </div>

        {/* Right 5 Cols: Enterprise-to-Equity Bridge & Horizon Split (With Arithmetic Operators & Bank / Corporate DDM Support) */}
        <div className="2xl:col-span-5 bg-[#141b26] rounded-2xl p-4 sm:p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col gap-3 overflow-hidden">
          <div>
            <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
              <h3 className="font-display font-bold text-base sm:text-lg text-[#f4eedf] tracking-tight">
                {isReit
                  ? 'Terminal Value & REIT AFFO Equity Bridge'
                  : isInsurance
                  ? 'Terminal Value & Actuarial Equity Bridge'
                  : isFinancial
                  ? 'Terminal Value & Bank Equity Bridge'
                  : isEquityModel
                  ? 'Terminal Value & DDM / FCFE Equity Bridge'
                  : 'Enterprise-to-Equity Value Bridge'}
              </h3>
              <div className="flex items-center gap-2 shrink-0">
                <span
                  className={`text-xs font-semibold tabular-nums px-2.5 py-1 rounded-lg border ${
                    pvTvShare >= 65
                      ? 'bg-[#182232] border-[#e3b23c]/35 text-[#f4eedf]'
                      : 'bg-[#0d121a] border-[#f4eedf]/10 text-[#a6b0c3]'
                  }`}
                  title={pvTvShare >= 65 ? 'High Terminal Value Dependency: >65% of Enterprise Value stems from perpetuity assumption' : 'Terminal Value share of total valuation'}
                >
                  TV Share: <strong className={pvTvShare >= 65 ? 'text-[#e3b23c]' : 'text-[#8ab4f8]'}>{pvTvShare.toFixed(1)}%</strong>
                  {pvTvShare >= 65 && (
                    <span className="ml-1 text-[10.5px] font-medium text-[#e3b23c]/90">
                      (High Perpetuity)
                    </span>
                  )}
                </span>
                {pvTvShare >= 65 && onTabChange && (
                  <button
                    type="button"
                    onClick={() => onTabChange('sensitivity')}
                    className="text-[11px] text-[#8ab4f8] hover:text-[#f4eedf] font-semibold transition cursor-pointer flex items-center gap-1 hover:underline ml-0.5"
                    title="Open 2D Sensitivity Matrix (WACC vs. Terminal Growth)"
                  >
                    <span>Sensitivity →</span>
                  </button>
                )}
              </div>
            </div>

            {/* Stacked Horizon Composition Bar */}
            <div className="mb-3">
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
              <div className="flex flex-wrap justify-between gap-1.5 text-[11px] font-semibold mt-1.5 tabular-nums">
                <span className="text-[#34b38a]">
                  ● {isEquityModel ? '5-Yr FCFE PV' : '5-Yr Cash Flows PV'}: {formatCurrency(pv5Yr, symbol, true)} ({pv5YrShare.toFixed(1)}%)
                </span>
                <span className="text-[#8ab4f8]">
                  ● Terminal Value PV: {formatCurrency(pvTv, symbol, true)} ({pvTvShare.toFixed(1)}%)
                </span>
              </div>
            </div>

            {/* Bridge Numbers Table with Arithmetic Signs */}
            <div className="space-y-2 text-xs border-t border-[#f4eedf]/10 pt-3">
              {isEquityModel ? (
                /* Bank or Corporate DDM / FCFE Equity Bridge */
                <>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3] flex items-center gap-1.5">
                      <span className="w-5 text-center font-bold text-[#34b38a]">(+)</span>
                      <span>{isFinancial ? 'PV of 5-Year Regulatory Capital FCFE' : 'PV of 5-Year Dividends / FCFE'}</span>
                    </span>
                    <span className="font-display font-bold tabular-nums text-[#34b38a]">+{formatCurrency(pv5Yr, symbol, true)}</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3] flex items-center gap-1.5">
                      <span className="w-5 text-center font-bold text-[#8ab4f8]">(+)</span>
                      <span>
                        PV of Terminal Equity Value (Gordon Growth)
                        <span className="ml-1.5 text-[10.5px] text-[#a6b0c3]/70 font-mono">({pvTvShare.toFixed(1)}% of Eq)</span>
                      </span>
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
                      <span className="font-bold">DDM / FCFE Fair Value per Share</span>
                    </span>
                    <span className="font-display font-bold text-lg tabular-nums text-[#e3b23c]">{symbol}{formatNumber(impliedPrice)}</span>
                  </div>
                  <div className="mt-2 text-[10px] text-[#a6b0c3] bg-[#0d121a] p-2 rounded-lg border border-[#f4eedf]/8">
                    {isInsurance ? (
                      <>
                        <strong className="text-[#f4eedf]">Insurance Actuarial Framework:</strong> Policyholder reserves &amp; unearned premiums represent investable float rather than corporate financing debt. Valued on Ex-AOCI Common Equity at Cost of Equity (<span className="font-mono">Ke</span>).
                      </>
                    ) : isReit ? (
                      <>
                        <strong className="text-[#f4eedf]">REIT / InvIT AFFO Framework:</strong> Distributable AFFO (NDCF after recurring maintenance CapEx) is discounted directly at Cost of Equity (<span className="font-mono">Ke</span>) and cross-checked against Cap-Rate GAV/NAV.
                      </>
                    ) : isFinancial ? (
                      <>
                        <strong className="text-[#f4eedf]">Bank Framework:</strong> Customer deposits &amp; borrowings are operational funding rather than capital structure debt. Valued directly to Equity via Regulatory Capital FCFE.
                      </>
                    ) : (
                      <>
                        <strong className="text-[#f4eedf]">Corporate DDM / FCFE Framework:</strong> Net income after ROE-implied equity reinvestment (<span className="font-mono">b = g / ROE</span>) is discounted directly at Cost of Equity (<span className="font-mono">Ke</span>) to Equity Value.
                      </>
                    )}
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
                      <span>
                        PV of Terminal Value (g = {formatPercent(dcf_result?.terminal_growth ?? data.macro?.terminal_growth)})
                        <span className="ml-1.5 text-[10.5px] text-[#a6b0c3]/70 font-mono">({pvTvShare.toFixed(1)}% of EV)</span>
                      </span>
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
                      <span>EV-Eligible Unrestricted Cash</span>
                    </span>
                    <span className="font-display font-bold tabular-nums text-[#34b38a]">+{formatCurrency(totalCash, symbol, true)}</span>
                  </div>
                  {minorityPreferred > 0 && (
                    <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                      <span className="text-[#a6b0c3] flex items-center gap-1.5">
                        <span className="w-5 text-center font-bold text-[#e07a5f]">(−)</span>
                        <span>Minority Interest &amp; Preferred Stock</span>
                      </span>
                      <span className="font-display font-bold tabular-nums text-[#e07a5f]">−{formatCurrency(minorityPreferred, symbol, true)}</span>
                    </div>
                  )}
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
                      <span>Diluted Valuation Shares (TSM)</span>
                    </span>
                    <span className="font-display font-bold tabular-nums text-[#f4eedf]">{formatShares(valuationShares, market)}</span>
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
      {/* ROW 2: STATS GRID (RESPONSIVE 1/2/3 COLUMNS)                        */}
      {/* (1. Company & Financial Stats | 2. WACC Breakdown | 3. Multiples)   */}
      {/* =================================================================== */}
      <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-4 items-stretch">

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
                {isFinancial
                  ? 'Cost of Capital (FIG Model)'
                  : isEquityModel
                  ? 'Cost of Equity (CAPM Hurdle Rate)'
                  : 'WACC & Capital Structure'}
              </h3>
              <span className="text-xs font-display font-bold text-[#e3b23c] tabular-nums">
                {isEquityModel ? 'Ke' : 'WACC'}: {formatPercent(wacc_details?.wacc)}
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
                  {isEquityModel ? 'Equity Weight: 100%' : `Equity Weight: ${formatPercent(wacc_details?.weight_equity)}`}
                </span>
                <span className="text-[#e3b23c]">
                  {isFinancial
                    ? 'Deposits: Operational'
                    : isEquityModel
                    ? `Corp WACC: ${formatPercent(wacc_details?.corporate_wacc || wacc_details?.wacc)}`
                    : `Debt Weight: ${formatPercent(wacc_details?.weight_debt)}`}
                </span>
              </div>
            </div>

            {/* Transparent Formula Reconciliation */}
            {!isEquityModel && wacc_details?.weight_equity != null && wacc_details?.weight_debt != null && (
              <div className="mb-3 px-2.5 py-1.5 rounded-xl bg-[#0d121a] border border-[#f4eedf]/8 text-[11px] text-[#a6b0c3] flex flex-wrap items-center justify-between gap-1.5">
                <span className="font-mono text-[10.5px]">WACC = (We × Ke) + (Wd × Kd)</span>
                <span className="text-[#f4eedf] font-semibold tabular-nums text-xs">
                  ({formatPercent(wacc_details.weight_equity)} × {formatPercent(wacc_details.cost_of_equity)}) + ({formatPercent(wacc_details.weight_debt)} × {formatPercent(wacc_details.cost_of_debt)}) = <strong className="text-[#e3b23c]">{formatPercent(wacc_details.wacc)}</strong>
                </span>
              </div>
            )}

            {/* 4 Key WACC Boxes */}
            <div className="grid grid-cols-2 gap-2.5 mb-3">
              <div className="bg-[#0d121a] p-2.5 rounded-xl border border-[#f4eedf]/6">
                <div className="text-[11px] text-[#a6b0c3]">Cost of Equity (Ke)</div>
                <div className="font-display font-bold text-base text-[#34b38a] tabular-nums mt-0.5">
                  {formatPercent(wacc_details?.cost_of_equity)}
                </div>
              </div>
              <div className="bg-[#0d121a] p-2.5 rounded-xl border border-[#f4eedf]/6">
                <div className="text-[11px] text-[#a6b0c3]">{isEquityModel ? 'Discount Model' : 'After-Tax Debt (Kd)'}</div>
                <div className="font-display font-bold text-base text-[#f4eedf] tabular-nums mt-0.5">
                  {isEquityModel ? 'Direct FCFE' : formatPercent(wacc_details?.cost_of_debt)}
                </div>
                {!isEquityModel && wacc_details?.tax_shield_capped && (
                  <div className="text-[10px] text-[#e3b23c] mt-0.5" title="Statutory Kd*(1-T) differs because interest deductions are capped by operating EBIT">
                    EBIT-capped shield (vs {formatPercent(wacc_details?.conventional_cost_of_debt)} stat.)
                  </div>
                )}
              </div>
            </div>

            <div className="space-y-2 text-xs">
              <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                <span className="text-[#a6b0c3]">{isEquityModel ? 'Hist Payout / Retention (b)' : 'Pre-Tax Cost of Debt'}</span>
                <span className="font-display font-bold tabular-nums text-[#f4eedf]">
                  {isEquityModel
                    ? `${formatPercent(dcf_result?.historical_payout_ratio ?? historicals?.avg_payout)} / ${formatPercent(dcf_result?.reinvestment_rate)}`
                    : formatPercent(wacc_details?.pretax_cost_of_debt)}
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
                <span className="text-[#a6b0c3]">{isEquityModel ? 'Minimum Ke Floor' : 'Minimum WACC Floor'}</span>
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
                {isEquityModel ? 'P/B Multiple Cross-Check' : 'Valuation Multiples & Ratios'}
              </h3>
              {renderValidationBadge()}
            </div>

            {/* Visual Multiple Comparison Bars */}
            {!isEquityModel && (
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
              {isReit ? (
                <>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3]">Current Market P / AFFO</span>
                    <span className="font-display font-bold tabular-nums text-[#f4eedf]">{formatNumber(validation?.market_multiple ?? dcf_result?.p_affo)}x</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3]">Model Implied P / AFFO</span>
                    <span className="font-display font-bold tabular-nums text-[#f4eedf]">{formatNumber(validation?.model_multiple ?? dcf_result?.justified_pb)}x</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3]">Cap-Rate NAV per Unit ({formatPercent(dcf_result?.benchmark_cap_rate)} Cap)</span>
                    <span className="font-display font-bold tabular-nums text-[#e3b23c]">{symbol}{formatNumber(dcf_result?.cap_rate_nav_per_unit ?? dcf_result?.bvps)}</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3]">AFFO per Unit (Base Run-Rate)</span>
                    <span className="font-display font-bold tabular-nums text-[#f4eedf]">{symbol}{formatNumber(dcf_result?.affo_per_unit)}</span>
                  </div>
                </>
              ) : isEquityModel ? (
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
                    <span className="font-display font-bold tabular-nums text-[#e3b23c]">{formatNumber(validation?.justified_pb ?? dcf_result?.justified_pb)}x</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-[#f4eedf]/6">
                    <span className="text-[#a6b0c3]">{isInsurance ? 'Ex-AOCI Book Value / Share' : 'Book Value / Share (BVPS)'}</span>
                    <span className="font-display font-bold tabular-nums text-[#f4eedf]">{symbol}{formatNumber(validation?.bvps ?? dcf_result?.bvps)}</span>
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

          {/* Dynamic Model Validation & Warning Interpretation Note */}
          <div className="mt-3.5 pt-3 border-t border-[#f4eedf]/10 text-[11px] leading-relaxed text-[#c5cedd] space-y-1.5">
            {isDistressed ? (
              <div className="border-l-2 border-[#e07a5f] pl-2.5">
                <strong className="text-[#e07a5f]">Distressed / Invalid DCF Note: </strong>
                {dcf_result?.equity_value != null && dcf_result.equity_value <= 0 ? (
                  <>
                    Balance sheet debt ({formatCurrency(totalDebt, symbol, true)}) exceeds discounted operating cash flows ({formatCurrency(dcf_result?.enterprise_value, symbol, true)}), resulting in zero baseline equity value. Use multiples or asset-recovery analysis until leverage normalizes.
                  </>
                ) : (
                  <>
                    High debt leverage ({formatCurrency(totalDebt, symbol, true)}) relative to volatile operating cash flows causes elevated downside tail risk in Monte Carlo stress simulations. Consider peer multiples alongside DCF.
                  </>
                )}
              </div>
            ) : validation?.status === 'PASS' ? (
              <div className="border-l-2 border-[#34b38a] pl-2.5">
                <strong className="text-[#34b38a]">Verified ({isEquityModel ? '≤35% P/B Gap' : '<50% Multiple Gap'}): </strong>
                {isEquityModel ? 'DDM / FCFE' : 'DCF'} implied {isEquityModel ? 'P/B' : validation?.metric_used === 'ev_revenue' ? 'EV/Sales' : 'EV/EBITDA'} ({formatNumber(modMult)}x) is within{' '}
                {validation?.multiple_gap_pct != null ? formatPercent(validation.multiple_gap_pct) : 'the normal range'} of the current market multiple ({formatNumber(mktMult)}x), confirming cash-flow projections align with peer market pricing.
              </div>
            ) : validation?.status === 'WARNING' ? (
              <div className="border-l-2 border-[#e3b23c] pl-2.5">
                <strong className="text-[#e3b23c]">How to Interpret WARNING ({isEquityModel ? '35%–65% P/B Gap' : '50%–80% Multiple Gap'}): </strong>
                Market {isEquityModel ? 'P/B' : validation?.metric_used === 'ev_revenue' ? 'EV/Sales' : 'EV/EBITDA'} ({formatNumber(mktMult)}x) diverges by{' '}
                <strong className="text-[#f4eedf]">{formatPercent(validation?.multiple_gap_pct)}</strong> from {isEquityModel ? 'DDM / FCFE' : 'DCF'} implied ({formatNumber(modMult)}x).{' '}
                {modMult < mktMult
                  ? 'The market is pricing in higher revenue/earnings growth or ROE/margin expansion than historical averages.'
                  : 'Baseline projections indicate stronger cash-flow expansion than currently priced by the market.'}
              </div>
            ) : (validation?.status === 'FAIL' || validation?.status === 'FLAG') ? (
              <div className="border-l-2 border-[#e07a5f] pl-2.5">
                <strong className="text-[#e07a5f]">How to Interpret FLAGGED ({isEquityModel ? '>65% P/B Gap' : '>80% Multiple Gap'}): </strong>
                Market {isEquityModel ? 'P/B' : validation?.metric_used === 'ev_revenue' ? 'EV/Sales' : 'EV/EBITDA'} ({formatNumber(mktMult)}x) diverges by{' '}
                <strong className="text-[#f4eedf]">{formatPercent(validation?.multiple_gap_pct)}</strong> from {isEquityModel ? 'DDM / FCFE' : 'DCF'} implied ({formatNumber(modMult)}x).{' '}
                {modMult < mktMult
                  ? 'Stock trades at a steep growth/scarcity premium over historical cash flows; use Model Assumptions sliders to test market-implied growth.'
                  : 'Significant disconnect between baseline cash flows and market valuation.'}
              </div>
            ) : null}

            {validation?.warning && (
              <div className="text-[10.5px] text-[#e3b23c] pl-2.5 border-l-2 border-[#e3b23c]/50">
                ⚠️ {validation.warning}
              </div>
            )}
          </div>
        </div>

      </div>

      {/* =================================================================== */}
      {/* ROW 2B: SCENARIO CROSS-CHECKS                                       */}
      {/* =================================================================== */}
      {scenariosObj && (
        <div className="grid grid-cols-1 gap-4">
          <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg space-y-3">
            <div className="flex items-center justify-between pb-2.5 border-b border-[#f4eedf]/10">
              <h3 className="font-display font-bold text-base text-[#f4eedf]">
                Scenario &amp; Cross-Check Summary
              </h3>
              <span className="text-[11px] font-semibold text-[#8ab4f8]">
                Live Parameterized Sensitivity
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-[#a6b0c3] border-b border-[#f4eedf]/10 text-left">
                    <th className="py-1.5 pr-2 font-semibold">Scenario</th>
                    <th className="py-1.5 px-2 font-semibold text-right">Implied Price</th>
                    <th className="py-1.5 px-2 font-semibold text-right">Δ vs Base</th>
                    <th className="py-1.5 pl-2 font-semibold">Key Driver</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#f4eedf]/6">
                  {Object.entries(scenariosObj).map(([sKey, sc]) => {
                    if (!sc || typeof sc !== 'object') return null;
                    const isApp = sc.applicable !== false && sc.implied_price != null;
                    return (
                      <tr key={sKey}>
                        <td className="py-2 pr-2 font-semibold text-[#f4eedf]">{sc.label || sKey}</td>
                        <td className="py-2 px-2 text-right font-display font-bold tabular-nums text-[#e3b23c]">
                          {isApp ? `${symbol}${formatNumber(sc.implied_price)}` : 'N/A'}
                        </td>
                        <td className={`py-2 px-2 text-right font-display font-semibold tabular-nums ${
                          !isApp || sc.delta_vs_base_pct == null ? 'text-[#a6b0c3]' : sc.delta_vs_base_pct >= 0 ? 'text-[#34b38a]' : 'text-[#e07a5f]'
                        }`}>
                          {isApp && sc.delta_vs_base_pct != null ? `${sc.delta_vs_base_pct >= 0 ? '+' : ''}${sc.delta_vs_base_pct.toFixed(1)}%` : '—'}
                        </td>
                        <td className="py-2 pl-2 text-[#a6b0c3] text-[11px] truncate max-w-[320px]" title={sc.key_driver || sc.note}>
                          {sc.key_driver || sc.note || '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

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

      {/* Research Provenance & Model Audit Disclosures */}
      <div className="bg-[#0d121a] rounded-2xl p-4 border border-white/[0.06] text-xs text-[#818ea4] flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <span>
            <strong className="text-[#a6b0c3]">Model Engine:</strong> {metadata?.model_version ? `ValuationLabs v${metadata.model_version}` : 'ValuationLabs v2.4.0'}
          </span>
          <span className="text-white/10">|</span>
          <span>
            <strong className="text-[#a6b0c3]">Valuation Generated:</strong> {metadata?.valuation_timestamp ? new Date(metadata.valuation_timestamp).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }) : 'Current Session'}
          </span>
          <span className="text-white/10">|</span>
          <span>
            <strong className="text-[#a6b0c3]">Market Price Timestamp:</strong> {metadata?.market_data_timestamp || 'Live Session'}
          </span>
          <span className="text-white/10">|</span>
          <span>
            <strong className="text-[#a6b0c3]">Filings Horizon:</strong> {metadata?.latest_financial_period || 'Audited Annual'}
          </span>
        </div>
        <div className="text-[11px] text-[#64748b]">
          Data Provenance: SEC EDGAR &amp; NSE-BSE Statutory Filings · Fed &amp; RBI 10Y Sovereign Curves
        </div>
      </div>

    </div>
  );
};

export default OverviewTab;
