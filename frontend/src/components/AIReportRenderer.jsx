import React from 'react';
import { FiTrendingUp, FiTrendingDown, FiActivity, FiCpu, FiAlertTriangle, FiCheckCircle } from 'react-icons/fi';

const formatNum = (val, currency) => {
  if (val == null || val === '') return 'N/A';
  if (typeof val === 'string') return val;
  const sym = currency === 'INR' ? '₹' : '$';
  return sym + Number(val).toLocaleString(undefined, { maximumFractionDigits: 2 });
};

const formatPct = (val) => {
  if (val == null || val === '') return 'N/A';
  if (typeof val === 'string' && val.includes('%')) return val;
  return Number(val).toFixed(1) + '%';
};

const Card = ({ title, children, className = "" }) => (
  <div className={`bg-zinc-900 border border-zinc-800 rounded-lg p-5 ${className}`}>
    {title && <h4 className="text-sm font-semibold text-zinc-400 mb-3 uppercase tracking-wider">{title}</h4>}
    {children}
  </div>
);

export default function AIReportRenderer({ jsonString }) {
  let report = null;
  try {
    let cleaned = typeof jsonString === 'string' ? jsonString.trim() : '';
    // Extract JSON block if it's wrapped in markdown fences or has leading/trailing text
    const match = cleaned.match(/\{[\s\S]*\}/);
    if (match) {
      cleaned = match[0];
    }
    report = typeof jsonString === 'string' ? JSON.parse(cleaned) : jsonString;
  } catch (e) {
    return (
      <div className="bg-red-950/20 border border-red-900/30 p-4 rounded-lg">
        <div className="text-red-400 font-semibold mb-2">Error parsing AI report data.</div>
        <p className="text-zinc-400 text-sm mb-2">The AI model returned an invalid JSON structure. Please try generating the summary again.</p>
        <p className="text-zinc-500 text-xs mb-1">Raw output snippet:</p>
        <pre className="text-[10px] text-zinc-500 overflow-x-auto max-h-40 bg-zinc-950 p-2 rounded border border-zinc-800 whitespace-pre-wrap">
          {typeof jsonString === 'string' ? jsonString.substring(0, 1000) + (jsonString.length > 1000 ? '...' : '') : ''}
        </pre>
      </div>
    );
  }

  if (!report || (!report.headline_metrics && !report.summary)) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 p-5 rounded-xl text-center space-y-3">
        <div className="text-amber-400 font-medium">Unable to load AI report structure.</div>
        <p className="text-xs text-zinc-400">The AI model response was interrupted or returned an incomplete payload. Please click "Generate AI Summary" above to retry.</p>
      </div>
    );
  }

  if (report && !report.headline_metrics && report.summary) {
    return (
      <div className="space-y-4 text-zinc-300 text-sm bg-zinc-900 border border-zinc-800 p-6 rounded-xl" id="ai-summary-content">
        <div className="prose prose-invert max-w-none whitespace-pre-line leading-relaxed font-sans">
          {report.summary}
        </div>
      </div>
    );
  }

  const { currency, headline_metrics: hl, executive_summary: exec, dcf_analysis: dcf, monte_carlo_analysis: mc, relative_valuation: rel, key_drivers, risks, model_quality, final_synopsis } = report;

  return (
    <div className="space-y-6 text-zinc-300 text-sm" id="ai-summary-content">
      
      {/* Headline Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <div className="text-zinc-500 text-xs mb-1">Current Price</div>
          <div className="text-2xl font-bold text-white">{formatNum(hl?.current_price, currency)}</div>
        </div>
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <div className="text-zinc-500 text-xs mb-1">DCF Value</div>
          <div className="text-2xl font-bold text-blue-400">{formatNum(hl?.dcf_value, currency)}</div>
          <div className={`text-xs mt-1 ${hl?.dcf_upside_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {hl?.dcf_upside_percent >= 0 ? '+' : ''}{formatPct(hl?.dcf_upside_percent)}
          </div>
        </div>
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <div className="text-zinc-500 text-xs mb-1">MC Median</div>
          <div className="text-2xl font-bold text-indigo-400">{formatNum(hl?.monte_carlo_median, currency)}</div>
          <div className={`text-xs mt-1 ${hl?.monte_carlo_upside_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {hl?.monte_carlo_upside_percent >= 0 ? '+' : ''}{formatPct(hl?.monte_carlo_upside_percent)}
          </div>
        </div>
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <div className="text-zinc-500 text-xs mb-1">MC Range (P5-P95)</div>
          <div className="text-lg font-semibold text-white mt-1">
            {formatNum(hl?.monte_carlo_p5, currency)} - {formatNum(hl?.monte_carlo_p95, currency)}
          </div>
        </div>
      </div>

      {/* Executive Summary */}
      <Card title="Executive Summary" className="bg-blue-900/10 border-blue-900/30">
        <p className="text-zinc-200 leading-relaxed">{exec?.overview}</p>
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <span className="text-xs text-blue-400 block mb-1">Primary Driver</span>
            <p className="text-zinc-300">{exec?.primary_driver}</p>
          </div>
          <div>
            <span className="text-xs text-red-400 block mb-1">Primary Risk</span>
            <p className="text-zinc-300">{exec?.primary_risk}</p>
          </div>
        </div>
      </Card>

      {/* DCF & MC details */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card title="DCF Analysis">
          <div className="space-y-4">
            <div>
              <div className="text-xs text-zinc-500 mb-1">Revenue Growth</div>
              <div className="text-white font-medium">{formatPct(dcf?.revenue_growth?.forecast_cagr)} CAGR</div>
              <p className="text-zinc-400 mt-1">{dcf?.revenue_growth?.interpretation}</p>
            </div>
            <div>
              <div className="text-xs text-zinc-500 mb-1">Margins & Cash Flow</div>
              <p className="text-zinc-400">{dcf?.margin?.interpretation}</p>
              <p className="text-zinc-400 mt-1">{dcf?.free_cash_flow?.interpretation}</p>
            </div>
            <div>
              <div className="text-xs text-zinc-500 mb-1">Terminal Value</div>
              <p className="text-zinc-400">TV is {formatPct(dcf?.terminal_value?.percent_of_enterprise_value)} of EV. {dcf?.terminal_value?.interpretation}</p>
            </div>
          </div>
        </Card>

        <Card title="Monte Carlo Analysis">
          <p className="text-zinc-300 mb-4">{mc?.distribution_interpretation}</p>
          <div className="space-y-3">
            <div className="p-3 bg-red-950/20 border border-red-900/30 rounded">
              <span className="text-xs font-semibold text-red-400 block mb-1">Downside Case</span>
              <p className="text-zinc-400">{mc?.downside_case}</p>
            </div>
            <div className="p-3 bg-zinc-950/50 border border-zinc-800 rounded">
              <span className="text-xs font-semibold text-zinc-400 block mb-1">Base Case</span>
              <p className="text-zinc-400">{mc?.base_case}</p>
            </div>
            <div className="p-3 bg-green-950/20 border border-green-900/30 rounded">
              <span className="text-xs font-semibold text-green-400 block mb-1">Upside Case</span>
              <p className="text-zinc-400">{mc?.upside_case}</p>
            </div>
          </div>
        </Card>
      </div>

      {/* Key Drivers */}
      {key_drivers && key_drivers.length > 0 && (
        <Card title="Key Value Drivers">
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-zinc-800 text-zinc-500 text-xs">
                  <th className="pb-2 font-medium">Driver</th>
                  <th className="pb-2 font-medium">Assumption</th>
                  <th className="pb-2 font-medium">Impact & Monitoring</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/50">
                {key_drivers.map((kd, i) => (
                  <tr key={i}>
                    <td className="py-3 pr-4 font-medium text-zinc-200 align-top">{kd.driver}</td>
                    <td className="py-3 pr-4 text-blue-400 align-top">{kd.assumption}</td>
                    <td className="py-3 text-zinc-400 align-top">
                      <div className="mb-1 text-zinc-300">{kd.valuation_impact}</div>
                      <div className="text-xs italic">Monitor: {kd.what_to_monitor}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Risks */}
      {risks && risks.length > 0 && (
        <Card title="Primary Risks">
          <div className="space-y-4">
            {risks.map((r, i) => (
              <div key={i} className="border-l-2 border-zinc-700 pl-4">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                    r.severity?.toLowerCase() === 'high' ? 'bg-red-500/20 text-red-400' :
                    r.severity?.toLowerCase() === 'medium' ? 'bg-amber-500/20 text-amber-400' :
                    'bg-zinc-700/50 text-zinc-300'
                  }`}>{r.severity}</span>
                  <span className="font-semibold text-zinc-200">{r.risk}</span>
                </div>
                <p className="text-zinc-400 text-sm mb-1">{r.mechanism}</p>
                <p className="text-zinc-500 text-xs italic">Monitor: {r.indicator_to_monitor}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      
      {/* Operating Fundamentals */}
      {report.operating_fundamentals && report.operating_fundamentals.length > 0 && (
        <Card title="Operating Fundamentals">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {report.operating_fundamentals.map((of, i) => (
              <div key={i} className="bg-zinc-950/50 p-3 rounded border border-zinc-800">
                <div className="text-xs text-zinc-500">{of.metric}</div>
                <div className="text-lg font-bold text-white">{of.current_value}</div>
                <div className="text-xs mt-1 text-zinc-400">{of.direction}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Scenarios */}
      {report.scenarios && (
        <Card title="Valuation Scenarios">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {['bear', 'base', 'bull'].map(s => {
              const sc = report.scenarios[s];
              if (!sc) return null;
              return (
                <div key={s} className="bg-zinc-950/50 p-4 rounded border border-zinc-800">
                  <div className="text-sm font-bold capitalize text-white mb-2">{s} Case</div>
                  <div className="text-xl font-bold text-blue-400 mb-2">{sc.fair_value}</div>
                  <ul className="text-xs text-zinc-400 space-y-1 mb-2">
                    <li>Rev Growth: {sc.revenue_growth}</li>
                    <li>Margin: {sc.ebit_margin}</li>
                    <li>WACC: {sc.wacc}</li>
                  </ul>
                  <p className="text-xs text-zinc-500">{sc.interpretation}</p>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* Valuation Triangulation */}
      {report.valuation_triangulation && (
        <Card title="Valuation Triangulation" className="bg-indigo-950/10 border-indigo-900/30">
          <div className="flex flex-col md:flex-row gap-6 mb-4">
            <div className="flex-1 text-center p-3 bg-zinc-900 rounded">
              <div className="text-xs text-zinc-500">DCF</div>
              <div className="font-bold text-white">{report.valuation_triangulation.dcf}</div>
            </div>
            <div className="flex-1 text-center p-3 bg-zinc-900 rounded">
              <div className="text-xs text-zinc-500">Monte Carlo</div>
              <div className="font-bold text-white">{report.valuation_triangulation.monte_carlo}</div>
            </div>
            <div className="flex-1 text-center p-3 bg-zinc-900 rounded">
              <div className="text-xs text-zinc-500">Market Price</div>
              <div className="font-bold text-white">{report.valuation_triangulation.market_price}</div>
            </div>
          </div>
          <p className="text-sm text-zinc-300">{report.valuation_triangulation.cross_method_interpretation}</p>
        </Card>
      )}

      {/* Model Quality & Conclusion */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card title="Model Quality Flags" className="bg-zinc-900">
          <ul className="space-y-2">
            {model_quality?.model_red_flags?.map((flag, i) => (
              <li key={i} className="flex gap-2 items-start text-zinc-400">
                <FiAlertTriangle className={`mt-0.5 flex-shrink-0 ${flag.severity?.toLowerCase() === 'high' ? 'text-red-400' : 'text-amber-400'}`} />
                <div>
                  <span className="text-zinc-300 block">{flag.issue}</span>
                  <span className="text-xs">{flag.why_it_matters}</span>
                </div>
              </li>
            ))}
            {(!model_quality?.model_red_flags || model_quality.model_red_flags.length === 0) && (
              <li className="flex gap-2 items-center text-green-400">
                <FiCheckCircle />
                <span>No major model red flags identified.</span>
              </li>
            )}
          </ul>
        </Card>

        <Card title="Final Synopsis" className="bg-zinc-900 border-zinc-700">
          <p className="text-zinc-200 leading-relaxed mb-4">
            {final_synopsis?.paragraph || exec?.key_takeaway || exec?.overview || 'Intrinsic valuation synthesis indicates cash flow dynamics support current fundamental estimates.'}
          </p>
          {((final_synopsis?.monitoring_points && final_synopsis.monitoring_points.length > 0) || (key_drivers && key_drivers.length > 0)) && (
            <div>
              <div className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Key Monitoring Points</div>
              <ul className="list-disc pl-4 space-y-1 text-zinc-400">
                {(final_synopsis?.monitoring_points && final_synopsis.monitoring_points.length > 0
                  ? final_synopsis.monitoring_points
                  : key_drivers?.slice(0, 3).map(d => `Monitor ${d.driver}: ${d.what_to_monitor}`) || []
                ).map((pt, i) => (
                  <li key={i}>{pt}</li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
