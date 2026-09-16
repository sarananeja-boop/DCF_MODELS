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
    <div className="bg-navy-800 rounded-lg p-4 border border-navy-600 mb-6 shadow-lg">
      <div className="flex justify-between items-center mb-4">
        <h3 className="font-semibold text-white">Assumptions</h3>
        <button 
          onClick={handleReset}
          className="text-xs text-text-secondary hover:text-white transition"
        >
          Reset
        </button>
      </div>

      <div className="space-y-6">
        {/* Revenue Growth */}
        <div>
          <div className="flex justify-between text-sm mb-1">
            <span className="text-text-secondary">Rev Growth (Yr 1)</span>
            <span className="font-mono text-accent-blue">{growth.toFixed(1)}%</span>
          </div>
          <input 
            type="range" min="-10" max="40" step="0.5" 
            value={growth} onChange={wrapChange(setGrowth)}
            className="w-full accent-accent-blue" 
          />
          <div className="text-[10px] text-gray-500 text-right mt-1">Default: {(defaultGrowth*100).toFixed(1)}%</div>
        </div>

        {/* EBIT Margin */}
        <div>
          <div className="flex justify-between text-sm mb-1">
            <span className="text-text-secondary">EBIT Margin</span>
            <span className="font-mono text-accent-blue">{margin.toFixed(1)}%</span>
          </div>
          <input 
            type="range" min="0" max="60" step="0.5" 
            value={margin} onChange={wrapChange(setMargin)}
            className="w-full accent-accent-blue" 
          />
          <div className="text-[10px] text-gray-500 text-right mt-1">Default: {(defaultMargin*100).toFixed(1)}%</div>
        </div>

        {/* WACC */}
        <div>
          <div className="flex justify-between text-sm mb-1">
            <span className="text-text-secondary">WACC</span>
            <span className="font-mono text-accent-blue">{wacc.toFixed(1)}%</span>
          </div>
          <input 
            type="range" min="5" max="25" step="0.1" 
            value={wacc} onChange={wrapChange(setWacc)}
            className="w-full accent-accent-blue" 
          />
          <div className="text-[10px] text-gray-500 text-right mt-1">Computed: {(defaultWacc*100).toFixed(1)}%</div>
        </div>
        
        {/* Terminal Growth */}
        <div>
          <div className="flex justify-between text-sm mb-1">
            <span className="text-text-secondary">Term. Growth Rate</span>
            <span className="font-mono text-accent-blue">{tgr.toFixed(1)}%</span>
          </div>
          <input 
            type="range" min="1" max="5" step="0.1" 
            value={tgr} onChange={wrapChange(setTgr)}
            className="w-full accent-accent-blue" 
          />
        </div>

        {isModified && (
          <button 
            onClick={handleApply}
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 py-2 mt-2 bg-navy-600 hover:bg-navy-700 text-white text-sm rounded-md transition border border-accent-blue/50"
          >
            <FiRefreshCw className={loading ? 'animate-spin' : ''} />
            Re-run Analysis
          </button>
        )}
      </div>
    </div>
  );
}
