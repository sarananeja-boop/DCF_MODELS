import React from 'react';
import Plot from 'react-plotly.js';

const MonteCarloTab = ({ data }) => {
  if (!data) return null;
  const { monte_carlo, market_data, company } = data;
  if (!monte_carlo) return null;

  const { stats, histogram, scatter_data } = monte_carlo;
  const currency = company?.currency || 'USD';
  const currentPrice = market_data?.current_price || 0;
  const iterations = monte_carlo.inputs?.iterations || 10000;

  const formatCurrency = (val) => {
    if (val == null) return '-';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: currency,
      maximumFractionDigits: 2
    }).format(val);
  };

  const formatPercent = (val) => {
    if (val == null) return '-';
    return new Intl.NumberFormat('en-US', {
      style: 'percent',
      maximumFractionDigits: 1
    }).format(val);
  };

  const darkLayout = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: '#111640',
    font: { color: '#e2e8f0', family: 'Inter, system-ui, sans-serif' },
    xaxis: { gridcolor: '#252b6a', zerolinecolor: '#252b6a' },
    yaxis: { gridcolor: '#252b6a', zerolinecolor: '#252b6a' },
    margin: { l: 60, r: 30, t: 50, b: 50 },
  };

  const plotConfig = { responsive: true, displayModeBar: false };

  // Histogram layout
  const p5 = stats?.p5 || 0;
  const p95 = stats?.p95 || 0;
  const median = stats?.median || 0;

  const histogramLayout = {
    ...darkLayout,
    title: `Monte Carlo Distribution (${iterations} iterations)`,
    xaxis: { ...darkLayout.xaxis, title: `Implied Share Price (${currency})` },
    yaxis: { ...darkLayout.yaxis, title: 'Frequency' },
    shapes: [
      {
        type: 'rect',
        x0: p5,
        x1: p95,
        y0: 0,
        y1: 1,
        yref: 'paper',
        fillcolor: 'rgba(59,130,246,0.08)',
        line: { width: 0 }
      },
      {
        type: 'line',
        x0: currentPrice,
        x1: currentPrice,
        y0: 0,
        y1: 1,
        yref: 'paper',
        line: { color: '#ef4444', width: 2, dash: 'dash' } // accent-red
      },
      {
        type: 'line',
        x0: median,
        x1: median,
        y0: 0,
        y1: 1,
        yref: 'paper',
        line: { color: '#10b981', width: 2, dash: 'solid' } // accent-green
      },
      {
        type: 'line',
        x0: p5,
        x1: p5,
        y0: 0,
        y1: 1,
        yref: 'paper',
        line: { color: '#f59e0b', width: 2, dash: 'dash' } // accent-amber
      },
      {
        type: 'line',
        x0: p95,
        x1: p95,
        y0: 0,
        y1: 1,
        yref: 'paper',
        line: { color: '#f59e0b', width: 2, dash: 'dash' }
      }
    ],
    annotations: [
      {
        x: currentPrice,
        y: 1.02,
        yref: 'paper',
        text: 'Current Price',
        showarrow: false,
        font: { color: '#ef4444', size: 10 }
      },
      {
        x: median,
        y: 1.02,
        yref: 'paper',
        text: 'Median',
        showarrow: false,
        font: { color: '#10b981', size: 10 }
      },
      {
        x: p5,
        y: 1.02,
        yref: 'paper',
        text: 'P5',
        showarrow: false,
        font: { color: '#f59e0b', size: 10 }
      },
      {
        x: p95,
        y: 1.02,
        yref: 'paper',
        text: 'P95',
        showarrow: false,
        font: { color: '#f59e0b', size: 10 }
      }
    ]
  };

  const statItems = [
    { label: 'Mean', value: stats?.mean },
    { label: 'Median', value: stats?.median, highlight: true },
    { label: 'P5', value: stats?.p5 },
    { label: 'P25', value: stats?.p25 },
    { label: 'P75', value: stats?.p75 },
    { label: 'P95', value: stats?.p95 },
    { label: 'Std Dev', value: stats?.std_dev }
  ];

  return (
    <div className="flex flex-col space-y-4">
      {/* Stats Cards Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-2">
        {statItems.map((stat, idx) => (
          <div 
            key={idx} 
            className={`bg-navy-700 rounded-lg p-3 text-center ${stat.highlight ? 'border-l-2 border-blue-500' : ''}`}
          >
            <div className="text-xs text-slate-400 uppercase mb-1">{stat.label}</div>
            <div className="text-lg font-semibold font-mono text-slate-100">
              {formatCurrency(stat.value)}
            </div>
          </div>
        ))}
      </div>

      {/* Histogram Chart */}
      {histogram && (
        <div className="bg-navy-700 rounded-xl p-4 mt-4">
          <Plot
            data={[
              {
                x: histogram.bins,
                y: histogram.counts,
                type: 'bar',
                marker: { color: 'rgba(59, 130, 246, 0.7)' }
              }
            ]}
            layout={histogramLayout}
            config={plotConfig}
            useResizeHandler={true}
            style={{ width: '100%', height: '400px' }}
            className="w-full"
          />
        </div>
      )}

      {/* Scatter Plots */}
      {scatter_data && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
          <div className="bg-navy-700 rounded-xl p-4">
            <Plot
              data={[
                {
                  x: scatter_data.growth,
                  y: scatter_data.margin,
                  mode: 'markers',
                  type: 'scatter',
                  marker: { color: 'rgba(59,130,246,0.15)', size: 3 }
                }
              ]}
              layout={{
                ...darkLayout,
                title: `Growth vs Margin (ρ = ${monte_carlo.inputs?.hist_corr_gm?.toFixed(2) || '0.00'})`,
                xaxis: { ...darkLayout.xaxis, title: 'Growth Rate', tickformat: '.1%' },
                yaxis: { ...darkLayout.yaxis, title: 'Operating Margin', tickformat: '.1%' },
                margin: { l: 50, r: 20, t: 40, b: 40 }
              }}
              config={plotConfig}
              useResizeHandler={true}
              style={{ width: '100%', height: '300px' }}
              className="w-full"
            />
          </div>
          
          <div className="bg-navy-700 rounded-xl p-4">
            <Plot
              data={[
                {
                  x: scatter_data.growth,
                  y: scatter_data.wacc,
                  mode: 'markers',
                  type: 'scatter',
                  marker: { color: 'rgba(16,185,129,0.15)', size: 3 }
                }
              ]}
              layout={{
                ...darkLayout,
                title: 'Growth vs WACC',
                xaxis: { ...darkLayout.xaxis, title: 'Growth Rate', tickformat: '.1%' },
                yaxis: { ...darkLayout.yaxis, title: 'WACC', tickformat: '.1%' },
                margin: { l: 50, r: 20, t: 40, b: 40 }
              }}
              config={plotConfig}
              useResizeHandler={true}
              style={{ width: '100%', height: '300px' }}
              className="w-full"
            />
          </div>

          <div className="bg-navy-700 rounded-xl p-4">
            <Plot
              data={[
                {
                  x: scatter_data.margin,
                  y: scatter_data.wacc,
                  mode: 'markers',
                  type: 'scatter',
                  marker: { color: 'rgba(245,158,11,0.15)', size: 3 }
                }
              ]}
              layout={{
                ...darkLayout,
                title: 'Margin vs WACC',
                xaxis: { ...darkLayout.xaxis, title: 'Operating Margin', tickformat: '.1%' },
                yaxis: { ...darkLayout.yaxis, title: 'WACC', tickformat: '.1%' },
                margin: { l: 50, r: 20, t: 40, b: 40 }
              }}
              config={plotConfig}
              useResizeHandler={true}
              style={{ width: '100%', height: '300px' }}
              className="w-full"
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default MonteCarloTab;
