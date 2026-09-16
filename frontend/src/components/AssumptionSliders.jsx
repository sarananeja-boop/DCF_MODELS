import React, { useState, useEffect } from 'react';
import { FiRefreshCw } from 'react-icons/fi';

export default function AssumptionSliders({ data, onOverride, loading }) {
  if (!data) return null;

  const defaultGrowth = data.historicals.revenue_cagr || data.historicals.avg_rev_growth || 0.10;
  const defaultMargin = data.historicals.avg_ebit_margin || 0.20;
  const defaultWacc = data.wacc.wacc;

  const [growth, setGrowth] = useState(defaultGrowth * 100);
  const [margin, setMargin] = useState(defaultMargin * 100);
  const [wacc, setWacc] = useState(defaultWacc * 100);
  const [tgr, setTgr] = useState(2.5);
  
  const [isModified, setIsModified] = useState(false);

  useEffect(() => {
    // Reset when data changes natively (new ticker)
    setGrowth(defaultGrowth * 100);
    setMargin(defaultMargin * 100);
    setWacc(defaultWacc * 100);
    setTgr(2.5);
    setIsModified(false);
  }, [data.company.ticker]);

  const handleApply = () => {
    onOverride({
      revenue_growth: growth / 100,
      ebit_margin: margin / 100,
      wacc: wacc / 100,
      terminal_growth: tgr / 100,
      projection_years: 5
    });
    setIsModified(false);
  };

  const handleReset = () => {
    setGrowth(defaultGrowth * 100);
    setMargin(defaultMargin * 100);
    setWacc(defaultWacc * 100);
    setTgr(2.5);
    setIsModified(true); // show the re-run button
  };

  const wrapChange = (setter) => (e) => {
    setter(parseFloat(e.target.value));
    setIsModified(true);
  };

  return (
    <div className="bg-zinc-900/40 rounded-xl p-6 border border-zinc-800/80 mb-6 shadow-xl backdrop-blur-sm">
      <div className="flex justify-between items-center mb-8 border-b border-zinc-800/50 pb-4">
        <h3 className="font-semibold text-zinc-100 text-lg tracking-tight">Assumptions</h3>
        <button 
          onClick={handleReset}
          className="text-xs text-zinc-400 hover:text-zinc-100 transition-colors uppercase tracking-wider font-medium"
        >
          Reset
        </button>
      </div>

      <div className="space-y-8">
        {/* Revenue Growth */}
        <div className="group">
          <div className="flex justify-between items-center text-sm mb-3">
            <label className="text-zinc-400 group-hover:text-zinc-300 transition-colors font-medium">Rev Growth (Yr 1)</label>
            <div className="flex items-center gap-1 bg-zinc-950/60 px-3 py-1.5 rounded-md border border-zinc-800 focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500/30 transition-all">
              <input 
                type="number" 
                value={growth.toFixed(1)} 
                onChange={wrapChange(setGrowth)}
                className="bg-transparent text-right w-14 text-zinc-100 font-mono tabular-nums text-sm focus:outline-none"
              />
              <span className="text-zinc-500 text-xs font-mono">%</span>
            </div>
          </div>
          <input 
            type="range" min="-10" max="40" step="0.5" 
            value={growth} onChange={wrapChange(setGrowth)}
            className="w-full h-1.5 bg-zinc-800/80 rounded-lg appearance-none cursor-pointer accent-blue-500 hover:accent-blue-400" 
          />
          <div className="text-[11px] text-zinc-600 text-right mt-2 font-mono">Default: {(defaultGrowth*100).toFixed(1)}%</div>
        </div>

        {/* EBIT Margin */}
        <div className="group">
          <div className="flex justify-between items-center text-sm mb-3">
            <label className="text-zinc-400 group-hover:text-zinc-300 transition-colors font-medium">EBIT Margin</label>
            <div className="flex items-center gap-1 bg-zinc-950/60 px-3 py-1.5 rounded-md border border-zinc-800 focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500/30 transition-all">
              <input 
                type="number" 
                value={margin.toFixed(1)} 
                onChange={wrapChange(setMargin)}
                className="bg-transparent text-right w-14 text-zinc-100 font-mono tabular-nums text-sm focus:outline-none"
              />
              <span className="text-zinc-500 text-xs font-mono">%</span>
            </div>
          </div>
          <input 
            type="range" min="0" max="60" step="0.5" 
            value={margin} onChange={wrapChange(setMargin)}
            className="w-full h-1.5 bg-zinc-800/80 rounded-lg appearance-none cursor-pointer accent-blue-500 hover:accent-blue-400" 
          />
          <div className="text-[11px] text-zinc-600 text-right mt-2 font-mono">Default: {(defaultMargin*100).toFixed(1)}%</div>
        </div>

        {/* WACC */}
        <div className="group">
          <div className="flex justify-between items-center text-sm mb-3">
            <label className="text-zinc-400 group-hover:text-zinc-300 transition-colors font-medium">Discount Rate (WACC)</label>
            <div className="flex items-center gap-1 bg-zinc-950/60 px-3 py-1.5 rounded-md border border-zinc-800 focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500/30 transition-all">
              <input 
                type="number" 
                value={wacc.toFixed(1)} 
                onChange={wrapChange(setWacc)}
                className="bg-transparent text-right w-14 text-zinc-100 font-mono tabular-nums text-sm focus:outline-none"
              />
              <span className="text-zinc-500 text-xs font-mono">%</span>
            </div>
          </div>
          <input 
            type="range" min="5" max="25" step="0.1" 
            value={wacc} onChange={wrapChange(setWacc)}
            className="w-full h-1.5 bg-zinc-800/80 rounded-lg appearance-none cursor-pointer accent-blue-500 hover:accent-blue-400" 
          />
          <div className="text-[11px] text-zinc-600 text-right mt-2 font-mono">Computed: {(defaultWacc*100).toFixed(1)}%</div>
        </div>
        
        {/* Terminal Growth */}
        <div className="group">
          <div className="flex justify-between items-center text-sm mb-3">
            <label className="text-zinc-400 group-hover:text-zinc-300 transition-colors font-medium">Term. Growth</label>
            <div className="flex items-center gap-1 bg-zinc-950/60 px-3 py-1.5 rounded-md border border-zinc-800 focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500/30 transition-all">
              <input 
                type="number" 
                value={tgr.toFixed(1)} 
                onChange={wrapChange(setTgr)}
                className="bg-transparent text-right w-14 text-zinc-100 font-mono tabular-nums text-sm focus:outline-none"
              />
              <span className="text-zinc-500 text-xs font-mono">%</span>
            </div>
          </div>
          <input 
            type="range" min="1" max="5" step="0.1" 
            value={tgr} onChange={wrapChange(setTgr)}
            className="w-full h-1.5 bg-zinc-800/80 rounded-lg appearance-none cursor-pointer accent-blue-500 hover:accent-blue-400" 
          />
        </div>

        {isModified && (
          <button 
            onClick={handleApply}
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 py-3 mt-8 bg-zinc-100 hover:bg-zinc-200 text-zinc-950 font-semibold rounded-lg transition shadow-lg shadow-zinc-100/10"
          >
            <FiRefreshCw className={loading ? 'animate-spin' : ''} />
            Re-run Analysis
          </button>
        )}
      </div>
    </div>
  );
}
