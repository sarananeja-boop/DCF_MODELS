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
  const { monte_carlo, market_data, company, diagnostics, dcf_result } = data;
  if (!monte_carlo) return null;

  const isEquityModel = Boolean(
    company?.is_financial ||
    company?.is_equity_model ||
    company?.model_type === 'CORPORATE_DDM' ||
    diagnostics?.is_equity_model ||
    dcf_result?.is_equity_model
  );

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
  const corrSampleSize = monte_carlo.corr_sample_size;
  const isCorrRegularized = monte_carlo.is_corr_regularized;
  const totalSimulations = monte_carlo.total_simulations || iterations * 3;
  const validSimulations = monte_carlo.valid_simulations || iterations;
  const invalidReasons = monte_carlo.invalid_simulation_reasons || {};

  const formatCurrency = (val) => {
    if (val == null) return '-';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: currency,
      maximumFractionDigits: 2
    }).format(val);
  };

  const p5 = stats?.p5 ?? 0;
  const p95 = stats?.p95 ?? 0;
  const median = stats?.median ?? 0;
  const zeroPriceSims = monte_carlo.zero_price_simulations ?? 0;
  const rejectedSims = Math.max(0, totalSimulations - validSimulations);

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
    margin: { l: 50, r: 20, t: 35, b: 45 },
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
        y: 1.05,
        yref: 'paper',
        text: 'Mkt Price',
        showarrow: false,
        font: { color: '#e07a5f', size: 10, family: 'Space Grotesk, sans-serif' }
      },
      {
        x: median,
        y: 0.94,
        yref: 'paper',
        text: 'Median',
        showarrow: false,
        font: { color: '#34b38a', size: 10, family: 'Space Grotesk, sans-serif' }
      },
      {
        x: p5,
        y: 1.05,
        yref: 'paper',
        text: 'P5',
        showarrow: false,
        font: { color: '#e3b23c', size: 10, family: 'Space Grotesk, sans-serif' }
      },
      {
        x: p95,
        y: 1.05,
        yref: 'paper',
        text: 'P95',
        showarrow: false,
        font: { color: '#e3b23c', size: 10, family: 'Space Grotesk, sans-serif' }
      }
    ]
  }), [warmLayout, currency, p5, p95, median, currentPrice]);

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
      {/* 90% Monte Carlo Simulation Range Banner */}
      <div className="bg-[#101722] rounded-2xl p-4 sm:p-5 border border-white/[0.08] shadow-md flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase font-bold tracking-wider text-[#e3b23c]">
              90% Monte Carlo Simulation Range (P5–P95)
            </span>
            <span className="text-[10px] px-2 py-0.5 rounded bg-white/[0.06] text-[#a6b0c3] font-mono">
              10,000 Cholesky Draws
            </span>
          </div>
          <div className="font-display text-2xl sm:text-3xl font-bold text-[#f4eedf] tabular-nums mt-1">
            {formatCurrency(p5)} <span className="text-[#818ea4] text-lg font-normal">to</span> {formatCurrency(p95)}
          </div>
          <p className="text-[11px] text-[#a6b0c3] mt-1 max-w-2xl leading-relaxed">
            Corridor of simulated intrinsic business valuations across 10,000 correlated iterations. This is an outcome distribution under model assumptions, not a market price forecast.
          </p>
        </div>

        {/* Simulation Integrity Badge Strip */}
        <div className="flex flex-wrap items-center gap-3 text-xs bg-[#090d14] px-3.5 py-2.5 rounded-xl border border-white/[0.08]">
          <div className="text-left">
            <span className="text-[10px] text-[#818ea4] block">Candidate Draws</span>
            <span className="font-display font-bold text-xs text-[#f4eedf] tabular-nums">
              {totalSimulations.toLocaleString()}
            </span>
          </div>
          <div className="h-6 w-px bg-white/[0.08]" />
          <div className="text-left">
            <span className="text-[10px] text-[#818ea4] block">Retained Valid</span>
            <span className="font-display font-bold text-xs text-[#34b38a] tabular-nums">
              {validSimulations.toLocaleString()}
            </span>
          </div>
          <div className="h-6 w-px bg-white/[0.08]" />
          <div className="text-left">
            <span className="text-[10px] text-[#818ea4] block">Input ρ (Correlation)</span>
            <span className="font-display font-bold text-xs text-[#8ab4f8] tabular-nums">
              {Number(histCorrGm).toFixed(2)}
              {corrSampleSize ? <span className="text-[10px] font-normal text-[#818ea4]"> (N={corrSampleSize})</span> : null}
              {isCorrRegularized ? <span className="text-[9px] text-[#e3b23c] ml-1 uppercase">Reg.</span> : null}
            </span>
          </div>
        </div>
      </div>

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
          <div className="mt-4 pt-4 border-t border-[#f4eedf]/10 overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
              <h4 className="font-display font-bold text-xs sm:text-sm text-[#f4eedf]">
                Implied Share Price Distribution ({iterations.toLocaleString()} Runs)
              </h4>
              <span className="text-[11px] font-mono text-[#a6b0c3]">
                {isEquityModel ? 'Growth–ROE' : 'Growth–Margin'} ρ = {Number(histCorrGm).toFixed(2)}
              </span>
            </div>
            <div className="min-h-[340px] sm:min-h-[380px] flex items-center justify-center">
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
                  style={{ width: '100%', height: '360px' }}
                  className="w-full"
                />
              ) : (
                <div className="flex flex-col items-center justify-center gap-2 text-xs text-[#a6b0c3]">
                  <div className="w-8 h-8 rounded-full border-2 border-[#5b8fd9]/20 border-t-[#5b8fd9] animate-spin"></div>
                  <span>Rendering 10,000-run distribution...</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Simulation Guardrails, Rejection Criteria & Correlation Disclosure */}
        <div className="mt-4 pt-3.5 border-t border-[#f4eedf]/10 grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-[#a6b0c3]">
          <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/8">
            <div className="text-[10px] font-bold uppercase tracking-wider text-[#e3b23c] mb-1">
              Sampling &amp; Rejection Guardrails
            </div>
            <p className="leading-relaxed">
              Retained <strong className="text-[#f4eedf] tabular-nums">{validSimulations.toLocaleString()}</strong> valid paths from <strong className="text-[#f4eedf] tabular-nums">{totalSimulations.toLocaleString()}</strong> candidate draws ({rejectedSims.toLocaleString()} rejected). Draws violating <span className="font-mono text-[#f4eedf]">{isEquityModel ? 'Ke' : 'WACC'} ≤ g + 0.50%</span>, <span className="font-mono text-[#f4eedf]">Kd ≤ 0%</span>, or <span className="font-mono text-[#f4eedf]">Rf / ERP ≤ 0%</span> are discarded.
            </p>
          </div>
          <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/8">
            <div className="text-[10px] font-bold uppercase tracking-wider text-[#8ab4f8] mb-1">
              Cholesky Correlation Provenance
            </div>
            <p className="leading-relaxed">
              {isEquityModel ? 'Growth–ROE' : 'Growth–Margin'} correlation (<span className="font-mono text-[#f4eedf]">ρ = {Number(histCorrGm).toFixed(2)}</span>) estimated across{' '}
              <strong className="text-[#f4eedf]">{corrSampleSize || 4} annual filings</strong>
              {isCorrRegularized ? ' with Bayesian shrinkage toward 0 for small sample stability (N < 5).' : '.'}{' '}
              Deterministic seed (<span className="font-mono text-[#f4eedf]">seed=42</span>) ensures reproducible quantiles.
            </p>
          </div>
          <div className="bg-[#0d121a] rounded-xl p-3 border border-[#f4eedf]/8">
            <div className="text-[10px] font-bold uppercase tracking-wider text-[#34b38a] mb-1">
              Limited-Liability Equity Floor
            </div>
            <p className="leading-relaxed">
              Paths where Net Debt exceeds simulated Enterprise Value (<span className="font-mono text-[#f4eedf]">Equity ≤ 0</span>) are floored at <strong className="text-[#f4eedf]">0.00/share</strong> rather than discarded (<strong className="text-[#f4eedf] tabular-nums">{zeroPriceSims.toLocaleString()}</strong> wipeout draws).
            </p>
          </div>
        </div>
      </div>

      {/* Scatter Plots (Downsampled & Defer-Mounted for Instant Zero-Lag Tab Switching) */}
      {sampledScatter && (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <div className="bg-[#141b26] rounded-2xl p-4 border border-[#f4eedf]/10 shadow-lg min-h-[270px] overflow-hidden">
            <h4 className="font-display font-bold text-xs sm:text-sm text-[#f4eedf] mb-1">
              Growth vs {isEquityModel ? 'ROE' : 'Margin'} (ρ = {Number(histCorrGm).toFixed(2)})
            </h4>
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
                  xaxis: { ...warmLayout.xaxis, title: 'Growth Rate', tickformat: '.1%' },
                  yaxis: { ...warmLayout.yaxis, title: isEquityModel ? 'Target ROE' : 'Operating Margin', tickformat: '.1%' },
                  margin: { l: 50, r: 20, t: 15, b: 40 }
                }}
                config={plotConfig}
                useResizeHandler={true}
                style={{ width: '100%', height: '250px' }}
                className="w-full"
              />
            ) : (
              <div className="h-[250px] flex items-center justify-center text-xs text-[#a6b0c3]">
                <span>Preparing correlation plot...</span>
              </div>
            )}
          </div>

          <div className="bg-[#141b26] rounded-2xl p-4 border border-[#f4eedf]/10 shadow-lg min-h-[270px] overflow-hidden">
            <h4 className="font-display font-bold text-xs sm:text-sm text-[#f4eedf] mb-1">
              Growth vs {isEquityModel ? 'Cost of Equity (Ke)' : 'Discount Rate (WACC)'}
            </h4>
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
                  xaxis: { ...warmLayout.xaxis, title: 'Growth Rate', tickformat: '.1%' },
                  yaxis: { ...warmLayout.yaxis, title: isEquityModel ? 'Cost of Equity (Ke)' : 'WACC', tickformat: '.1%' },
                  margin: { l: 50, r: 20, t: 15, b: 40 }
                }}
                config={plotConfig}
                useResizeHandler={true}
                style={{ width: '100%', height: '250px' }}
                className="w-full"
              />
            ) : (
              <div className="h-[250px] flex items-center justify-center text-xs text-[#a6b0c3]">
                <span>Preparing correlation plot...</span>
              </div>
            )}
          </div>

          <div className="bg-[#141b26] rounded-2xl p-4 border border-[#f4eedf]/10 shadow-lg min-h-[270px] overflow-hidden">
            <h4 className="font-display font-bold text-xs sm:text-sm text-[#f4eedf] mb-1">
              {isEquityModel ? 'ROE' : 'Margin'} vs {isEquityModel ? 'Cost of Equity (Ke)' : 'Discount Rate (WACC)'}
            </h4>
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
                  xaxis: { ...warmLayout.xaxis, title: isEquityModel ? 'Target ROE' : 'Operating Margin', tickformat: '.1%' },
                  yaxis: { ...warmLayout.yaxis, title: isEquityModel ? 'Cost of Equity (Ke)' : 'WACC', tickformat: '.1%' },
                  margin: { l: 50, r: 20, t: 15, b: 40 }
                }}
                config={plotConfig}
                useResizeHandler={true}
                style={{ width: '100%', height: '250px' }}
                className="w-full"
              />
            ) : (
              <div className="h-[250px] flex items-center justify-center text-xs text-[#a6b0c3]">
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