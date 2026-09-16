import React from 'react';
import Plot from 'react-plotly.js';

export default function SensitivityTab({ data }) {
  if (!data || !data.sensitivity) return null;

  const { growth_wacc, margin_wacc } = data.sensitivity;
  const sym = data.company.symbol;

  const layoutConfig = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: '#111640',
    font: { color: '#f1f5f9' },
    margin: { t: 40, r: 20, l: 80, b: 60 },
    xaxis: { tickformat: '.1%', title: 'Revenue Growth Rate' },
    yaxis: { tickformat: '.1%', title: 'WACC' },
  };

  const createAnnotations = (x, y, z) => {
    const annotations = [];
    for (let i = 0; i < y.length; i++) {
      for (let j = 0; j < x.length; j++) {
        annotations.push({
          x: x[j],
          y: y[i],
          text: `${sym}${z[i][j].toFixed(1)}`,
          font: { color: '#fff', size: 10 },
          showarrow: false
        });
      }
    }
    return annotations;
  };

  return (
    <div className="space-y-6">
      <div className="bg-navy-800 rounded-lg p-6 border border-navy-600 shadow-lg">
        <h3 className="text-xl font-semibold mb-2">Sensitivity: Growth vs WACC</h3>
        <p className="text-sm text-text-secondary mb-4">
          Implied share price across variations of Yr-1 Revenue Growth and WACC.
        </p>
        <div className="w-full overflow-hidden">
          <Plot
            data={[{
              z: growth_wacc.price_grid,
              x: growth_wacc.growth_range,
              y: growth_wacc.wacc_range,
              type: 'heatmap',
              colorscale: 'RdYlGn',
              showscale: true,
              colorbar: { title: 'Price', tickprefix: sym }
            }]}
            layout={{
              ...layoutConfig,
              height: 400,
              autosize: true,
              annotations: createAnnotations(growth_wacc.growth_range, growth_wacc.wacc_range, growth_wacc.price_grid)
            }}
            useResizeHandler={true}
            style={{ width: '100%', height: '100%' }}
          />
        </div>
      </div>

      <div className="bg-navy-800 rounded-lg p-6 border border-navy-600 shadow-lg">
        <h3 className="text-xl font-semibold mb-2">Sensitivity: Margin vs WACC</h3>
        <p className="text-sm text-text-secondary mb-4">
          Implied share price across variations of EBIT Margin and WACC.
        </p>
        <div className="w-full overflow-hidden">
          <Plot
            data={[{
              z: margin_wacc.price_grid,
              x: margin_wacc.margin_range,
              y: margin_wacc.wacc_range,
              type: 'heatmap',
              colorscale: 'RdYlGn',
              showscale: true,
              colorbar: { title: 'Price', tickprefix: sym }
            }]}
            layout={{
              ...layoutConfig,
              height: 400,
              autosize: true,
              xaxis: { tickformat: '.1%', title: 'EBIT Margin' },
              annotations: createAnnotations(margin_wacc.margin_range, margin_wacc.wacc_range, margin_wacc.price_grid)
            }}
            useResizeHandler={true}
            style={{ width: '100%', height: '100%' }}
          />
        </div>
      </div>
    </div>
  );
}
