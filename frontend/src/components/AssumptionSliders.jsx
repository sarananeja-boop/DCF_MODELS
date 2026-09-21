import React, { useState, useEffect } from 'react';
import { FiRefreshCw } from 'react-icons/fi';

export default function AssumptionSliders({ data, onOverride, loading }) {
  if (!data) return null;

  const isFinancial = Boolean(data.company?.is_financial || data.diagnostics?.is_financial);

  const defaultGrowth = isFinancial
    ? (data.historicals.avg_ni_growth || data.historicals.avg_rev_growth || 0.10)
    : (data.historicals.revenue_cagr || data.historicals.avg_rev_growth || 0.10);
  
  const currentMargin = isFinancial
    ? (data.diagnostics?.current_ebit_margin ?? data.historicals.avg_roe ?? 0.14)
    : (data.diagnostics?.current_ebit_margin ?? data.historicals.avg_ebit_margin);
  const isNegativeMargin = !isFinancial && currentMargin < 0;
  
  // Always use the true historical baseline as default (never the applied override)
  const defaultMargin = isFinancial
    ? (data.historicals.avg_roe ?? 0.14)
    : (data.historicals.avg_ebit_margin ?? 0.20);
  
  const defaultWacc = isFinancial
    ? (data.wacc.cost_of_equity || data.wacc.wacc || 0.10)
    : data.wacc.wacc;

  const defaultTgr = (data.macro?.terminal_growth ?? (data.company?.market === 'IN' ? 0.055 : 0.025)) * 100;
  const isIndia = data.company?.market === 'IN';
  const maxTgr = isIndia ? 8.0 : 5.0;

  // Initialize with applied override if present, else true default
  const [growth, setGrowth] = useState(() => (data.overrides_applied?.revenue_growth != null ? data.overrides_applied.revenue_growth * 100 : defaultGrowth * 100));
  const [margin, setMargin] = useState(() => (data.overrides_applied?.ebit_margin != null ? data.overrides_applied.ebit_margin * 100 : defaultMargin * 100));
  const [wacc, setWacc] = useState(() => (data.overrides_applied?.wacc != null ? data.overrides_applied.wacc * 100 : defaultWacc * 100));
  const [tgr, setTgr] = useState(() => (data.overrides_applied?.terminal_growth != null ? data.overrides_applied.terminal_growth * 100 : defaultTgr));

  useEffect(() => {
    // Reset local slider state when a new ticker is loaded
    const g = data.overrides_applied?.revenue_growth != null ? data.overrides_applied.revenue_growth * 100 : defaultGrowth * 100;
    const m = data.overrides_applied?.ebit_margin != null ? data.overrides_applied.ebit_margin * 100 : defaultMargin * 100;
    const w = data.overrides_applied?.wacc != null ? data.overrides_applied.wacc * 100 : defaultWacc * 100;
    const t = data.overrides_applied?.terminal_growth != null ? data.overrides_applied.terminal_growth * 100 : defaultTgr;
    setGrowth(g);
    setMargin(m);
    setWacc(w);
    setTgr(t);
  }, [data.company?.ticker, defaultTgr]);

  // Handlers that update local slider state AND notify parent only on user action
  const handleGrowthChange = (val) => {
    setGrowth(val);
    onOverride({
      revenue_growth: val / 100,
      ebit_margin: margin / 100,
      wacc: wacc / 100,
      terminal_growth: tgr / 100,
      projection_years: 5
    });
  };

  const handleMarginChange = (val) => {
    setMargin(val);
    onOverride({
      revenue_growth: growth / 100,
      ebit_margin: val / 100,
      wacc: wacc / 100,
      terminal_growth: tgr / 100,
      projection_years: 5
    });
  };

  const handleWaccChange = (val) => {
    setWacc(val);
    onOverride({
      revenue_growth: growth / 100,
      ebit_margin: margin / 100,
      wacc: val / 100,
      terminal_growth: tgr / 100,
      projection_years: 5
    });
  };

  const handleTgrChange = (val) => {
    setTgr(val);
    onOverride({
      revenue_growth: growth / 100,
      ebit_margin: margin / 100,
      wacc: wacc / 100,
      terminal_growth: val / 100,
      projection_years: 5
    });
  };

  return (
    <div className="bg-zinc-900/40 rounded-xl p-6 border border-zinc-800/80 mb-6 shadow-xl backdrop-blur-sm">
      <div className="flex justify-between items-center mb-8 border-b border-zinc-800/50 pb-4">
        <div>
          <h3 className="font-semibold text-zinc-100 text-lg tracking-tight">Assumptions</h3>
          {isFinancial && (
            <span className="text-xs font-mono text-emerald-400 bg-emerald-950/40 border border-emerald-500/30 px-2 py-0.5 rounded mt-1 inline-block">
              Banking & Financial Services (FCFE / DDM Model)
            </span>
          )}
        </div>
      </div>

      <div className="space-y-8">
        {/* Growth Slider */}
        <div className="group">
          <div className="flex justify-between items-center text-sm mb-3">
            <label className="text-zinc-400 group-hover:text-zinc-300 transition-colors font-medium">
              {isFinancial ? 'Net Income Growth (Yr 1)' : 'Rev Growth (Yr 1)'}
            </label>
            <div className="flex items-center gap-1 bg-zinc-950/60 px-3 py-1.5 rounded-md border border-zinc-800 focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500/30 transition-all">
              <input 
                type="number" 
                value={growth.toFixed(1)} 
                onChange={(e) => handleGrowthChange(parseFloat(e.target.value) || 0)}
                className="bg-transparent text-right w-14 text-zinc-100 font-mono tabular-nums text-sm focus:outline-none"
              />
              <span className="text-zinc-500 text-xs font-mono">%</span>
            </div>
          </div>
          <input 
            type="range" min="-10" max="40" step="0.5" 
            value={growth} onChange={(e) => handleGrowthChange(parseFloat(e.target.value))}
            className="w-full h-1.5 bg-zinc-800/80 rounded-lg appearance-none cursor-pointer accent-blue-500 hover:accent-blue-400" 
          />
          <div className="text-[11px] text-zinc-600 text-right mt-2 font-mono">Default: {(defaultGrowth*100).toFixed(1)}%</div>
        </div>

        {/* Profitability / ROE Slider */}
        <div className="group">
          <div className="flex justify-between items-center text-sm mb-3">
            <label className="text-zinc-400 group-hover:text-zinc-300 transition-colors font-medium">
              {isFinancial 
                ? 'Target Return on Equity (ROE)' 
                : (isNegativeMargin ? 'Target EBIT Margin' : 'EBIT Margin')}
            </label>
            <div className="flex items-center gap-1 bg-zinc-950/60 px-3 py-1.5 rounded-md border border-zinc-800 focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500/30 transition-all">
              <input 
                type="number" 
                value={margin.toFixed(1)} 
                onChange={(e) => handleMarginChange(parseFloat(e.target.value) || 0)}
                className="bg-transparent text-right w-14 text-zinc-100 font-mono tabular-nums text-sm focus:outline-none"
              />
              <span className="text-zinc-500 text-xs font-mono">%</span>
            </div>
          </div>
          <input 
            type="range" 
            min={isFinancial ? "5" : "-60"} 
            max={isFinancial ? "35" : "60"} 
            step="0.5" 
            value={margin} onChange={(e) => handleMarginChange(parseFloat(e.target.value))}
            className="w-full h-1.5 bg-zinc-800/80 rounded-lg appearance-none cursor-pointer accent-blue-500 hover:accent-blue-400" 
          />
          <div className="text-[11px] text-zinc-600 text-right mt-2 font-mono flex justify-between">
            <span>{isNegativeMargin ? `Current EBIT Margin: ${(currentMargin*100).toFixed(1)}%` : ''}</span>
            <span>Default: {(defaultMargin*100).toFixed(1)}%</span>
          </div>
        </div>

        {/* Discount Rate (WACC vs Ke) */}
        <div className="group">
          <div className="flex justify-between items-center text-sm mb-3">
            <label className="text-zinc-400 group-hover:text-zinc-300 transition-colors font-medium">
              {isFinancial ? 'Discount Rate (Cost of Equity Ke)' : 'Discount Rate (WACC)'}
            </label>
            <div className="flex items-center gap-1 bg-zinc-950/60 px-3 py-1.5 rounded-md border border-zinc-800 focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500/30 transition-all">
              <input 
                type="number" 
                value={wacc.toFixed(1)} 
                onChange={(e) => handleWaccChange(parseFloat(e.target.value) || 0)}
                className="bg-transparent text-right w-14 text-zinc-100 font-mono tabular-nums text-sm focus:outline-none"
              />
              <span className="text-zinc-500 text-xs font-mono">%</span>
            </div>
          </div>
          <input 
            type="range" min="5" max="25" step="0.1" 
            value={wacc} onChange={(e) => handleWaccChange(parseFloat(e.target.value))}
            className="w-full h-1.5 bg-zinc-800/80 rounded-lg appearance-none cursor-pointer accent-blue-500 hover:accent-blue-400" 
          />
          <div className="text-[11px] text-zinc-600 mt-2 font-mono flex flex-col gap-1">
            <div className="flex justify-between">
              <span>Computed: {(defaultWacc*100).toFixed(1)}%</span>
              {data.market_data?.beta && (
                <span>Beta: {data.market_data.beta.toFixed(2)}</span>
              )}
            </div>
            {data.diagnostics?.ke_floored && (
              <span className="text-amber-400/90 text-[10px] bg-amber-950/40 p-1 rounded border border-amber-500/20">
                {data.diagnostics.ke_note}
              </span>
            )}
            {data.diagnostics?.beta_clamped && (
              <span className="text-blue-400/90 text-[10px] bg-blue-950/40 p-1 rounded border border-blue-500/20">
                {data.diagnostics.beta_note}
              </span>
            )}
          </div>
        </div>
        
        {/* Terminal Growth */}
        <div className="group">
          <div className="flex justify-between items-center text-sm mb-3">
            <label className="text-zinc-400 group-hover:text-zinc-300 transition-colors font-medium">Term. Growth</label>
            <div className="flex items-center gap-1 bg-zinc-950/60 px-3 py-1.5 rounded-md border border-zinc-800 focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500/30 transition-all">
              <input 
                type="number" 
                value={tgr.toFixed(1)} 
                onChange={(e) => handleTgrChange(parseFloat(e.target.value) || 0)}
                className="bg-transparent text-right w-14 text-zinc-100 font-mono tabular-nums text-sm focus:outline-none"
              />
              <span className="text-zinc-500 text-xs font-mono">%</span>
            </div>
          </div>
          <input 
            type="range" min="1" max={maxTgr} step="0.1" 
            value={tgr} onChange={(e) => handleTgrChange(parseFloat(e.target.value))}
            className="w-full h-1.5 bg-zinc-800/80 rounded-lg appearance-none cursor-pointer accent-blue-500 hover:accent-blue-400" 
          />
          <div className="text-[11px] text-zinc-600 mt-2 font-mono flex flex-col gap-1">
            <div className="text-right">Default: {defaultTgr.toFixed(1)}%</div>
            {data.diagnostics?.terminal_growth_capped && (
              <span className="text-amber-400/90 text-[10px] bg-amber-950/40 p-1 rounded border border-amber-500/20">
                {data.diagnostics.terminal_value_note}
              </span>
            )}
          </div>
        </div>

        {/* NWC Ratio Display */}
        {data.diagnostics?.normalized_nwc_to_revenue !== undefined && (
          <div className="flex justify-between items-center text-sm pt-4 border-t border-zinc-800/50">
            <span className="text-zinc-500 font-medium">Normalized NWC / Revenue</span>
            <span className="text-zinc-300 font-mono">
              {(data.diagnostics.normalized_nwc_to_revenue * 100).toFixed(1)}%
            </span>
          </div>
        )}

      </div>
    </div>
  );
}
