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
  const isEquityModel = Boolean(
    isFinancial ||
    data.company?.is_equity_model ||
    data.company?.model_type === 'CORPORATE_DDM' ||
    data.diagnostics?.is_equity_model ||
    data.dcf_result?.is_equity_model
  );
  const symbol = data.company?.symbol || (data.company?.currency === 'INR' ? '₹' : '$');
  const currentPrice = data.market_data?.current_price || 1;

  const defaultGrowth = data.diagnostics?.default_growth ?? (
    isEquityModel
      ? (data.historicals?.avg_ni_growth || data.historicals?.avg_rev_growth || 0.10)
      : (data.historicals?.revenue_cagr || data.historicals?.avg_rev_growth || 0.10)
  );
  
  const currentMargin = isEquityModel
    ? (data.diagnostics?.current_ebit_margin ?? data.historicals?.avg_roe ?? 0.14)
    : (data.diagnostics?.current_ebit_margin ?? data.historicals?.avg_ebit_margin ?? 0.18);
  const isNegativeMargin = !isEquityModel && currentMargin < 0;
  
  const defaultMargin = data.diagnostics?.default_margin ?? (
    isEquityModel
      ? (data.historicals?.avg_roe ?? 0.14)
      : (data.diagnostics?.target_ebit_margin ?? data.historicals?.avg_ebit_margin ?? 0.20)
  );
  
  const defaultWacc = data.diagnostics?.default_wacc ?? (
    isEquityModel
      ? (data.wacc?.cost_of_equity || data.wacc?.wacc || 0.10)
      : (data.wacc?.wacc || 0.10)
  );

  const defaultTgr = (data.macro?.terminal_growth ?? (data.company?.market === 'IN' ? 0.055 : 0.025)) * 100;
  const isIndia = data.company?.market === 'IN';
  const minTgr = 0.5;
  const maxTgr = isIndia ? 8.0 : 5.0;

  const appliedGrowth = data.overrides_applied?.revenue_growth != null ? data.overrides_applied.revenue_growth * 100 : defaultGrowth * 100;
  const appliedMargin = data.overrides_applied?.ebit_margin != null ? data.overrides_applied.ebit_margin * 100 : defaultMargin * 100;
  const appliedWacc = data.overrides_applied?.wacc != null ? data.overrides_applied.wacc * 100 : defaultWacc * 100;
  const appliedTgr = data.overrides_applied?.terminal_growth != null ? data.overrides_applied.terminal_growth * 100 : defaultTgr;

  const minGrowth = Math.min(-20, Math.floor(Math.min(defaultGrowth * 100, appliedGrowth) - 5));
  const maxGrowth = Math.max(60, Math.ceil(Math.max(defaultGrowth * 100, appliedGrowth) + 10));
  const minMargin = Math.min(isEquityModel ? 2 : -60, Math.floor(Math.min(defaultMargin * 100, appliedMargin) - 5));
  const maxMargin = Math.max(isFinancial ? 40 : isEquityModel ? 60 : 65, Math.ceil(Math.max(defaultMargin * 100, appliedMargin) + 5));
  const minWacc = Math.min(4, Math.floor(Math.min(defaultWacc * 100, appliedWacc) - 1));
  const maxWacc = Math.max(25, Math.ceil(Math.max(defaultWacc * 100, appliedWacc) + 5));

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
  }, [data.company?.ticker, data.company?.model_type, appliedGrowth, appliedMargin, appliedWacc, appliedTgr]);

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
    let clamped = Math.max(minGrowth, Math.min(maxGrowth, val));
    if (Math.abs(clamped - appliedGrowth) <= 0.08) clamped = appliedGrowth;
    setGrowth(clamped);
    notifyParent(clamped, margin, wacc, tgr);
  };

  const handleMarginChange = (val) => {
    let clamped = Math.max(minMargin, Math.min(maxMargin, val));
    if (Math.abs(clamped - appliedMargin) <= 0.08) clamped = appliedMargin;
    setMargin(clamped);
    notifyParent(growth, clamped, wacc, tgr);
  };

  const handleWaccChange = (val) => {
    let clamped = Math.max(minWacc, Math.min(maxWacc, val));
    if (Math.abs(clamped - appliedWacc) <= 0.08) clamped = appliedWacc;
    setWacc(clamped);
    notifyParent(growth, margin, clamped, tgr);
  };

  const handleTgrChange = (val) => {
    let clamped = Math.max(minTgr, Math.min(maxTgr, val));
    if (Math.abs(clamped - appliedTgr) <= 0.08) clamped = appliedTgr;
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
      g = Math.max(minGrowth, g - 3.5);
      m = Math.max(isEquityModel ? 6 : 5, m - 2.5);
      w = Math.min(maxWacc, w + 1.0);
      t = Math.max(minTgr, t - 0.5);
    } else if (preset === 'bull') {
      g = Math.min(maxGrowth, g + 4.0);
      m = Math.min(maxMargin, m + 2.5);
      w = Math.max(minWacc, w - 0.6);
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

  // Instant client-side DCF preview when dragging sliders (mirroring dcf_engine.py & bank_engine.py)
  const livePreview = useMemo(() => {
    const dcf = data.dcf_result;
    if (!dcf || dcf.implied_price == null) return null;

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
    const mNew = margin / 100;
    const wNew = Math.max(0.04, wacc / 100);
    const tNew = Math.max(0.005, tgr / 100);
    const years = dcf.projected_revenue?.length || 5;
    const shares = data.market_data?.shares_outstanding || 1;
    const market = data.company?.market || 'US';

    if (isEquityModel) {
      // Bank / Corporate DDM Engine mirroring bank_engine.py
      const hist = data.historicals || {};
      const diag = data.diagnostics || {};
      const niHist = hist.net_income || [];
      const validNi = niHist.filter((x) => x > 0);
      const baseNi = validNi.length > 0 ? validNi[validNi.length - 1] : (hist.revenue?.[hist.revenue.length - 1] || 1e9) * 0.15;

      const bveHist = hist.book_value || [];
      const validBve = bveHist.filter((x) => x > 0);
      const baseBve = validBve.length > 0 ? validBve[validBve.length - 1] : baseNi / 0.14;

      const currRoe = Number(diag.current_ebit_margin ?? hist.avg_roe ?? 0.14);
      const targetRoe = Math.max(0.05, Math.min(0.35, mNew));
      let baseRoe = Math.max(0.05, Math.min(0.35, currRoe));
      if (baseRoe < targetRoe * 0.90) baseRoe = targetRoe;

      const ke = wNew;
      const termG = Math.min(tNew, market === 'IN' ? 0.055 : 0.025);
      const stG = Math.max(-0.05, Math.min(0.35, gNew));

      let gSched;
      if (stG > termG + 0.06) {
        gSched = Array.from({ length: years }, (_, i) => {
          const step = i / years;
          return stG - (stG - termG) * Math.pow(step, 1.35);
        });
      } else {
        gSched = Array.from({ length: years }, (_, i) => stG + (termG - stG) * (i / Math.max(1, years - 1)));
      }

      const roeSched = Array.from({ length: years }, (_, i) => baseRoe + (targetRoe - baseRoe) * (i / Math.max(1, years - 1)));

      let curNi = baseNi;
      let curBve = baseBve;
      let pvFcfe = 0;
      let lastNi = 0;

      for (let i = 0; i < years; i++) {
        const yrG = gSched[i];
        const yrGNext = i + 1 < years ? gSched[i + 1] : termG;
        const roe = roeSched[i];
        curNi = curNi * (1 + yrG);

        const marginalRoe = Math.max(roe, targetRoe, yrG * 0.95);
        const retentionB = marginalRoe > 0 ? Math.min(0.85, Math.max(0.05, yrGNext / marginalRoe)) : 0.50;
        const reinvested = curNi * retentionB;
        const fcfe = curNi * (1 - retentionB);
        curBve += reinvested;

        pvFcfe += fcfe / Math.pow(1 + ke, i + 0.5);
        if (i === years - 1) lastNi = curNi;
      }

      const spread = ke - termG;
      let tv = 0;
      if (spread < 0.020) {
        const effTermG = Math.max(0.01, ke - 0.020);
        const termRoe = roeSched[years - 1];
        const termRet = termRoe > 0 ? Math.min(0.95, Math.max(0.05, effTermG / termRoe)) : 0.50;
        const termNi = lastNi * (1 + effTermG);
        const termFcfe = termNi * (1 - termRet);
        tv = termFcfe / 0.020;
      } else {
        const termRoe = roeSched[years - 1];
        const termRet = termRoe > 0 ? Math.min(0.95, Math.max(0.05, termG / termRoe)) : 0.50;
        const termNi = lastNi * (1 + termG);
        const termFcfe = termNi * (1 - termRet);
        tv = termFcfe / spread;
      }

      const pvTv = tv / Math.pow(1 + ke, years - 0.5);
      const eqVal = pvFcfe + pvTv;
      const simPrice = Math.max(0, eqVal / shares);

      return {
        isDirty: true,
        price: simPrice,
        upside: (simPrice / currentPrice) - 1,
      };
    }

    // Standard FCFF Engine mirroring dcf_engine.py
    const hist = data.historicals || {};
    const diag = data.diagnostics || {};
    const revHist = hist.revenue || [];
    const lastRev = hist.last_revenue || (revHist.length > 0 ? revHist[revHist.length - 1] : (dcf.projected_revenue?.[0] / (1 + (diag.default_growth || 0.10))) || 1);
    const taxRate = dcf.tax_rate ?? (market === 'IN' ? 0.2517 : 0.21);
    const nwcRatio = dcf.normalized_nwc_to_revenue || 0;

    const baseRev = dcf.projected_revenue || [];
    const baseDna = dcf.projected_dna || [];
    const baseCapex = dcf.projected_capex || [];
    const isExtractive = Boolean(dcf.is_extractive || diag.is_extractive);
    const isCyclical = Boolean(dcf.is_cyclical || diag.is_cyclical);

    let gSched;
    if (!isExtractive && !isCyclical && gNew > tNew + 0.10) {
      gSched = Array.from({ length: years }, (_, i) => {
        const step = i / years;
        return gNew - (gNew - tNew) * Math.pow(step, 1.35);
      });
    } else {
      gSched = Array.from({ length: years }, (_, i) => gNew + (tNew - gNew) * (i / Math.max(1, years - 1)));
    }

    const currM = diag.current_ebit_margin;
    let mSched;
    if (currM != null && Math.abs(currM - mNew) > 0.005) {
      mSched = Array.from({ length: years }, (_, i) => currM + (mNew - currM) * ((i + 1) / years));
    } else {
      mSched = Array.from({ length: years }, () => mNew);
    }

    const dnaPct = (baseRev[0] && baseDna[0]) ? baseDna[0] / baseRev[0] : (hist.avg_dna_pct || 0.04);
    const capexPcts = Array.from({ length: years }, (_, i) => {
      return (baseRev[i] && baseCapex[i]) ? baseCapex[i] / baseRev[i] : (hist.avg_capex_pct || 0.06);
    });

    let curRev = lastRev;
    let pvUfcf = 0;
    const projRev = [];
    for (let yr = 0; yr < years; yr++) {
      const nextRev = curRev * (1 + gSched[yr]);
      const marginVal = mSched[yr];
      const nopat = nextRev * marginVal * (1 - taxRate);
      const dnaAdd = nextRev * dnaPct;
      const capexSub = nextRev * capexPcts[yr];
      const deltaNwc = nwcRatio * (nextRev - curRev);
      const ufcf = nopat + dnaAdd - capexSub - deltaNwc;

      pvUfcf += ufcf / Math.pow(1 + wNew, yr + 0.5);
      projRev.push(nextRev);
      curRev = nextRev;
    }

    const maxGAllowed = isExtractive ? 0.025 : (market === 'IN' ? 0.050 : 0.025);
    const clampedT = Math.min(tNew, maxGAllowed);
    const minSpread = 0.025;
    const effT = (wNew - clampedT < minSpread) ? Math.max(0.01, wNew - minSpread) : clampedT;

    // Terminal Reinvestment Rate: scale backend calibrated rate proportionally with terminal growth
    const baseTgr = dcf.terminal_growth || (market === 'IN' ? 0.050 : 0.025);
    const baseReinv = dcf.terminal_reinv_rate ?? 0.30;
    const termReinvRate = Math.min(0.80, Math.max(0.06, baseReinv * (effT / Math.max(0.01, baseTgr))));

    const termNopat = projRev[years - 1] * (1 + effT) * mSched[years - 1] * (1 - taxRate);
    const termUfcf = termNopat * (1 - termReinvRate);

    // Institutional Exit Multiple Cross-Check for Cyclicals/Extractives
    const benchMult = dcf.benchmark_exit_multiple || 10.0;
    const termEbitda = projRev[years - 1] * (1 + effT) * (mSched[years - 1] + dnaPct);
    const exitTv = termEbitda > 0 ? termEbitda * benchMult : 0;

    const spread = wNew - effT;
    const gordonTv = termUfcf / Math.max(0.005, spread);
    let tv = gordonTv;
    if (isExtractive && exitTv > 0 && gordonTv > exitTv) {
      tv = 0.35 * gordonTv + 0.65 * exitTv;
    } else if (isCyclical && exitTv > 0 && gordonTv > exitTv) {
      tv = 0.45 * gordonTv + 0.55 * exitTv;
    }

    // Mid-year discount factor for TV matches backend discount_factors[-1] = (1 + w)^4.5
    const pvTv = tv / Math.pow(1 + wNew, years - 0.5);
    const simEv = pvUfcf + pvTv;

    const totalDebt = data.wacc?.total_debt || 0;
    const totalCash = data.wacc?.total_cash ?? data.company?.total_cash ?? 0;
    const simEq = Math.max(0, simEv - totalDebt + totalCash);
    const simPrice = Math.max(0, simEq / shares);

    return {
      isDirty: true,
      price: simPrice,
      upside: (simPrice / currentPrice) - 1,
    };
  }, [growth, margin, wacc, tgr, appliedGrowth, appliedMargin, appliedWacc, appliedTgr, data, currentPrice, isEquityModel]);

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
            ) : isEquityModel ? (
              <span className="text-[11px] font-semibold text-[#8ab4f8] block truncate">
                Corporate DDM / FCFE Mode
              </span>
            ) : (
              <span className="text-[11px] text-[#a6b0c3] block truncate">
                5-Year FCFF DCF Inputs
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
              {isEquityModel ? 'Net Income Growth (Yr 1)' : 'Rev Growth (Yr 1)'}
            </label>
            <div className="flex items-center bg-[#0d121a] px-2.5 py-1 rounded-lg border border-[#f4eedf]/15 focus-within:border-[#e3b23c] shrink-0">
              <input
                type="number"
                step="0.1"
                value={growth.toFixed(1)}
                onChange={(e) => handleGrowthChange(parseFloat(e.target.value) || 0)}
                className="bg-transparent text-right w-12 text-[#f4eedf] font-display font-bold tabular-nums text-sm focus:outline-none"
              />
              <span className="text-[#a6b0c3] text-xs ml-0.5">%</span>
            </div>
          </div>
          <input
            type="range"
            min={minGrowth}
            max={maxGrowth}
            step="0.1"
            value={growth}
            onChange={(e) => handleGrowthChange(parseFloat(e.target.value))}
            className="w-full warm-slider cursor-pointer"
          />
          <div className="flex flex-wrap justify-between gap-1 text-[11px] text-[#a6b0c3] mt-1.5 tabular-nums">
            <span>Hist Avg: {(defaultGrowth * 100).toFixed(1)}%</span>
            <span>Default: {(defaultGrowth * 100).toFixed(1)}%</span>
          </div>
        </div>

        {/* 2. Operating EBIT Margin / ROE */}
        <div>
          <div className="flex flex-wrap justify-between items-center gap-1.5 text-sm mb-2">
            <label className="text-[#f4eedf] font-semibold text-xs sm:text-sm min-w-0">
              {isEquityModel
                ? 'Target ROE'
                : isNegativeMargin
                ? 'Target EBIT Margin (Yr 5)'
                : 'EBIT Margin'}
            </label>
            <div className="flex items-center bg-[#0d121a] px-2.5 py-1 rounded-lg border border-[#f4eedf]/15 focus-within:border-[#e3b23c] shrink-0">
              <input
                type="number"
                step="0.1"
                value={margin.toFixed(1)}
                onChange={(e) => handleMarginChange(parseFloat(e.target.value) || 0)}
                className="bg-transparent text-right w-12 text-[#f4eedf] font-display font-bold tabular-nums text-sm focus:outline-none"
              />
              <span className="text-[#a6b0c3] text-xs ml-0.5">%</span>
            </div>
          </div>
          <input
            type="range"
            min={minMargin}
            max={maxMargin}
            step="0.1"
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
              {isEquityModel ? 'Cost of Equity (Ke)' : 'Discount Rate (WACC)'}
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
            min={minWacc}
            max={maxWacc}
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
            min={minTgr}
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

        {/* Normalized NWC / Revenue or Retention Rate */}
        {isEquityModel && data.dcf_result?.reinvestment_rate !== undefined ? (
          <div className="flex justify-between items-center text-xs pt-3.5 border-t border-[#f4eedf]/10">
            <span className="text-[#a6b0c3] font-medium">Equity Retention Rate (b = g / ROE)</span>
            <span className="text-[#f4eedf] font-display font-bold tabular-nums">
              {(data.dcf_result.reinvestment_rate * 100).toFixed(1)}%
            </span>
          </div>
        ) : data.diagnostics?.normalized_nwc_to_revenue !== undefined ? (
          <div className="flex justify-between items-center text-xs pt-3.5 border-t border-[#f4eedf]/10">
            <span className="text-[#a6b0c3] font-medium">Normalized NWC / Revenue</span>
            <span className="text-[#f4eedf] font-display font-bold tabular-nums">
              {(data.diagnostics.normalized_nwc_to_revenue * 100).toFixed(1)}%
            </span>
          </div>
        ) : null}

      </div>
    </div>
  );
}
