import React from 'react';
import Plot from 'react-plotly.js';

export default function TrendsTab({ data }) {
  if (!data || !data.trends) return null;

  const { trends } = data;
  const sym = data.company.symbol;

  const layoutConfig = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#a1a1aa', family: 'font-mono, tabular-nums, sans-serif' },
    margin: { t: 40, r: 20, l: 60, b: 40 },
    height: 300,
    autosize: true,
    xaxis: { 
      gridcolor: '#27272a', 
      dtick: 1, 
      tickfont: { color: '#a1a1aa' } 
    },
    yaxis: { 
      gridcolor: '#27272a', 
      tickfont: { color: '#a1a1aa' } 
    }
  };

  const formatYAxis = (val) => {
    if (val >= 1e9) return `${sym}${(val/1e9).toFixed(1)}B`;
    if (val >= 1e6) return `${sym}${(val/1e6).toFixed(1)}M`;
    return `${sym}${val}`;
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        
        {/* Revenue History */}
        <div className="bg-zinc-900 rounded-lg p-6 border border-zinc-800 shadow-lg">
          <div className="flex justify-between items-start mb-2">
            <h3 className="text-lg font-semibold">Revenue History</h3>
            <span className="text-xs bg-accent-blue/20 text-accent-blue px-2 py-1 rounded font-mono tabular-nums">
              CAGR: {(trends.revenue_cagr * 100).toFixed(1)}%
            </span>
          </div>
          <Plot
            data={[{
              x: trends.revenue_history.map(d => d.year),
              y: trends.revenue_history.map(d => d.value),
              type: 'bar',
              marker: { color: '#3b82f6' }
            }]}
            layout={{
              ...layoutConfig,
              yaxis: { tickprefix: sym }
            }}
            useResizeHandler={true}
            style={{ width: '100%' }}
          />
        </div>

        {/* EBIT Margin Trend */}
        <div className="bg-zinc-900 rounded-lg p-6 border border-zinc-800 shadow-lg">
          <div className="flex justify-between items-start mb-2">
            <h3 className="text-lg font-semibold">EBIT Margin Trend</h3>
            <span className={`text-xs px-2 py-1 rounded font-mono tabular-nums ${
              trends.margin_trend === 'expanding' ? 'bg-accent-green/20 text-accent-green' : 
              trends.margin_trend === 'compressing' ? 'bg-accent-red/20 text-accent-red' : 'bg-gray-700 text-gray-300'
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
              line: { color: '#10b981', width: 3 },
              marker: { size: 8 }
            }]}
            layout={{
              ...layoutConfig,
              yaxis: { tickformat: '.1%' }
            }}
            useResizeHandler={true}
            style={{ width: '100%' }}
          />
        </div>

        {/* CapEx Intensity */}
        <div className="bg-zinc-900 rounded-lg p-6 border border-zinc-800 shadow-lg">
          <div className="flex justify-between items-start mb-2">
            <h3 className="text-lg font-semibold">CapEx / Revenue</h3>
            <span className="text-xs bg-zinc-800/80 text-text-secondary px-2 py-1 rounded">
              {trends.capex_trend}
            </span>
          </div>
          <Plot
            data={[{
              x: trends.capex_intensity.map(d => d.year),
              y: trends.capex_intensity.map(d => d.value),
              type: 'scatter',
              mode: 'lines+markers',
              line: { color: '#f59e0b', width: 2 },
              marker: { size: 6 }
            }]}
            layout={{
              ...layoutConfig,
              yaxis: { tickformat: '.1%' }
            }}
            useResizeHandler={true}
            style={{ width: '100%' }}
          />
        </div>

        {/* FCF History */}
        <div className="bg-zinc-900 rounded-lg p-6 border border-zinc-800 shadow-lg">
          <h3 className="text-lg font-semibold mb-2">Proxy FCF History</h3>
          <Plot
            data={[{
              x: trends.fcf_history.map(d => d.year),
              y: trends.fcf_history.map(d => d.value),
              type: 'bar',
              marker: { 
                color: trends.fcf_history.map(d => d.value >= 0 ? '#10b981' : '#ef4444')
              }
            }]}
            layout={{
              ...layoutConfig,
              yaxis: { tickprefix: sym }
            }}
            useResizeHandler={true}
            style={{ width: '100%' }}
          />
        </div>

      </div>
    </div>
  );
}
