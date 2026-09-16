import React from 'react';
import { FiArrowRight } from 'react-icons/fi';

const DCFModelTab = ({ data }) => {
  if (!data || !data.dcf_result) return null;

  const { company, dcf_result, wacc } = data;
  const symbol = company?.symbol || '$';
  const market = company?.market || 'US';

  const formatNum = (val, curSymbol = symbol, curMarket = market) => {
    if (val === undefined || val === null || isNaN(val)) return '-';
    
    let formattedVal = '';
    
    if (curMarket === 'IN') {
      if (Math.abs(val) >= 1e7) {
        formattedVal = (val / 1e7).toFixed(2) + 'Cr';
      } else if (Math.abs(val) >= 1e5) {
        formattedVal = (val / 1e5).toFixed(2) + 'L';
      } else {
        formattedVal = new Intl.NumberFormat('en-IN').format(val);
      }
    } else {
      if (Math.abs(val) >= 1e9) {
        formattedVal = (val / 1e9).toFixed(2) + 'B';
      } else if (Math.abs(val) >= 1e6) {
        formattedVal = (val / 1e6).toFixed(2) + 'M';
      } else if (Math.abs(val) >= 1e3) {
        formattedVal = (val / 1e3).toFixed(2) + 'K';
      } else {
        formattedVal = new Intl.NumberFormat('en-US').format(val);
      }
    }
    
    return `${curSymbol}${formattedVal}`;
  };

  const formatPct = (val) => {
    if (val === undefined || val === null || isNaN(val)) return '-';
    return (val * 100).toFixed(1) + '%';
  };

  const projectionYears = dcf_result.projected_revenue?.length || 0;
  const cash = wacc?.total_cash ?? company?.total_cash ?? company?.cash;
  
  return (
    <div className="space-y-6">
      {/* Projected Financials Table */}
      <div className="bg-navy-700 rounded-xl p-5 shadow-lg border border-navy-600">
        <div className="mb-4">
          <h2 className="text-xl font-semibold text-slate-100">Projected Financials</h2>
          <p className="text-sm text-slate-400">{projectionYears}-Year Projection</p>
        </div>
        
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="bg-navy-800 text-slate-400 uppercase text-xs tracking-wider">
              <tr>
                <th className="px-4 py-3 font-medium rounded-tl-lg sticky left-0 bg-navy-800 z-10">Metric</th>
                {Array.from({ length: projectionYears }).map((_, i) => (
                  <th key={i} className="px-4 py-3 font-medium text-right min-w-[100px]">
                    Year {i + 1}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-navy-600 border-b border-navy-600">
              {/* Revenue */}
              <tr className="bg-navy-700 hover:bg-navy-600/50 transition-colors">
                <td className="px-4 py-3 font-medium text-slate-200 sticky left-0 bg-navy-700 z-10 border-r border-navy-600/30">
                  Revenue
                </td>
                {dcf_result.projected_revenue?.map((val, i) => (
                  <td key={i} className="px-4 py-3 text-right font-mono text-slate-300">
                    {formatNum(val)}
                  </td>
                ))}
              </tr>
              {/* Growth Rate */}
              <tr className="bg-navy-800/50 hover:bg-navy-700 transition-colors">
                <td className="px-4 py-3 font-medium text-slate-200 sticky left-0 bg-navy-800/50 z-10 border-r border-navy-600/30">
                  Growth Rate
                </td>
                {dcf_result.growth_schedule?.map((val, i) => (
                  <td key={i} className="px-4 py-3 text-right font-mono text-slate-300">
                    {formatPct(val)}
                  </td>
                ))}
              </tr>
              {/* UFCF */}
              <tr className="bg-navy-700 hover:bg-navy-600/50 transition-colors">
                <td className="px-4 py-3 font-medium text-slate-200 sticky left-0 bg-navy-700 z-10 border-r border-navy-600/30">
                  UFCF
                </td>
                {dcf_result.projected_ufcf?.map((val, i) => (
                  <td key={i} className="px-4 py-3 text-right font-mono text-slate-300">
                    {formatNum(val)}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Terminal Value Section */}
      <div className="bg-navy-700 rounded-xl p-5 shadow-lg border border-navy-600 mt-4">
        <h2 className="text-xl font-semibold text-slate-100 mb-4">Terminal Value</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-navy-800 rounded-lg p-4 border border-navy-600/50">
            <p className="text-slate-400 text-sm mb-1">Terminal Value</p>
            <p className="text-xl font-semibold text-slate-100 font-mono">
              {formatNum(dcf_result.terminal_value)}
            </p>
          </div>
          <div className="bg-navy-800 rounded-lg p-4 border border-navy-600/50">
            <p className="text-slate-400 text-sm mb-1">Enterprise Value</p>
            <p className="text-xl font-semibold text-slate-100 font-mono">
              {formatNum(dcf_result.enterprise_value)}
            </p>
          </div>
        </div>
      </div>

      {/* Equity Bridge Section */}
      <div className="bg-navy-700 rounded-xl p-5 shadow-lg border border-navy-600 mt-4">
        <h2 className="text-xl font-semibold text-slate-100 mb-4">Equity Bridge</h2>
        
        <div className="flex flex-col md:flex-row items-center justify-between gap-4 overflow-x-auto pb-2">
          {/* Enterprise Value */}
          <div className="flex-1 min-w-[140px] bg-navy-800 rounded-lg p-4 text-center border border-navy-600/50">
            <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">Enterprise Value</p>
            <p className="text-lg font-semibold text-slate-100 font-mono">
              {formatNum(dcf_result.enterprise_value)}
            </p>
          </div>
          
          <div className="text-slate-500 hidden md:block"><FiArrowRight size={20} /></div>
          <div className="text-slate-500 md:hidden rotate-90"><FiArrowRight size={20} /></div>
          
          {/* Less Debt */}
          <div className="flex-1 min-w-[140px] bg-navy-800 rounded-lg p-4 text-center border border-navy-600/50">
            <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">Total Debt</p>
            <p className="text-lg font-semibold text-accent-red font-mono">
              - {formatNum(wacc?.total_debt)}
            </p>
          </div>
          
          {cash !== undefined && (
            <>
              <div className="text-slate-500 hidden md:block"><FiArrowRight size={20} /></div>
              <div className="text-slate-500 md:hidden rotate-90"><FiArrowRight size={20} /></div>
              
              {/* Plus Cash */}
              <div className="flex-1 min-w-[140px] bg-navy-800 rounded-lg p-4 text-center border border-navy-600/50">
                <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">Cash</p>
                <p className="text-lg font-semibold text-accent-green font-mono">
                  + {formatNum(cash)}
                </p>
              </div>
            </>
          )}

          <div className="text-slate-500 hidden md:block"><FiArrowRight size={20} /></div>
          <div className="text-slate-500 md:hidden rotate-90"><FiArrowRight size={20} /></div>
          
          {/* Equity Value */}
          <div className="flex-1 min-w-[140px] bg-navy-800 rounded-lg p-4 text-center border border-navy-600/50">
            <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">Equity Value</p>
            <p className="text-lg font-semibold text-slate-100 font-mono">
              {formatNum(dcf_result.equity_value)}
            </p>
          </div>

          <div className="text-slate-500 hidden md:block"><FiArrowRight size={20} /></div>
          <div className="text-slate-500 md:hidden rotate-90"><FiArrowRight size={20} /></div>
          
          {/* Implied Price */}
          <div className="flex-1 min-w-[140px] bg-accent-blue/10 rounded-lg p-4 text-center border border-accent-blue/30 shadow-[0_0_15px_rgba(59,130,246,0.15)]">
            <p className="text-accent-blue/80 text-xs uppercase tracking-wider mb-1 font-semibold">Implied Price</p>
            <p className="text-2xl font-bold text-white font-mono">
              {formatNum(dcf_result.implied_price)}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DCFModelTab;
