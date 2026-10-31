import React, { useMemo, useState, useEffect } from 'react';
import Plot from 'react-plotly.js';

const downsample = (arr, maxPoints = 350) => {
  if (!arr || !Array.isArray(arr)) return [];
  if (arr.length <= maxPoints) return arr;
  const step = Math.ceil(arr.length / maxPoints);
  const result = [];
  for (let i = 0; i < arr.length; i += step) {
    result.push(arr[i]);
  }
  return result;
};

const MonteCarloTab = ({ data }) => {
  if (!data) return null;
  const { monte_carlo, market_data, company } = data;
  if (!monte_carlo) return null;

  const [chartsReady, setChartsReady] = useState(false);

  useEffect(() => {
    // Microtask deferral so the tab mounts instantaneously without blocking UI thread
    const timer = setTimeout(() => setChartsReady(true), 40);
    return () => clearTimeout(timer);
  }, []);

  const { stats, histogram } = monte_carlo;
  const rawScatter = monte_carlo.scatter_data || monte_carlo.scatter;
  const currency = company?.currency || 'USD';
  const currentPrice = market_data?.current_price || 0;
  const iterations = monte_carlo.actual_iterations || monte_carlo.inputs?.iterations || 10000;
  const histCorrGm = monte_carlo.hist_corr_gm ?? monte_carlo.inputs?.hist_corr_gm ?? 0;

  const formatCurrency = (val) => {
    if (val == null) return '-';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: currency,
      maximumFractionDigits: 2
    }).format(val);
  };

  const p5 = stats?.p5 || 0;
  const p95 = stats?.p95 || 0;
  const median = stats?.median || 0;

  // Downsample scatter data for instant 0ms rendering
  const sampledScatter = useMemo(() => {
    if (!rawScatter) return null;
    const g = rawScatter.growth || rawScatter.sim_growth || [];
    const m = rawScatter.margin || rawScatter.sim_margin || [];
    const w = rawScatter.wacc || rawScatter.sim_wacc || [];
    const maxP = 350;
    const step = Math.max(1, Math.ceil(g.length / maxP));

    const growth = [];
    const margin = [];
    const wacc = [];
    for (let i = 0; i < g.length; i += step) {
      growth.push(g[i]);
      margin.push(m[i]);
      wacc.push(w[i]);
    }
    return { growth, margin, wacc };
  }, [rawScatter]);

  const warmLayout = useMemo(() => ({
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#a6b0c3', family: 'Plus Jakarta Sans, sans-serif' },
    xaxis: { gridcolor: 'rgba(244,238,223,0.08)', zerolinecolor: 'rgba(244,238,223,0.12)' },
    yaxis: { gridcolor: 'rgba(244,238,223,0.08)', zerolinecolor: 'rgba(244,238,223,0.12)' },
    margin: { l: 60, r: 30, t: 45, b: 45 },
  }), []);

  const plotConfig = useMemo(() => ({ responsive: true, displayModeBar: false }), []);

  const histogramLayout = useMemo(() => ({
    ...warmLayout,
    title: {
      text: `Implied Share Price Distribution (${iterations.toLocaleString()} Runs | Growth–Margin ρ = ${Number(histCorrGm).toFixed(2)})`,
      font: { color: '#f4eedf', size: 13, family: 'Space Grotesk, sans-serif' }
    },
    xaxis: { ...warmLayout.xaxis, title: `Implied Share Price (${currency})` },
    yaxis: { ...warmLayout.yaxis, title: 'Frequency' },
    shapes: [
      {
        type: 'rect',
        x0: p5,
        x1: p95,
        y0: 0,
        y1: 1,
        yref: 'paper',
        fillcolor: 'rgba(91,143,217,0.09)',
        line: { width: 0 }
      },
      {
        type: 'line',
        x0: currentPrice,
        x1: currentPrice,
        y0: 0,
        y1: 1,
        yref: 'paper',
        line: { color: '#e07a5f', width: 2, dash: 'dash' }
      },
      {
        type: 'line',
        x0: median,
        x1: median,
        y0: 0,
        y1: 1,
        yref: 'paper',
        line: { color: '#34b38a', width: 2.5, dash: 'solid' }
      },
      {
        type: 'line',
        x0: p5,
        x1: p5,
        y0: 0,
        y1: 1,
        yref: 'paper',
        line: { color: '#e3b23c', width: 2, dash: 'dash' }
      },
      {
        type: 'line',
        x0: p95,
        x1: p95,
        y0: 0,
        y1: 1,
        yref: 'paper',
        line: { color: '#e3b23c', width: 2, dash: 'dash' }
      }
    ],
    annotations: [
      {
        x: currentPrice,
        y: 1.03,
        yref: 'paper',
        text: 'Market Price',
        showarrow: false,
        font: { color: '#e07a5f', size: 10, family: 'Space Grotesk, sans-serif' }
      },
      {
        x: median,
        y: 1.03,
        yref: 'paper',
        text: 'Median Fair Value',
        showarrow: false,
        font: { color: '#34b38a', size: 10, family: 'Space Grotesk, sans-serif' }
      },
      {
        x: p5,
        y: 1.03,
        yref: 'paper',
        text: 'P5 (Bear)',
        showarrow: false,
        font: { color: '#e3b23c', size: 10, family: 'Space Grotesk, sans-serif' }
      },
      {
        x: p95,
        y: 1.03,
        yref: 'paper',
        text: 'P95 (Bull)',
        showarrow: false,
        font: { color: '#e3b23c', size: 10, family: 'Space Grotesk, sans-serif' }
      }
    ]
  }), [warmLayout, iterations, histCorrGm, currency, p5, p95, median, currentPrice]);

  const statItems = [
    { label: 'P5 (Bear 5%)', value: stats?.p5 },
    { label: 'P25 (Lower Q)', value: stats?.p25 },
    { label: 'Median (P50)', value: stats?.median, highlight: true },
    { label: 'Mean Value', value: stats?.mean },
    { label: 'P75 (Upper Q)', value: stats?.p75 },
    { label: 'P95 (Bull 95%)', value: stats?.p95 },
    { label: 'Std Deviation', value: stats?.std_dev }
  ];

  return (
    <div className="space-y-4 text-[#f4eedf]">
      {/* Stats Row */}
      <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg">
        <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-7 gap-2.5">
          {statItems.map((stat, idx) => (
            <div 
              key={idx} 
              className="bg-[#0d121a] rounded-xl p-3 text-center border border-[#f4eedf]/10"
            >
              <div className={`text-[11px] font-semibold uppercase mb-1 ${stat.highlight ? 'text-[#e3b23c]' : 'text-[#a6b0c3]'}`}>
                {stat.label}
              </div>
              <div className={`font-display text-base sm:text-lg font-bold tabular-nums ${stat.highlight ? 'text-[#e3b23c]' : 'text-[#f4eedf]'}`}>
                {formatCurrency(stat.value)}
              </div>
            </div>
          ))}
        </div>

        {/* Histogram Chart */}
        {histogram && (
          <div className="mt-4 pt-4 border-t border-[#f4eedf]/10 min-h-[380px] flex items-center justify-center">
            {chartsReady ? (
              <Plot
                data={[
                  {
                    x: histogram.bins,
                    y: histogram.counts,
                    type: 'bar',
                    marker: { color: 'rgba(91, 143, 217, 0.72)' }
                  }
                ]}
                layout={histogramLayout}
                config={plotConfig}
                useResizeHandler={true}
                style={{ width: '100%', height: '380px' }}
                className="w-full"
              />
            ) : (
              <div className="flex flex-col items-center justify-center gap-2 text-xs text-[#a6b0c3]">
                <div className="w-8 h-8 rounded-full border-2 border-[#5b8fd9]/20 border-t-[#5b8fd9] animate-spin"></div>
                <span>Rendering 10,000-run distribution...</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Scatter Plots (Downsampled & Defer-Mounted for Instant Zero-Lag Tab Switching) */}
      {sampledScatter && (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <div className="bg-[#141b26] rounded-2xl p-4 border border-[#f4eedf]/10 shadow-lg min-h-[270px]">
            {chartsReady ? (
              <Plot
                data={[
                  {
                    x: sampledScatter.growth,
                    y: sampledScatter.margin,
                    mode: 'markers',
                    type: 'scatter',
                    marker: { color: 'rgba(91,143,217,0.35)', size: 4 }
                  }
                ]}
                layout={{
                  ...warmLayout,
                  title: { text: `Growth vs Margin (ρ = ${Number(histCorrGm).toFixed(2)})`, font: { color: '#f4eedf', size: 12, family: 'Space Grotesk, sans-serif' } },
                  xaxis: { ...warmLayout.xaxis, title: 'Growth Rate', tickformat: '.1%' },
                  yaxis: { ...warmLayout.yaxis, title: 'Operating Margin', tickformat: '.1%' },
                  margin: { l: 50, r: 20, t: 40, b: 40 }
                }}
                config={plotConfig}
                useResizeHandler={true}
                style={{ width: '100%', height: '270px' }}
                className="w-full"
              />
            ) : (
              <div className="h-[270px] flex items-center justify-center text-xs text-[#a6b0c3]">
                <span>Preparing correlation plot...</span>
              </div>
            )}
          </div>

          <div className="bg-[#141b26] rounded-2xl p-4 border border-[#f4eedf]/10 shadow-lg min-h-[270px]">
            {chartsReady ? (
              <Plot
                data={[
                  {
                    x: sampledScatter.growth,
                    y: sampledScatter.wacc,
                    mode: 'markers',
                    type: 'scatter',
                    marker: { color: 'rgba(52,179,138,0.35)', size: 4 }
                  }
                ]}
                layout={{
                  ...warmLayout,
                  title: { text: 'Growth vs Discount Rate (WACC)', font: { color: '#f4eedf', size: 12, family: 'Space Grotesk, sans-serif' } },
                  xaxis: { ...warmLayout.xaxis, title: 'Growth Rate', tickformat: '.1%' },
                  yaxis: { ...warmLayout.yaxis, title: 'WACC', tickformat: '.1%' },
                  margin: { l: 50, r: 20, t: 40, b: 40 }
                }}
                config={plotConfig}
                useResizeHandler={true}
                style={{ width: '100%', height: '270px' }}
                className="w-full"
              />
            ) : (
              <div className="h-[270px] flex items-center justify-center text-xs text-[#a6b0c3]">
                <span>Preparing correlation plot...</span>
              </div>
            )}
          </div>

          <div className="bg-[#141b26] rounded-2xl p-4 border border-[#f4eedf]/10 shadow-lg min-h-[270px]">
            {chartsReady ? (
              <Plot
                data={[
                  {
                    x: sampledScatter.margin,
                    y: sampledScatter.wacc,
                    mode: 'markers',
                    type: 'scatter',
                    marker: { color: 'rgba(227,178,60,0.35)', size: 4 }
                  }
                ]}
                layout={{
                  ...warmLayout,
                  title: { text: 'Margin vs Discount Rate (WACC)', font: { color: '#f4eedf', size: 12, family: 'Space Grotesk, sans-serif' } },
                  xaxis: { ...warmLayout.xaxis, title: 'Operating Margin', tickformat: '.1%' },
                  yaxis: { ...warmLayout.yaxis, title: 'WACC', tickformat: '.1%' },
                  margin: { l: 50, r: 20, t: 40, b: 40 }
                }}
                config={plotConfig}
                useResizeHandler={true}
                style={{ width: '100%', height: '270px' }}
                className="w-full"
              />
            ) : (
              <div className="h-[270px] flex items-center justify-center text-xs text-[#a6b0c3]">
                <span>Preparing correlation plot...</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default MonteCarloTab;