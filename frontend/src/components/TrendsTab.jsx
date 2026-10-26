import React from 'react';
import Plot from 'react-plotly.js';

export default function TrendsTab({ data }) {
  if (!data || !data.trends) return null;

  const { trends } = data;
  const sym = data.company.symbol;

  const layoutConfig = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#a6b0c3', family: 'Plus Jakarta Sans, sans-serif' },
    margin: { t: 20, r: 20, l: 60, b: 40 },
    height: 270,
    autosize: true,
    xaxis: { 
      gridcolor: 'rgba(244,238,223,0.08)', 
      dtick: 1, 
      tickfont: { color: '#a6b0c3' } 
    },
    yaxis: { 
      gridcolor: 'rgba(244,238,223,0.08)', 
      tickfont: { color: '#a6b0c3' } 
    }
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-[#f4eedf]">
      {/* Revenue History */}
      <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg">
        <div className="flex justify-between items-center mb-2">
          <h3 className="font-display text-base font-bold text-[#f4eedf]">Revenue History (4-Yr)</h3>
          <span className="text-xs bg-[#5b8fd9]/15 text-[#8ab4f8] border border-[#5b8fd9]/30 px-2.5 py-1 rounded-lg font-display font-bold tabular-nums">
            CAGR: {(trends.revenue_cagr * 100).toFixed(1)}%
          </span>
        </div>
        <Plot
          data={[{
            x: trends.revenue_history.map(d => d.year),
            y: trends.revenue_history.map(d => d.value),
            type: 'bar',
            marker: { color: '#5b8fd9' }
          }]}
          layout={{
            ...layoutConfig,
            yaxis: { ...layoutConfig.yaxis, tickprefix: sym }
          }}
          useResizeHandler={true}
          style={{ width: '100%' }}
        />
      </div>

      {/* EBIT Margin Trend */}
      <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg">
        <div className="flex justify-between items-center mb-2">
          <h3 className="font-display text-base font-bold text-[#f4eedf]">Operating EBIT Margin</h3>
          <span className={`text-xs px-2.5 py-1 rounded-lg font-display font-bold tabular-nums border ${
            trends.margin_trend === 'expanding' ? 'bg-[#34b38a]/15 text-[#34b38a] border-[#34b38a]/30' : 
            trends.margin_trend === 'compressing' ? 'bg-[#e07a5f]/15 text-[#e07a5f] border-[#e07a5f]/30' : 'bg-[#0d121a] text-[#a6b0c3] border-[#f4eedf]/10'
          }`}>
            {trends.margin_trend.toUpperCase()}
          </span>
        </div>
        <Plot
          data={[{
            x: trends.margin_history.map(d => d.year),
            y: trends.margin_history.map(d => d.value),
            type: 'scatter',
            mode: 'lines+markers',
            line: { color: '#34b38a', width: 3 },
            marker: { size: 8, color: '#34b38a' }
          }]}
          layout={{
            ...layoutConfig,
            yaxis: { ...layoutConfig.yaxis, tickformat: '.1%' }
          }}
          useResizeHandler={true}
          style={{ width: '100%' }}
        />
      </div>

      {/* CapEx Intensity */}
      <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg">
        <div className="flex justify-between items-center mb-2">
          <h3 className="font-display text-base font-bold text-[#f4eedf]">CapEx Intensity (% of Revenue)</h3>
          <span className="text-xs font-display font-bold text-[#e3b23c]">
            {trends.capex_trend}
          </span>
        </div>
        <Plot
          data={[{
            x: trends.capex_intensity.map(d => d.year),
            y: trends.capex_intensity.map(d => d.value),
            type: 'scatter',
            mode: 'lines+markers',
            line: { color: '#e3b23c', width: 2.5 },
            marker: { size: 7, color: '#e3b23c' }
          }]}
          layout={{
            ...layoutConfig,
            yaxis: { ...layoutConfig.yaxis, tickformat: '.1%' }
          }}
          useResizeHandler={true}
          style={{ width: '100%' }}
        />
      </div>

      {/* FCF History */}
      <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg">
        <div className="flex justify-between items-center mb-2">
          <h3 className="font-display text-base font-bold text-[#f4eedf]">Free Cash Flow History</h3>
        </div>
        <Plot
          data={[{
            x: trends.fcf_history.map(d => d.year),
            y: trends.fcf_history.map(d => d.value),
            type: 'bar',
            marker: { 
              color: trends.fcf_history.map(d => d.value >= 0 ? '#34b38a' : '#e07a5f')
            }
          }]}
          layout={{
            ...layoutConfig,
            yaxis: { ...layoutConfig.yaxis, tickprefix: sym }
          }}
          useResizeHandler={true}
          style={{ width: '100%' }}
        />
      </div>
    </div>
  );
}
