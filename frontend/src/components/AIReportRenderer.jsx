import React, { useState } from 'react';
import {
  FiFileText,
  FiPrinter,
  FiSun,
  FiMoon,
  FiAlertTriangle,
} from 'react-icons/fi';

const formatNum = (val, currency) => {
  if (val == null || val === '') return '—';
  if (typeof val === 'string') return val;
  const sym = currency === 'INR' ? '₹' : '$';
  return sym + Number(val).toLocaleString(undefined, { maximumFractionDigits: 2 });
};

const formatPct = (val) => {
  if (val == null || val === '') return '—';
  if (typeof val === 'string' && val.includes('%')) return val;
  return Number(val).toFixed(1) + '%';
};

const cleanText = (str) => {
  if (!str || typeof str !== 'string') return '';
  return str.replace(/^(Point\s*\d+\s*:\s*|\d+\.\s*)/i, '').trim();
};

export default function AIReportRenderer({ jsonString }) {
  // Toggle between Paper Mode (White Sheet) and Executive Dark Mode
  const [theme, setTheme] = useState('paper');
  const isPaper = theme === 'paper';

  let report = null;
  try {
    let cleaned = typeof jsonString === 'string' ? jsonString.trim() : '';
    const match = cleaned.match(/\{[\s\S]*\}/);
    if (match) {
      cleaned = match[0];
    }
    report = typeof jsonString === 'string' ? JSON.parse(cleaned) : jsonString;
  } catch (e) {
    return (
      <div className="bg-red-50 border border-red-200 p-6 rounded text-red-900 max-w-4xl mx-auto my-6 font-sans">
        <div className="font-bold flex items-center gap-2 mb-2">
          <FiAlertTriangle /> Parsing Error in Valuation Report Payload
        </div>
        <p className="text-sm text-red-700">
          The research synthesis returned an invalid JSON document. Please click "Generate AI Summary" above to re-generate the note.
        </p>
      </div>
    );
  }

  if (!report || (!report.headline_metrics && !report.summary)) {
    return (
      <div className="bg-slate-50 border border-slate-200 p-8 rounded text-center max-w-4xl mx-auto my-6 font-sans">
        <h3 className="text-slate-700 font-semibold mb-1">Valuation Memorandum Not Available</h3>
        <p className="text-xs text-slate-500">Click "Generate AI Summary" above to produce the institutional research initiation note.</p>
      </div>
    );
  }

  // Handle plain text / markdown fallback
  if (report && !report.headline_metrics && report.summary) {
    return (
      <div className="bg-white border border-slate-300 p-8 rounded text-slate-900 max-w-4xl mx-auto shadow-sm my-6 leading-relaxed whitespace-pre-line font-sans">
        {report.summary}
      </div>
    );
  }

  const {
    company,
    ticker,
    currency,
    headline_metrics: hl = {},
    executive_summary: exec = {},
    variant_perception: vp = {},
    business_and_moat: moat = {},
    expectations_investing: exp = {},
    dcf_cash_flow_bridge: dcfBridge = report.dcf_analysis || {},
    asymmetric_scenarios: scenarios = report.scenarios || {},
    downside_risks: risks = report.risks || [],
    quarterly_monitoring_signposts: monitoring = report.thesis_invalidation_and_monitoring || {},
    final_synthesis: finalMemo = report.final_synopsis?.paragraph || '',
  } = report;

  const currentPrice = hl?.current_price ?? 0;
  const dcfValue = hl?.dcf_value ?? 0;
  const dcfUpside = hl?.dcf_upside_percent ?? 0;
  const isPremium = dcfUpside < 0;

  // COMPLIANCE: Determine purely analytical valuation posture (Zero BUY/SELL)
  let posture = hl.valuation_posture;
  if (!posture || posture.includes('SELL') || posture.includes('BUY')) {
    if (dcfUpside <= -35.0) {
      posture = 'TRADING AT SIGNIFICANT PREMIUM TO DCF';
    } else if (dcfUpside < -10.0) {
      posture = 'TRADING AT PREMIUM TO DCF';
    } else if (dcfUpside <= 15.0) {
      posture = 'VALUED WITHIN DCF FAIR VALUE RANGE';
    } else if (dcfUpside <= 35.0) {
      posture = 'TRADING AT DISCOUNT TO DCF';
    } else {
      posture = 'TRADING AT SIGNIFICANT DISCOUNT TO DCF';
    }
  }

  // Fallback themes to ensure "Structural Driver" is NEVER repeated
  const defaultThemes = [
    'Top-Line Revenue Durability & Category Saturation',
    'Operating Margin Ceilings & Pass-Through Elasticity',
    'Capital Reinvestment & Return on Invested Capital',
    'Competitive Moat & Long-Term Market Positioning',
  ];

  const rawPillars = vp.structural_pillars || vp.thesis_points || [];
  const pillars = rawPillars.map((p, idx) => {
    if (typeof p === 'object' && p !== null) {
      const rawTheme = cleanText(p.theme || '');
      const isGeneric = !rawTheme || rawTheme.toLowerCase().includes('structural driver') || rawTheme.toLowerCase().includes('point');
      return {
        theme: isGeneric ? (defaultThemes[idx] || 'Valuation Mechanism') : rawTheme,
        analysis: cleanText(p.analysis || ''),
      };
    }
    const cleanStr = cleanText(String(p));
    const parts = cleanStr.split(/:\s*(.+)/);
    if (parts.length >= 2 && !parts[0].toLowerCase().includes('point') && !parts[0].toLowerCase().includes('structural driver')) {
      return { theme: cleanText(parts[0]), analysis: cleanText(parts[1]) };
    }
    return {
      theme: defaultThemes[idx] || 'Structural Valuation Driver',
      analysis: parts.length >= 2 ? cleanText(parts[1]) : cleanStr,
    };
  });

  // Explicit CSS class mappings — ZERO Tailwind `dark:` classes
  const C = isPaper
    ? {
        docBg: 'bg-[#ffffff]',
        docBorder: 'border-slate-300',
        textTitle: 'text-[#0a192f]',         // Deep navy black
        textHeading: 'text-[#0f172a]',       // Deep slate black
        textBody: 'text-[#1e293b]',          // Charcoal black
        textMuted: 'text-[#475569]',         // Medium slate grey
        textSubtle: 'text-[#64748b]',        // Subtle grey
        rule: 'border-slate-300',
        divider: 'border-slate-200',
        tableHeaderBg: 'bg-slate-100',
        tableHeaderText: 'text-[#0f172a]',
        tableCellBorder: 'border-slate-300',
        tableRowAlt: 'bg-slate-50/60',
        badgeBg: 'bg-slate-100',
        badgeBorder: 'border-slate-300',
        badgeText: 'text-[#0f172a]',
        accentText: 'text-[#1d4ed8]',        // Deep royal blue
        premiumText: 'text-[#b91c1c]',       // Deep crimson
        discountText: 'text-[#15803d]',      // Deep forest green
      }
    : {
        docBg: 'bg-[#0d121a]',
        docBorder: 'border-[#232d3d]',
        textTitle: 'text-[#ffffff]',
        textHeading: 'text-[#ffffff]',
        textBody: 'text-[#f4eedf]',          // Warm canvas cream
        textMuted: 'text-[#a6b0c3]',         // Crisp muted slate
        textSubtle: 'text-[#7e8b9f]',
        rule: 'border-[#263346]',
        divider: 'border-[#1e2736]',
        tableHeaderBg: 'bg-[#151c27]',
        tableHeaderText: 'text-[#f4eedf]',
        tableCellBorder: 'border-[#1e2736]',
        tableRowAlt: 'bg-[#101620]',
        badgeBg: 'bg-[#1a2332]',
        badgeBorder: 'border-[#2e3d54]',
        badgeText: 'text-[#f4eedf]',
        accentText: 'text-[#5b8fd9]',
        premiumText: 'text-[#e07a5f]',
        discountText: 'text-[#34b38a]',
      };

  return (
    <div className="w-full py-4 print:py-0 font-sans" id="ai-summary-content">
      {/* Top Document Toolbar */}
      <div className="max-w-4xl mx-auto mb-3 flex items-center justify-between px-1 text-xs text-slate-400">
        <span className="font-mono uppercase tracking-wider text-[11px]">
          Institutional Research Memorandum
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setTheme(isPaper ? 'dark' : 'paper')}
            className="flex items-center gap-1 px-3 py-1 rounded border border-slate-700 bg-slate-800 text-slate-200 hover:bg-slate-700 transition-colors cursor-pointer text-xs font-medium"
            title="Toggle between Paper Mode and Dark Mode"
          >
            {isPaper ? <FiMoon className="text-blue-400" /> : <FiSun className="text-amber-400" />}
            <span>{isPaper ? 'Switch to Dark Mode' : 'Switch to Paper Mode'}</span>
          </button>
          <button
            onClick={() => window.print()}
            className="flex items-center gap-1 px-3 py-1 rounded border border-slate-700 bg-slate-800 text-slate-200 hover:bg-slate-700 transition-colors cursor-pointer text-xs font-medium"
            title="Print or Export PDF"
          >
            <FiPrinter />
            <span>Print / PDF</span>
          </button>
        </div>
      </div>

      {/* Main Continuous Document Container — Pure Editorial Presentation (ZERO BOXES) */}
      <div
        className={`max-w-4xl mx-auto border shadow-xl p-6 sm:p-10 md:p-14 transition-colors ${C.docBg} ${C.docBorder}`}
      >
        {/* Document Masthead */}
        <div className={`border-b-2 ${C.rule} pb-5 mb-8`}>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs uppercase tracking-wider font-semibold mb-2">
            <div className={`flex items-center gap-2 ${C.textHeading}`}>
              <span className="font-bold tracking-widest">VALUATIONLABS RESEARCH</span>
              <span>•</span>
              <span className={C.textMuted}>EQUITY RESEARCH MEMORANDUM</span>
            </div>
            <div className={`font-mono text-[11px] ${C.textMuted}`}>
              <span>TICKER: {ticker}</span>
              <span className="mx-2">|</span>
              <span>CURRENCY: {currency || 'INR'}</span>
              <span className="mx-2">|</span>
              <span>VALUATION INITIATION</span>
            </div>
          </div>

          <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 mt-4">
            <div>
              <h1 className={`text-2xl sm:text-3xl font-bold tracking-tight ${C.textTitle}`}>
                {company || ticker}
              </h1>
              <p className={`text-xs sm:text-sm ${C.textMuted} mt-1.5 italic`}>
                Discounted Cash Flow & Reverse DCF Expectations Initiation Memorandum
              </p>
            </div>
            {/* Analytical Posture Badge (NO BUY / SELL) */}
            <div className="self-start md:self-end text-left md:text-right">
              <div className={`text-[10px] font-bold uppercase tracking-wider ${C.textSubtle} mb-1`}>
                Valuation Posture
              </div>
              <div
                className={`inline-block px-3 py-1 rounded font-bold text-xs tracking-wider uppercase border ${C.badgeBorder} ${C.badgeBg} ${C.badgeText}`}
              >
                {posture}
              </div>
            </div>
          </div>
        </div>

        {/* 1. Core Financial & Valuation Summary Schedule (Clean Wall Street Table) */}
        <div className="mb-10">
          <div className="overflow-x-auto">
            <table className={`w-full text-left text-xs sm:text-sm border-collapse border ${C.tableCellBorder}`}>
              <thead>
                <tr className={`${C.tableHeaderBg} border-b ${C.tableCellBorder} text-[11px] font-bold tracking-wider uppercase ${C.tableHeaderText}`}>
                  <th className={`p-2.5 sm:p-3 border-r ${C.tableCellBorder}`}>Current Price (P0)</th>
                  <th className={`p-2.5 sm:p-3 border-r ${C.tableCellBorder}`}>DCF Fair Value</th>
                  <th className={`p-2.5 sm:p-3 border-r ${C.tableCellBorder}`}>Valuation Spread</th>
                  <th className={`p-2.5 sm:p-3 border-r ${C.tableCellBorder}`}>MC Median (P50)</th>
                  <th className="p-2.5 sm:p-3">90% Confidence Corridor</th>
                </tr>
              </thead>
              <tbody className="divide-y font-mono text-xs sm:text-sm">
                <tr>
                  <td className={`p-2.5 sm:p-3 border-r ${C.tableCellBorder} font-bold ${C.textHeading}`}>
                    {formatNum(currentPrice, currency)}
                  </td>
                  <td className={`p-2.5 sm:p-3 border-r ${C.tableCellBorder} font-bold ${C.accentText}`}>
                    {formatNum(dcfValue, currency)}
                  </td>
                  <td className={`p-2.5 sm:p-3 border-r ${C.tableCellBorder} font-bold ${isPremium ? C.premiumText : C.discountText}`}>
                    {dcfUpside >= 0 ? '+' : ''}{formatPct(dcfUpside)} ({isPremium ? 'Premium' : 'Discount'})
                  </td>
                  <td className={`p-2.5 sm:p-3 border-r ${C.tableCellBorder} ${C.textBody}`}>
                    {formatNum(hl?.monte_carlo_median, currency)}
                  </td>
                  <td className={`p-2.5 sm:p-3 ${C.textBody}`}>
                    {formatNum(hl?.monte_carlo_p5, currency)} – {formatNum(hl?.monte_carlo_p95, currency)}
                  </td>
                </tr>
                <tr className={`${C.tableRowAlt} text-[11px] ${C.textSubtle}`}>
                  <td className={`p-2 border-r ${C.tableCellBorder}`}>Market Trading Level</td>
                  <td className={`p-2 border-r ${C.tableCellBorder}`}>5-Yr UFCF + Perpetual TV</td>
                  <td className={`p-2 border-r ${C.tableCellBorder}`}>Delta vs Intrinsic Baseline</td>
                  <td className={`p-2 border-r ${C.tableCellBorder}`}>10k Simulation Central Path</td>
                  <td className="p-2">P5 Downside Floor to P95 Ceiling</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* 2. Section I: Executive Summary & Valuation Synthesis (Continuous Prose — No Boxes) */}
        <section className="mb-10">
          <h2 className={`text-sm font-bold uppercase tracking-wider ${C.textHeading} pb-1.5 border-b ${C.rule} mb-4`}>
            I. Executive Summary & Valuation Synthesis
          </h2>
          <div className={`text-sm leading-relaxed ${C.textBody} space-y-4`}>
            <p className="text-justify">
              {exec.thesis_narrative || exec.overview || (
                `Discounted cash flow analysis establishes an implied intrinsic equity fair value of ${formatNum(dcfValue, currency)} per share for ${company || ticker}, comparing against current market trading levels of ${formatNum(currentPrice, currency)}. This establishes an implied valuation spread of ${formatPct(dcfUpside)}.`
              )}
            </p>

            {/* Dense Paragraph Dissections with Bold Leads */}
            {(exec.valuation_gap_analysis || exec.valuation_gap) && (
              <p className="text-justify">
                <span className={`font-bold ${C.textHeading}`}>Valuation Spread Dissection. </span>
                {exec.valuation_gap_analysis || exec.valuation_gap}
              </p>
            )}

            {(exec.core_value_engine || exec.primary_driver) && (
              <p className="text-justify">
                <span className={`font-bold ${C.textHeading}`}>Core Cash Flow Engine. </span>
                {exec.core_value_engine || exec.primary_driver}
              </p>
            )}

            {(exec.primary_downside_vulnerability || exec.primary_risk) && (
              <p className="text-justify">
                <span className={`font-bold ${C.textHeading}`}>Primary Downside Vulnerability. </span>
                {exec.primary_downside_vulnerability || exec.primary_risk}
              </p>
            )}
          </div>
        </section>

        {/* 3. Section II: Expectations Investing (Reverse DCF Analysis — Clean Financial Table) */}
        <section className="mb-10">
          <div className={`flex items-center justify-between pb-1.5 border-b ${C.rule} mb-4`}>
            <h2 className={`text-sm font-bold uppercase tracking-wider ${C.textHeading}`}>
              II. Expectations Investing: What Is Priced Into Today's Valuation?
            </h2>
            <span className={`text-xs font-mono font-bold uppercase ${C.textMuted}`}>
              {exp.hurdle_classification || exp.hurdle_verdict || 'Reverse DCF Hurdle'}
            </span>
          </div>

          <p className={`text-sm leading-relaxed ${C.textBody} mb-4 text-justify`}>
            Applying Michael Mauboussin's Expectations Investing methodology, Reverse DCF shifts the inquiry from calculating fair value to identifying the exact operational hurdles the company must satisfy to justify its current trading price of {formatNum(currentPrice, currency)}.
          </p>

          {/* Reverse DCF Comparative Table */}
          <div className="overflow-x-auto mb-4">
            <table className={`w-full text-left text-xs border-collapse border ${C.tableCellBorder}`}>
              <thead>
                <tr className={`${C.tableHeaderBg} border-b ${C.tableCellBorder} text-[11px] font-bold tracking-wider uppercase ${C.tableHeaderText}`}>
                  <th className={`p-2.5 border-r ${C.tableCellBorder}`}>Financial Variable</th>
                  <th className={`p-2.5 border-r ${C.tableCellBorder}`}>Model Fundamental Baseline</th>
                  <th className={`p-2.5 border-r ${C.tableCellBorder}`}>Market-Implied Hurdle (P0)</th>
                  <th className={`p-2.5 border-r ${C.tableCellBorder}`}>Expectations Hurdle Gap</th>
                  <th className="p-2.5">Feasibility Assessment</th>
                </tr>
              </thead>
              <tbody className="divide-y font-mono text-xs">
                <tr>
                  <td className={`p-2.5 border-r ${C.tableCellBorder} font-sans font-medium ${C.textHeading}`}>
                    5-Year Revenue Growth CAGR
                  </td>
                  <td className={`p-2.5 border-r ${C.tableCellBorder} ${C.textBody}`}>
                    {formatPct(exp.baseline_growth_cagr)}
                  </td>
                  <td className={`p-2.5 border-r ${C.tableCellBorder} font-bold ${C.accentText}`}>
                    {formatPct(exp.market_implied_growth_cagr)}
                  </td>
                  <td className={`p-2.5 border-r ${C.tableCellBorder} font-bold ${C.textHeading}`}>
                    {exp.growth_hurdle_gap_bps > 0 ? '+' : ''}{Number(exp.growth_hurdle_gap_bps || 0).toFixed(0)} bps
                  </td>
                  <td className={`p-2.5 font-sans ${C.textMuted} text-[11px]`}>
                    {exp.growth_hurdle_gap_bps > 1500 ? 'Demands unprecedented secular expansion' : 'Broadly aligned with historical capacity'}
                  </td>
                </tr>
                <tr>
                  <td className={`p-2.5 border-r ${C.tableCellBorder} font-sans font-medium ${C.textHeading}`}>
                    Operating Margin (EBIT / ROE)
                  </td>
                  <td className={`p-2.5 border-r ${C.tableCellBorder} ${C.textBody}`}>
                    {formatPct(dcfBridge.operating_margin_leverage?.forecast_margin || dcfBridge.margin?.forecast_margin)}
                  </td>
                  <td className={`p-2.5 border-r ${C.tableCellBorder} ${C.textBody}`}>
                    {exp.market_implied_margin || '—'}
                  </td>
                  <td className={`p-2.5 border-r ${C.tableCellBorder} ${C.textSubtle}`}>
                    {typeof exp.market_implied_margin === 'string' && exp.market_implied_margin.includes('Unachievable') ? 'N/A' : 'Margin shift'}
                  </td>
                  <td className={`p-2.5 font-sans ${C.textMuted} text-[11px]`}>
                    {typeof exp.market_implied_margin === 'string' && exp.market_implied_margin.includes('Unachievable')
                      ? 'Margin expansion alone cannot support current price'
                      : 'Requires sustained pricing power'}
                  </td>
                </tr>
                <tr>
                  <td className={`p-2.5 border-r ${C.tableCellBorder} font-sans font-medium ${C.textHeading}`}>
                    Discount Rate (WACC / Ke)
                  </td>
                  <td className={`p-2.5 border-r ${C.tableCellBorder} ${C.textBody}`}>
                    {formatPct(dcfBridge.cost_of_capital?.wacc || dcfBridge.wacc?.value)}
                  </td>
                  <td className={`p-2.5 border-r ${C.tableCellBorder} ${C.textBody}`}>
                    {exp.market_implied_wacc || '—'}
                  </td>
                  <td className={`p-2.5 border-r ${C.tableCellBorder} ${C.textSubtle}`}>
                    Cost of capital delta
                  </td>
                  <td className={`p-2.5 font-sans ${C.textMuted} text-[11px]`}>
                    Market treats cash flows with lower risk premium
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Plausibility Assessment Narrative — Pure Paragraph */}
          <p className={`text-sm leading-relaxed ${C.textBody} text-justify`}>
            <span className={`font-bold ${C.textHeading}`}>Expectations Plausibility Assessment. </span>
            {exp.plausibility_assessment || exp.plausibility_analysis || 'Reverse DCF reveals that prevailing valuations demand substantial operational acceleration beyond normalized delivery.'}
          </p>
        </section>

        {/* 4. Section III: Variant Perception (No Boxes — Pure Thematic Paragraphs) */}
        <section className="mb-10">
          <h2 className={`text-sm font-bold uppercase tracking-wider ${C.textHeading} pb-1.5 border-b ${C.rule} mb-4`}>
            III. Variant Perception: Where Our Thesis Diverges From Market Consensus
          </h2>
          
          <p className={`text-sm leading-relaxed ${C.textBody} text-justify mb-4`}>
            <span className={`font-bold ${C.textHeading}`}>
              {vp.divergence_headline || 'Core Disconnect Between Market Pricing and Operational Reality.'}{' '}
            </span>
            {vp.fundamental_reality || vp.summary || 'Market consensus appears anchored in aggressive growth assumptions that diverge from historical category maturity.'}
          </p>

          {/* Named Thematic Structural Pillars — Dense Editorial Paragraphs */}
          <div className="space-y-4">
            {pillars.map((pil, idx) => (
              <p key={idx} className={`text-sm leading-relaxed ${C.textBody} text-justify`}>
                <span className={`font-bold ${C.textHeading}`}>{pil.theme}. </span>
                {pil.analysis}
              </p>
            ))}
          </div>
        </section>

        {/* 5. Section IV: Business Architecture, Segments & Economic Moat (No Boxes) */}
        {moat && (moat.business_model || moat.competitive_moat) && (
          <section className="mb-10">
            <h2 className={`text-sm font-bold uppercase tracking-wider ${C.textHeading} pb-1.5 border-b ${C.rule} mb-4`}>
              IV. Business Architecture, Operating Segments & Economic Moat
            </h2>
            <div className={`text-sm leading-relaxed ${C.textBody} space-y-4`}>
              {moat.business_model && (
                <p className="text-justify">
                  <span className={`font-bold ${C.textHeading}`}>Commercial Architecture & Reporting Segments. </span>
                  {moat.business_model}
                </p>
              )}
              {moat.competitive_moat && (
                <p className="text-justify">
                  <span className={`font-bold ${C.textHeading}`}>Competitive Moat & Barriers to Entry. </span>
                  {moat.competitive_moat}
                </p>
              )}
              {moat.market_position_and_clients && (
                <p className="text-justify">
                  <span className={`font-bold ${C.textHeading}`}>Market Position & Customer Reach. </span>
                  {moat.market_position_and_clients}
                </p>
              )}
            </div>
          </section>
        )}

        {/* 6. Section V: DCF Cash Flow Mechanics & Value Bridge (No Boxes) */}
        <section className="mb-10">
          <h2 className={`text-sm font-bold uppercase tracking-wider ${C.textHeading} pb-1.5 border-b ${C.rule} mb-4`}>
            V. DCF Valuation Bridge & Cash Flow Schedule
          </h2>

          <div className={`text-sm leading-relaxed ${C.textBody} space-y-4`}>
            {(dcfBridge.revenue_trajectory?.analysis || dcfBridge.revenue_growth?.interpretation) && (
              <p className="text-justify">
                <span className={`font-bold ${C.textHeading}`}>
                  Top-Line Revenue Trajectory ({formatPct(dcfBridge.revenue_trajectory?.forecast_cagr || dcfBridge.revenue_growth?.forecast_cagr)} CAGR).{' '}
                </span>
                {dcfBridge.revenue_trajectory?.analysis || dcfBridge.revenue_growth?.interpretation}
              </p>
            )}

            {(dcfBridge.operating_margin_leverage?.analysis || dcfBridge.margin?.interpretation) && (
              <p className="text-justify">
                <span className={`font-bold ${C.textHeading}`}>
                  Operating Margin & Cost Leverage ({formatPct(dcfBridge.operating_margin_leverage?.forecast_margin || dcfBridge.margin?.forecast_margin)} Margin).{' '}
                </span>
                {dcfBridge.operating_margin_leverage?.analysis || dcfBridge.margin?.interpretation}
              </p>
            )}

            {(dcfBridge.reinvestment_dynamics?.fcf_conversion_analysis || dcfBridge.free_cash_flow?.interpretation) && (
              <p className="text-justify">
                <span className={`font-bold ${C.textHeading}`}>Reinvestment Demands (CapEx & Working Capital Float). </span>
                {dcfBridge.reinvestment_dynamics?.fcf_conversion_analysis || dcfBridge.free_cash_flow?.interpretation}
                {dcfBridge.reinvestment_dynamics?.capex_intensity && ` CapEx intensity averages ${dcfBridge.reinvestment_dynamics.capex_intensity}.`}
              </p>
            )}

            {(dcfBridge.cost_of_capital?.analysis || dcfBridge.wacc?.interpretation) && (
              <p className="text-justify">
                <span className={`font-bold ${C.textHeading}`}>
                  Cost of Capital & Discount Rate ({formatPct(dcfBridge.cost_of_capital?.wacc || dcfBridge.wacc?.value)} WACC).{' '}
                </span>
                {dcfBridge.cost_of_capital?.analysis || dcfBridge.wacc?.interpretation}
              </p>
            )}

            {(dcfBridge.terminal_value_mechanics?.analysis || dcfBridge.terminal_value?.interpretation) && (
              <p className="text-justify">
                <span className={`font-bold ${C.textHeading}`}>
                  Terminal Value & Multiple Cross-Check ({formatPct(dcfBridge.terminal_value_mechanics?.tv_share_of_ev || dcfBridge.terminal_value?.percent_of_enterprise_value)} of EV).{' '}
                </span>
                {dcfBridge.terminal_value_mechanics?.analysis || dcfBridge.terminal_value?.interpretation}
                {dcfBridge.terminal_value?.exit_multiple_cross_check && ` (${dcfBridge.terminal_value.exit_multiple_cross_check})`}
              </p>
            )}
          </div>
        </section>

        {/* 7. Section VI: Asymmetric Scenario Matrix (Clean Table) */}
        {scenarios && (
          <section className="mb-10">
            <h2 className={`text-sm font-bold uppercase tracking-wider ${C.textHeading} pb-1.5 border-b ${C.rule} mb-4`}>
              VI. Asymmetric Scenario Matrix
            </h2>
            <div className="overflow-x-auto">
              <table className={`w-full text-left text-xs border-collapse border ${C.tableCellBorder}`}>
                <thead>
                  <tr className={`${C.tableHeaderBg} border-b ${C.tableCellBorder} text-[11px] font-bold tracking-wider uppercase ${C.tableHeaderText}`}>
                    <th className={`p-2.5 border-r ${C.tableCellBorder}`}>Scenario</th>
                    <th className={`p-2.5 border-r ${C.tableCellBorder}`}>Intrinsic Value</th>
                    <th className={`p-2.5 border-r ${C.tableCellBorder}`}>Rev Growth</th>
                    <th className={`p-2.5 border-r ${C.tableCellBorder}`}>EBIT Margin</th>
                    <th className="p-2.5">Operational Catalysts & Assumptions</th>
                  </tr>
                </thead>
                <tbody className="divide-y text-xs">
                  {['bear', 'base', 'bull'].map((s) => {
                    const sc = scenarios[s];
                    if (!sc) return null;
                    const isBear = s === 'bear';
                    const isBull = s === 'bull';
                    return (
                      <tr key={s}>
                        <td className={`p-2.5 border-r ${C.tableCellBorder} font-bold uppercase font-mono ${C.textHeading}`}>
                          {s} Case ({isBear ? 'P5' : isBull ? 'P95' : 'Base'})
                        </td>
                        <td className={`p-2.5 border-r ${C.tableCellBorder} font-bold font-mono ${C.textHeading}`}>
                          {formatNum(sc.fair_value, currency)}
                        </td>
                        <td className={`p-2.5 border-r ${C.tableCellBorder} font-mono ${C.textBody}`}>
                          {sc.revenue_growth}
                        </td>
                        <td className={`p-2.5 border-r ${C.tableCellBorder} font-mono ${C.textBody}`}>
                          {sc.ebit_margin}
                        </td>
                        <td className={`p-2.5 ${C.textMuted} text-justify`}>
                          {sc.operational_catalysts || sc.catalyst}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* 8. Section VII: Downside Risks & Transmission Channels (Clean List — No Boxes) */}
        {risks && risks.length > 0 && (
          <section className="mb-10">
            <h2 className={`text-sm font-bold uppercase tracking-wider ${C.textHeading} pb-1.5 border-b ${C.rule} mb-4`}>
              VII. Downside Risks & Cash Flow Transmission Channels
            </h2>
            <div className={`text-sm leading-relaxed ${C.textBody} space-y-3.5`}>
              {risks.map((r, i) => (
                <div key={i} className="text-justify">
                  <span className={`font-bold text-xs uppercase tracking-wider mr-2 ${r.severity?.toLowerCase() === 'high' ? C.premiumText : C.textMuted}`}>
                    [{r.severity} Severity]
                  </span>
                  <span className={`font-bold ${C.textHeading}`}>{r.risk}. </span>
                  <span>{r.transmission_mechanism || r.mechanism} </span>
                  {(r.early_warning_indicator || r.indicator_to_monitor) && (
                    <span className={`italic ${C.textSubtle} text-xs`}>
                      (Monitoring Metric: {r.early_warning_indicator || r.indicator_to_monitor})
                    </span>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* 9. Section VIII: Quarterly Monitoring Milestones & Invalidation (Clean List — No Boxes) */}
        {monitoring && (monitoring.quarterly_kpis || monitoring.invalidation_triggers) && (
          <section className="mb-10">
            <h2 className={`text-sm font-bold uppercase tracking-wider ${C.textHeading} pb-1.5 border-b ${C.rule} mb-4`}>
              VIII. Quarterly Monitoring Milestones & Thesis Invalidation
            </h2>
            <div className={`text-sm leading-relaxed ${C.textBody} grid grid-cols-1 md:grid-cols-2 gap-6`}>
              {monitoring.quarterly_kpis && monitoring.quarterly_kpis.length > 0 && (
                <div>
                  <h3 className={`font-bold text-xs uppercase tracking-wider ${C.textHeading} mb-2`}>
                    Quarterly Operational KPIs to Track
                  </h3>
                  <ul className={`space-y-2 text-xs sm:text-sm ${C.textMuted} list-disc pl-4 text-justify`}>
                    {monitoring.quarterly_kpis.map((kpi, idx) => (
                      <li key={idx}>{cleanText(kpi)}</li>
                    ))}
                  </ul>
                </div>
              )}

              {monitoring.invalidation_triggers && monitoring.invalidation_triggers.length > 0 && (
                <div>
                  <h3 className={`font-bold text-xs uppercase tracking-wider ${C.textHeading} mb-2`}>
                    Thesis Invalidation Triggers (When to Revise)
                  </h3>
                  <ul className={`space-y-2 text-xs sm:text-sm ${C.textMuted} list-disc pl-4 text-justify`}>
                    {monitoring.invalidation_triggers.map((trig, idx) => (
                      <li key={idx}>{cleanText(trig)}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </section>
        )}

        {/* 10. Closing Synthesis Memorandum */}
        {finalMemo && (
          <section className={`mb-10 pt-4 border-t ${C.divider}`}>
            <h2 className={`text-xs font-bold uppercase tracking-wider ${C.textHeading} mb-2`}>
              Valuation Synthesis & Strategic Posture
            </h2>
            <p className={`text-sm ${C.textBody} leading-relaxed text-justify italic`}>
              "{finalMemo}"
            </p>
          </section>
        )}

        {/* 11. Mandatory Regulatory Compliance Disclaimer */}
        <div className={`pt-6 border-t ${C.rule} text-[10px] ${C.textSubtle} leading-relaxed text-justify font-mono`}>
          <p className={`font-bold ${C.textMuted} uppercase mb-1`}>
            REGULATORY COMPLIANCE & LEGAL DISCLAIMERS
          </p>
          <p>
            ValuationLabs Research is an automated quantitative financial modeling software platform. ValuationLabs is not a registered investment advisor, broker-dealer, or portfolio manager under SEBI, SEC, or any financial regulatory authority. This memorandum is generated automatically based on mathematical discounted cash flow formulas and public financial reporting data for informational, analytical, and academic purposes only. Under no circumstances should this document be construed as investment advice, financial promotion, or a recommendation, offer, or solicitation to buy, sell, or hold any security. Historical financial performance is not indicative of future results.
          </p>
        </div>
      </div>
    </div>
  );
}
