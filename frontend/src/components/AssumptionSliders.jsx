import React, { useState, useEffect, useMemo } from 'react';
import { FiRefreshCw, FiRotateCcw, FiTrendingUp, FiTrendingDown, FiSliders } from 'react-icons/fi';

export default function AssumptionSliders({ 
  data, 
  onOverride, 
  onApply, 
  onReset, 
  loading 
}) {
  if (!data) return null;

  const isFinancial = Boolean(data.company?.is_financial || data.diagnostics?.is_financial);
  const symbol = data.company?.symbol || (data.company?.currency === 'INR' ? '₹' : '$');
  const currentPrice = data.market_data?.current_price || 1;

  const defaultGrowth = isFinancial
    ? (data.historicals?.avg_ni_growth || data.historicals?.avg_rev_growth || 0.10)
    : (data.historicals?.revenue_cagr || data.historicals?.avg_rev_growth || 0.10);
  
  const currentMargin = isFinancial
    ? (data.diagnostics?.current_ebit_margin ?? data.historicals?.avg_roe ?? 0.14)
    : (data.diagnostics?.current_ebit_margin ?? data.historicals?.avg_ebit_margin ?? 0.18);
  const isNegativeMargin = !isFinancial && currentMargin < 0;
  
  const defaultMargin = isFinancial
    ? (data.historicals?.avg_roe ?? 0.14)
    : (data.diagnostics?.target_ebit_margin ?? data.historicals?.avg_ebit_margin ?? 0.20);
  
  const defaultWacc = isFinancial
    ? (data.wacc?.cost_of_equity || data.wacc?.wacc || 0.10)
    : (data.wacc?.wacc || 0.10);

  const defaultTgr = (data.macro?.terminal_growth ?? (data.company?.market === 'IN' ? 0.055 : 0.025)) * 100;
  const isIndia = data.company?.market === 'IN';
  const maxTgr = isIndia ? 8.0 : 5.0;

  const appliedGrowth = data.overrides_applied?.revenue_growth != null ? data.overrides_applied.revenue_growth * 100 : defaultGrowth * 100;
  const appliedMargin = data.overrides_applied?.ebit_margin != null ? data.overrides_applied.ebit_margin * 100 : defaultMargin * 100;
  const appliedWacc = data.overrides_applied?.wacc != null ? data.overrides_applied.wacc * 100 : defaultWacc * 100;
  const appliedTgr = data.overrides_applied?.terminal_growth != null ? data.overrides_applied.terminal_growth * 100 : defaultTgr;

  const [growth, setGrowth] = useState(() => appliedGrowth);
  const [margin, setMargin] = useState(() => appliedMargin);
  const [wacc, setWacc] = useState(() => appliedWacc);
  const [tgr, setTgr] = useState(() => appliedTgr);
  const [activePreset, setActivePreset] = useState('base');

  useEffect(() => {
    setGrowth(appliedGrowth);
    setMargin(appliedMargin);
    setWacc(appliedWacc);
    setTgr(appliedTgr);
    const hasCustom = data.overrides_applied && Object.keys(data.overrides_applied).length > 0;
    setActivePreset(hasCustom ? 'custom' : 'base');
  }, [data.company?.ticker, appliedGrowth, appliedMargin, appliedWacc, appliedTgr]);

  const notifyParent = (g, m, w, t, preset = 'custom') => {
    setActivePreset(preset);
    const payload = {
      revenue_growth: g / 100,
      ebit_margin: m / 100,
      wacc: w / 100,
      terminal_growth: t / 100,
      projection_years: 5
    };
    if (onOverride) onOverride(payload);
    return payload;
  };

  const handleGrowthChange = (val) => {
    const clamped = Math.max(-20, Math.min(50, val));
    setGrowth(clamped);
    notifyParent(clamped, margin, wacc, tgr);
  };

  const handleMarginChange = (val) => {
    const clamped = Math.max(isFinancial ? 2 : -60, Math.min(isFinancial ? 40 : 65, val));
    setMargin(clamped);
    notifyParent(growth, clamped, wacc, tgr);
  };

  const handleWaccChange = (val) => {
    const clamped = Math.max(4, Math.min(25, val));
    setWacc(clamped);
    notifyParent(growth, margin, clamped, tgr);
  };

  const handleTgrChange = (val) => {
    const clamped = Math.max(0.5, Math.min(maxTgr, val));
    setTgr(clamped);
    notifyParent(growth, margin, wacc, clamped);
  };

  const handleResetLocalAndServer = () => {
    const g = defaultGrowth * 100;
    const m = defaultMargin * 100;
    const w = defaultWacc * 100;
    const t = defaultTgr;
    setGrowth(g);
    setMargin(m);
    setWacc(w);
    setTgr(t);
    setActivePreset('base');
    if (onReset) onReset();
  };

  const applyPreset = (preset) => {
    let g = defaultGrowth * 100;
    let m = defaultMargin * 100;
    let w = defaultWacc * 100;
    let t = defaultTgr;

    if (preset === 'bear') {
      g = Math.max(-10, g - 3.5);
      m = Math.max(isFinancial ? 6 : 5, m - 2.5);
      w = Math.min(22, w + 1.0);
      t = Math.max(1.5, t - 0.5);
    } else if (preset === 'bull') {
      g = Math.min(40, g + 4.0);
      m = Math.min(isFinancial ? 32 : 55, m + 2.5);
      w = Math.max(5.5, w - 0.6);
      t = Math.min(maxTgr - 0.3, t + 0.4);
    }

    setGrowth(g);
    setMargin(m);
    setWacc(w);
    setTgr(t);
    notifyParent(g, m, w, t, preset);
  };

  // Check if current slider state differs from default baseline
  const isModifiedFromDefault =
    Math.abs(growth - defaultGrowth * 100) > 0.05 ||
    Math.abs(margin - defaultMargin * 100) > 0.05 ||
    Math.abs(wacc - defaultWacc * 100) > 0.05 ||
    Math.abs(tgr - defaultTgr) > 0.05 ||
    (data.overrides_applied && Object.keys(data.overrides_applied).length > 0);

  // Instant client-side DCF preview when dragging sliders
  const livePreview = useMemo(() => {
    const dcf = data.dcf_result;
    if (!dcf || !dcf.implied_price) return null;

    const isDirty =
      Math.abs(growth - appliedGrowth) > 0.05 ||
      Math.abs(margin - appliedMargin) > 0.05 ||
      Math.abs(wacc - appliedWacc) > 0.05 ||
      Math.abs(tgr - appliedTgr) > 0.05;

    if (!isDirty) {
      return {
        isDirty: false,
        price: dcf.implied_price,
        upside: (dcf.implied_price / currentPrice) - 1,
      };
    }

    const gNew = growth / 100;
    const gOld = appliedGrowth / 100;
    const mNew = Math.max(0.01, margin / 100);
    const mOld = Math.max(0.01, appliedMargin / 100);
    const wNew = Math.max(0.04, wacc / 100);
    const tNew = Math.min(wNew - 0.01, tgr / 100);

    const years = dcf.projected_ufcf?.length || 5;
    const baseUfcfList = dcf.projected_ufcf || [];
    const marginRatio = mNew / mOld;

    let pvUfcf = 0;
    let lastUfcf = 0;
    for (let i = 0; i < years; i++) {
      const yearIdx = i + 1;
      const fadeWeight = i / Math.max(1, years - 1);
      const stepGNew = gNew * (1 - fadeWeight * 0.5) + tNew * (fadeWeight * 0.5);
      const stepGOld = gOld * (1 - fadeWeight * 0.5) + (appliedTgr / 100) * (fadeWeight * 0.5);
      const growthCompoundRatio = Math.pow((1 + stepGNew) / Math.max(0.5, 1 + stepGOld), yearIdx);
      const simUfcf = (baseUfcfList[i] || 0) * growthCompoundRatio * marginRatio;
      const midYearPeriod = i + 0.5;
      pvUfcf += simUfcf / Math.pow(1 + wNew, midYearPeriod);
      if (i === years - 1) lastUfcf = simUfcf;
    }

    const tv = (lastUfcf * (1 + tNew)) / Math.max(0.015, wNew - tNew);
    const pvTv = tv / Math.pow(1 + wNew, years);
    const simEv = pvUfcf + pvTv;

    const totalDebt = data.wacc?.total_debt || 0;
    const totalCash = data.wacc?.total_cash ?? data.company?.total_cash ?? 0;
    const shares = data.market_data?.shares_outstanding || 1;

    const simEq = isFinancial ? simEv : Math.max(0, simEv - totalDebt + totalCash);
    const simPrice = Math.max(0, simEq / shares);

    return {
      isDirty: true,
      price: simPrice,
      upside: (simPrice / currentPrice) - 1,
    };
  }, [growth, margin, wacc, tgr, appliedGrowth, appliedMargin, appliedWacc, appliedTgr, data, currentPrice, isFinancial]);

  return (
    <div className="bg-[#141b26] rounded-2xl p-4 sm:p-5 border border-[#f4eedf]/10 shadow-xl space-y-4 sm:space-y-5 overflow-hidden">
      {/* Header & Scenario Presets */}
      <div className="flex flex-wrap items-center justify-between gap-2.5 pb-3.5 border-b border-[#f4eedf]/10">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-[#0d121a] border border-[#f4eedf]/12 flex items-center justify-center text-[#e3b23c] shrink-0">
            <FiSliders className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <h3 className="font-display font-bold text-[#f4eedf] text-base tracking-tight truncate">
              Model Assumptions
            </h3>
            {isFinancial ? (
              <span className="text-[11px] font-semibold text-[#34b38a] block truncate">
                Bank FCFE / ROE Mode
              </span>
            ) : (
              <span className="text-[11px] text-[#a6b0c3] block truncate">
                5-Year DCF Inputs
              </span>
            )}
          </div>
        </div>

        {/* Scenario Pill Switcher */}
        <div className="inline-flex items-center bg-[#0d121a] p-1 rounded-lg border border-[#f4eedf]/10 text-[11px] font-semibold shrink-0">
          {[
            { id: 'bear', label: 'Bear' },
            { id: 'base', label: 'Base' },
            { id: 'bull', label: 'Bull' },
          ].map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => applyPreset(p.id)}
              className={`px-2.5 py-1 rounded-md transition cursor-pointer ${
                activePreset === p.id
                  ? 'bg-[#e3b23c] text-[#0f141c] font-bold'
                  : 'text-[#a6b0c3] hover:text-[#f4eedf]'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Live Preview Banner when Sliders are Adjusted */}
      {livePreview && (
        <div className={`flex flex-wrap items-center justify-between gap-2 px-3.5 py-2.5 rounded-xl border transition-all ${
          livePreview.isDirty
            ? 'bg-[#141b26] border border-[#f4eedf]/20 shadow-sm'
            : 'bg-[#0d121a]/80 border-[#f4eedf]/10'
        }`}>
          <span className="text-xs font-medium text-[#a6b0c3] whitespace-nowrap">
            {livePreview.isDirty ? 'Live Simulated Value:' : 'Model Fair Value:'}
          </span>
          <div className="flex items-center gap-2 shrink-0">
            <span className="font-display font-bold text-sm sm:text-base text-[#f4eedf] tabular-nums">
              {symbol}{livePreview.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
            <span className={`inline-flex items-center gap-0.5 text-xs font-bold tabular-nums ${
              livePreview.upside >= 0 ? 'text-[#34b38a]' : 'text-[#e07a5f]'
            }`}>
              {livePreview.upside >= 0 ? <FiTrendingUp /> : <FiTrendingDown />}
              {Math.abs(livePreview.upside * 100).toFixed(1)}%
            </span>
          </div>
        </div>
      )}

      {/* Action Buttons: Re-run Analysis & Return to Default (Restore Defaults) */}
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={() => onApply && onApply({
            revenue_growth: growth / 100,
            ebit_margin: margin / 100,
            wacc: wacc / 100,
            terminal_growth: tgr / 100,
            projection_years: 5
          })}
          disabled={loading}
          className={`flex items-center justify-center gap-1.5 py-2.5 px-2.5 sm:px-3 rounded-xl text-[11px] sm:text-xs font-bold transition cursor-pointer text-center leading-tight ${
            livePreview?.isDirty
              ? 'bg-[#e3b23c] hover:bg-[#ecc052] text-[#0f141c] shadow-lg shadow-[#e3b23c]/20'
              : 'bg-[#f4eedf] hover:bg-white text-[#0f141c]'
          }`}
        >
          <FiRefreshCw className={`w-3.5 h-3.5 shrink-0 ${loading ? 'animate-spin' : ''}`} />
          <span className="truncate">Re-run Analysis</span>
        </button>

        <button
          type="button"
          onClick={handleResetLocalAndServer}
          disabled={loading}
          className={`flex items-center justify-center gap-1.5 py-2.5 px-2.5 sm:px-3 rounded-xl text-[11px] sm:text-xs font-bold border transition cursor-pointer text-center leading-tight ${
            isModifiedFromDefault
              ? 'bg-[#e07a5f]/15 hover:bg-[#e07a5f]/25 text-[#f4eedf] border-[#e07a5f]/40'
              : 'bg-[#0d121a] hover:bg-[#1c2534] text-[#a6b0c3] hover:text-[#f4eedf] border-[#f4eedf]/12'
          }`}
        >
          <FiRotateCcw className="w-3.5 h-3.5 shrink-0" />
          <span className="truncate">Restore Defaults</span>
        </button>
      </div>

      {/* 4 Compact Sliders (Numbers-Forward, Zero Paragraph Clutter) */}
      <div className="space-y-4 sm:space-y-5 pt-1">
        
        {/* 1. Revenue Growth */}
        <div>
          <div className="flex flex-wrap justify-between items-center gap-1.5 text-sm mb-2">
            <label className="text-[#f4eedf] font-semibold text-xs sm:text-sm min-w-0">
              {isFinancial ? 'Net Income Growth (Yr 1)' : 'Rev Growth (Yr 1)'}
            </label>
            <div className="flex items-center bg-[#0d121a] px-2.5 py-1 rounded-lg border border-[#f4eedf]/15 focus-within:border-[#e3b23c] shrink-0">
              <input
                type="number"
                step="0.5"
                value={growth.toFixed(1)}
                onChange={(e) => handleGrowthChange(parseFloat(e.target.value) || 0)}
                className="bg-transparent text-right w-12 text-[#f4eedf] font-display font-bold tabular-nums text-sm focus:outline-none"
              />
              <span className="text-[#a6b0c3] text-xs ml-0.5">%</span>
            </div>
          </div>
          <input
            type="range"
            min="-10"
            max="40"
            step="0.5"
            value={growth}
            onChange={(e) => handleGrowthChange(parseFloat(e.target.value))}
            className="w-full warm-slider cursor-pointer"
          />
          <div className="flex flex-wrap justify-between gap-1 text-[11px] text-[#a6b0c3] mt-1.5 tabular-nums">
            <span>Hist CAGR: {(defaultGrowth * 100).toFixed(1)}%</span>
            <span>Default: {(defaultGrowth * 100).toFixed(1)}%</span>
          </div>
        </div>

        {/* 2. Operating EBIT Margin / ROE */}
        <div>
          <div className="flex flex-wrap justify-between items-center gap-1.5 text-sm mb-2">
            <label className="text-[#f4eedf] font-semibold text-xs sm:text-sm min-w-0">
              {isFinancial
                ? 'Target ROE'
                : isNegativeMargin
                ? 'Target EBIT Margin (Yr 5)'
                : 'EBIT Margin'}
            </label>
            <div className="flex items-center bg-[#0d121a] px-2.5 py-1 rounded-lg border border-[#f4eedf]/15 focus-within:border-[#e3b23c] shrink-0">
              <input
                type="number"
                step="0.5"
                value={margin.toFixed(1)}
                onChange={(e) => handleMarginChange(parseFloat(e.target.value) || 0)}
                className="bg-transparent text-right w-12 text-[#f4eedf] font-display font-bold tabular-nums text-sm focus:outline-none"
              />
              <span className="text-[#a6b0c3] text-xs ml-0.5">%</span>
            </div>
          </div>
          <input
            type="range"
            min={isFinancial ? '5' : '-30'}
            max={isFinancial ? '35' : '60'}
            step="0.5"
            value={margin}
            onChange={(e) => handleMarginChange(parseFloat(e.target.value))}
            className="w-full warm-slider cursor-pointer"
          />
          <div className="flex flex-wrap justify-between gap-1 text-[11px] text-[#a6b0c3] mt-1.5 tabular-nums">
            <span>Current: {(currentMargin * 100).toFixed(1)}%</span>
            <span>Default: {(defaultMargin * 100).toFixed(1)}%</span>
          </div>
        </div>

        {/* 3. Discount Rate (WACC / Ke) */}
        <div>
          <div className="flex flex-wrap justify-between items-center gap-1.5 text-sm mb-2">
            <label className="text-[#f4eedf] font-semibold text-xs sm:text-sm min-w-0">
              {isFinancial ? 'Cost of Equity (Ke)' : 'Discount Rate (WACC)'}
            </label>
            <div className="flex items-center bg-[#0d121a] px-2.5 py-1 rounded-lg border border-[#f4eedf]/15 focus-within:border-[#e3b23c] shrink-0">
              <input
                type="number"
                step="0.1"
                value={wacc.toFixed(1)}
                onChange={(e) => handleWaccChange(parseFloat(e.target.value) || 0)}
                className="bg-transparent text-right w-12 text-[#f4eedf] font-display font-bold tabular-nums text-sm focus:outline-none"
              />
              <span className="text-[#a6b0c3] text-xs ml-0.5">%</span>
            </div>
          </div>
          <input
            type="range"
            min="5"
            max="25"
            step="0.1"
            value={wacc}
            onChange={(e) => handleWaccChange(parseFloat(e.target.value))}
            className="w-full warm-slider cursor-pointer"
          />
          <div className="text-[11px] text-[#a6b0c3] mt-1.5 tabular-nums flex flex-col gap-1">
            <div className="flex flex-wrap justify-between gap-1">
              <span>Computed: {(defaultWacc * 100).toFixed(1)}%</span>
              {data.market_data?.beta && (
                <span>Beta: {data.market_data.beta.toFixed(2)}</span>
              )}
            </div>
            {data.diagnostics?.wacc_floored && (
              <span className="text-[#e3b23c] text-xs font-medium block">
                ⚠️ {data.diagnostics.wacc_note}
              </span>
            )}
            {data.diagnostics?.ke_floored && (
              <span className="text-[#e3b23c] text-xs font-medium block">
                {data.diagnostics.ke_note}
              </span>
            )}
          </div>
        </div>

        {/* 4. Terminal Growth */}
        <div>
          <div className="flex flex-wrap justify-between items-center gap-1.5 text-sm mb-2">
            <label className="text-[#f4eedf] font-semibold text-xs sm:text-sm min-w-0">
              Terminal Growth (g)
            </label>
            <div className="flex items-center bg-[#0d121a] px-2.5 py-1 rounded-lg border border-[#f4eedf]/15 focus-within:border-[#e3b23c] shrink-0">
              <input
                type="number"
                step="0.1"
                value={tgr.toFixed(1)}
                onChange={(e) => handleTgrChange(parseFloat(e.target.value) || 0)}
                className="bg-transparent text-right w-12 text-[#f4eedf] font-display font-bold tabular-nums text-sm focus:outline-none"
              />
              <span className="text-[#a6b0c3] text-xs ml-0.5">%</span>
            </div>
          </div>
          <input
            type="range"
            min="1"
            max={maxTgr}
            step="0.1"
            value={tgr}
            onChange={(e) => handleTgrChange(parseFloat(e.target.value))}
            className="w-full warm-slider cursor-pointer"
          />
          <div className="flex flex-wrap justify-between gap-1 text-[11px] text-[#a6b0c3] mt-1.5 tabular-nums">
            <span>Max Cap: {maxTgr.toFixed(1)}%</span>
            <span>Default: {defaultTgr.toFixed(1)}%</span>
          </div>
        </div>

        {/* Normalized NWC / Revenue */}
        {data.diagnostics?.normalized_nwc_to_revenue !== undefined && (
          <div className="flex justify-between items-center text-xs pt-3.5 border-t border-[#f4eedf]/10">
            <span className="text-[#a6b0c3] font-medium">Normalized NWC / Revenue</span>
            <span className="text-[#f4eedf] font-display font-bold tabular-nums">
              {(data.diagnostics.normalized_nwc_to_revenue * 100).toFixed(1)}%
            </span>
          </div>
        )}

      </div>
    </div>
  );
}
