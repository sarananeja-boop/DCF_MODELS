import React from 'react';
import Plot from 'react-plotly.js';

export default function SensitivityTab({ data }) {
  if (!data || !data.sensitivity) return null;

  const { growth_wacc, margin_wacc } = data.sensitivity;
  const isFinancial = Boolean(data.company?.is_financial || data.diagnostics?.is_financial || data.dcf_result?.is_financial);
  const sym = data.company?.symbol || (data.company?.currency === 'INR' ? '₹' : '$');

  const layoutConfig = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#a1a1aa', family: 'font-mono, tabular-nums, sans-serif' },
    margin: { t: 40, r: 20, l: 80, b: 60 },
  };

  const createAnnotations = (x, y, z) => {
    if (!x || !y || !z || !Array.isArray(z) || !Array.isArray(y) || !Array.isArray(x)) return [];
    const annotations = [];
    for (let i = 0; i < y.length; i++) {
      if (!z[i] || !Array.isArray(z[i])) continue;
      for (let j = 0; j < x.length; j++) {
        const val = z[i][j];
        if (val !== undefined && val !== null && !isNaN(val)) {
          annotations.push({
            x: x[j],
            y: y[i],
            text: `${sym}${Number(val).toFixed(1)}`,
            font: { color: '#fff', size: 10 },
            showarrow: false
          });
        }
      }
    }
    return annotations;
  };

  // Grid 1 Data (Growth vs WACC / Ke)
  const g1_z = growth_wacc?.price_grid || growth_wacc?.grid || [];
  const g1_x = growth_wacc?.growth_range || [];
  const g1_y = growth_wacc?.wacc_range || [];

  // Grid 2 Data (Margin / ROE vs WACC / Ke)
  const g2_z = margin_wacc?.price_grid || margin_wacc?.grid || [];
  const g2_x = margin_wacc?.margin_range || margin_wacc?.roe_range || margin_wacc?.growth_range || [];
  const g2_y = margin_wacc?.wacc_range || [];

  return (
    <div className="space-y-6">
      {/* 1. First Sensitivity Matrix */}
      <div className="bg-zinc-900 rounded-lg p-6 border border-zinc-800 shadow-lg">
        <h3 className="text-xl font-semibold mb-2">
          {isFinancial ? 'Sensitivity: Net Income Growth vs Cost of Equity (Ke)' : 'Sensitivity: Growth vs WACC'}
        </h3>
        <p className="text-sm text-text-secondary mb-4">
          {isFinancial
            ? 'Implied share price across variations of Yr-1 Net Income Growth and Cost of Equity (Ke).'
            : 'Implied share price across variations of Yr-1 Revenue Growth and WACC.'}
        </p>
        <div className="w-full overflow-hidden">
          <Plot
            data={[{
              z: g1_z,
              x: g1_x,
              y: g1_y,
              type: 'heatmap',
              colorscale: 'RdYlGn',
              showscale: true,
              colorbar: { title: 'Price', tickprefix: sym }
            }]}
            layout={{
              ...layoutConfig,
              height: 400,
              autosize: true,
              xaxis: { 
                tickformat: '.1%', 
                title: isFinancial ? 'Net Income Growth Rate' : 'Revenue Growth Rate' 
              },
              yaxis: { 
                tickformat: '.1%', 
                title: isFinancial ? 'Cost of Equity (Ke)' : 'WACC' 
              },
              annotations: createAnnotations(g1_x, g1_y, g1_z)
            }}
            useResizeHandler={true}
            style={{ width: '100%', height: '100%' }}
          />
        </div>
      </div>

      {/* 2. Second Sensitivity Matrix */}
      <div className="bg-zinc-900 rounded-lg p-6 border border-zinc-800 shadow-lg">
        <h3 className="text-xl font-semibold mb-2">
          {isFinancial ? 'Sensitivity: Target ROE vs Cost of Equity (Ke)' : 'Sensitivity: Margin vs WACC'}
        </h3>
        <p className="text-sm text-text-secondary mb-4">
          {isFinancial
            ? 'Implied share price across variations of Target Return on Equity (ROE) and Cost of Equity (Ke).'
            : 'Implied share price across variations of EBIT Margin and WACC.'}
        </p>
        <div className="w-full overflow-hidden">
          <Plot
            data={[{
              z: g2_z,
              x: g2_x,
              y: g2_y,
              type: 'heatmap',
              colorscale: 'RdYlGn',
              showscale: true,
              colorbar: { title: 'Price', tickprefix: sym }
            }]}
            layout={{
              ...layoutConfig,
              height: 400,
              autosize: true,
              xaxis: { 
                tickformat: '.1%', 
                title: isFinancial ? 'Target Return on Equity (ROE)' : 'EBIT Margin' 
              },
              yaxis: { 
                tickformat: '.1%', 
                title: isFinancial ? 'Cost of Equity (Ke)' : 'WACC' 
              },
              annotations: createAnnotations(g2_x, g2_y, g2_z)
            }}
            useResizeHandler={true}
            style={{ width: '100%', height: '100%' }}
          />
        </div>
      </div>
    </div>
  );
}
