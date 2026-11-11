import React, { useState, useEffect, useRef, useMemo } from 'react';
import axios from 'axios';
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createSeriesMarkers,
  ColorType,
  CrosshairMode,
  LineStyle,
} from 'lightweight-charts';
import {
  FiActivity,
  FiAlertTriangle,
  FiCheckCircle,
  FiClock,
  FiInfo,
  FiLayers,
  FiRefreshCw,
  FiShield,
  FiSliders,
  FiTarget,
  FiTrendingUp,
} from 'react-icons/fi';
import { MODEL_VERSION } from '../version';

const formatNum = (val, decimals = 2) => {
  if (val == null || Number.isNaN(Number(val))) return 'N/A';
  return Number(val).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
};

const formatCompactVol = (val) => {
  if (val == null || Number.isNaN(Number(val))) return '0';
  const n = Math.abs(Number(val));
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e7) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toFixed(0);
};

const computeLocalPositionSizing = ({
  capital,
  riskPct,
  maxWeightPct,
  entryPrice,
  stopPrice,
  costBps,
  market,
}) => {
  const mkt = (market || 'US').toUpperCase();
  const tickSize = mkt === 'IN' ? 0.05 : 0.01;
  const roundTick = (p) => Number((Math.round(p / tickSize) * tickSize).toFixed(2));

  const cap = Number(capital);
  const entry = roundTick(Number(entryPrice));
  const stop = roundTick(Number(stopPrice));
  const bps = Math.max(0, Number(costBps) || 0);

  if (!cap || cap <= 0 || !entry || entry <= 0) {
    return { valid: false, error: 'Portfolio capital and entry price must be positive.' };
  }
  if (!stop || stop <= 0) {
    return { valid: false, error: 'Stop-loss price must be greater than zero.' };
  }
  if (stop >= entry) {
    return {
      valid: false,
      wrongSideStop: true,
      error: `Wrong-side stop: Stop price (${stop.toFixed(2)}) must be strictly below Entry price (${entry.toFixed(2)}) for a long position.`,
    };
  }

  const riskFrac = Math.max(0.0005, Math.min(0.20, (Number(riskPct) || 1.0) / 100));
  const maxWtFrac = Math.max(0.01, Math.min(1.0, (Number(maxWeightPct) || 10.0) / 100));
  const halfCostFrac = bps / 10000 / 2;

  const entryEff = entry * (1 + halfCostFrac);
  const stopEff = stop * (1 - halfCostFrac);
  const riskPerShare = entryEff - stopEff;

  const riskBudgetAmt = cap * riskFrac;
  const maxPosAmt = cap * maxWtFrac;

  const sharesByRisk = Math.max(0, Math.floor(riskBudgetAmt / riskPerShare));
  const sharesByCap = Math.max(0, Math.floor(maxPosAmt / entryEff));
  const shares = Math.min(sharesByRisk, sharesByCap);
  const cappedByWeight = sharesByCap < sharesByRisk;

  const positionValue = shares * entry;
  const portfolioWeightPct = (positionValue / cap) * 100;
  const estFrictionCost = positionValue * (bps / 10000);
  const maxLossAmt = shares * riskPerShare;
  const maxLossPct = (maxLossAmt / cap) * 100;
  const rDist = entry - stop;

  return {
    valid: true,
    wrongSideStop: false,
    tickSize,
    entryPrice: entry,
    stopPrice: stop,
    stopDistancePct: ((entry - stop) / entry) * 100,
    riskPerShare,
    riskBudgetAmt,
    shares,
    sharesByRisk,
    cappedByWeight,
    positionValue,
    portfolioWeightPct,
    estFrictionCost,
    maxLossAmt,
    maxLossPct,
    targets: {
      r1: roundTick(entry + 1 * rDist),
      r2: roundTick(entry + 2 * rDist),
      r3: roundTick(entry + 3 * rDist),
    },
  };
};

const TechnicalWorkspace = ({ ticker, market, analysisData, onSwitchToFundamental }) => {
  const [timeframe, setTimeframe] = useState('1D');
  const [rangePreset, setRangePreset] = useState('1Y');
  const [taData, setTaData] = useState(null);
  const [taLoading, setTaLoading] = useState(false);
  const [taError, setTaError] = useState(null);

  // Overlay & Pane toggles
  const [showSma, setShowSma] = useState(true);
  const [showEma, setShowEma] = useState(false);
  const [showBollinger, setShowBollinger] = useState(true);
  const [avwapAnchor, setAvwapAnchor] = useState('ytd'); // 'none' | 'ytd' | 'high_52w' | 'low_52w' | 'swing_low'
  const [showSrLevels, setShowSrLevels] = useState(true);
  const [showVolumeProfile, setShowVolumeProfile] = useState(true);
  const [showFairValueLine, setShowFairValueLine] = useState(true);
  const [showCorpActions, setShowCorpActions] = useState(true);
  const [activeSubPane, setActiveSubPane] = useState('rsi'); // 'rsi' | 'macd' | 'atr'
  const [showMinerviniModal, setShowMinerviniModal] = useState(false);
  const [activeTaTab, setActiveTaTab] = useState('chart'); // 'chart' | 'matrix' | 'regime' | 'backtest'

  // Phase 3 Signal Backtester State
  const [btData, setBtData] = useState(null);
  const [btLoading, setBtLoading] = useState(false);
  const [btError, setBtError] = useState(null);
  const [btCostInput, setBtCostInput] = useState('');
  const [btHorizonFilter, setBtHorizonFilter] = useState('all'); // 'all' | 5 | 10 | 20 | 60
  const [btLabelFilter, setBtLabelFilter] = useState('all'); // 'all' | 'Historically favourable' | 'No reliable edge' | 'Insufficient evidence'
  const [expandedTestId, setExpandedTestId] = useState(null);

  // Position Calculator State
  const [posCapital, setPosCapital] = useState(100000);
  const [posRiskPct, setPosRiskPct] = useState(1.0);
  const [posMaxWeightPct, setPosMaxWeightPct] = useState(10.0);
  const [posEntryPrice, setPosEntryPrice] = useState(0);
  const [stopMethod, setStopMethod] = useState('atr_2'); // 'atr_1_5' | 'atr_2' | 'atr_3' | 'swing_low' | 'support' | 'manual'
  const [posStopPrice, setPosStopPrice] = useState(0);
  const [posCostBps, setPosCostBps] = useState(10);

  // Chart DOM refs
  const mainChartContainerRef = useRef(null);
  const subChartContainerRef = useRef(null);
  const mainChartInstanceRef = useRef(null);
  const subChartInstanceRef = useRef(null);
  const [crosshairInfo, setCrosshairInfo] = useState(null);

  const activeSymbol = analysisData?.company?.ticker || ticker || 'AAPL';
  const activeMarket = analysisData?.company?.market || market || 'auto';
  const activeFairValue = analysisData?.dcf_result?.implied_price;
  const activeVerdict = analysisData?.verdict?.verdict;
  const activeMethodLabel = useMemo(() => {
    if (!analysisData?.company) return 'Enterprise DCF (FCFF)';
    if (analysisData.company.is_financial) return 'Tier-1 Banking DDM/FCFE';
    if (analysisData.company.is_equity_model) return 'Corporate DDM / FCFE';
    return 'Enterprise DCF (FCFF)';
  }, [analysisData]);

  // Fetch `/api/technical/chart` lazily only when inside TechnicalWorkspace
  const fetchTechnicalChart = async (tf = timeframe) => {
    if (!activeSymbol) return;
    setTaLoading(true);
    setTaError(null);
    try {
      const params = {
        symbol: activeSymbol,
        market: activeMarket,
        timeframe: tf,
        period: '10y',
      };
      if (activeFairValue != null) params.fair_value = activeFairValue;
      if (activeVerdict) params.verdict = activeVerdict;
      if (activeMethodLabel) params.active_method = activeMethodLabel;

      const resp = await axios.get('/api/technical/chart', { params });
      const data = resp.data;
      setTaData(data);

      // Initialize position sizing defaults when ticker changes
      const defs = data?.position_sizing_defaults;
      if (defs) {
        setPosCapital(defs.default_capital || (data.market === 'IN' ? 1000000 : 100000));
        setPosCostBps(defs.default_cost_bps || (data.market === 'IN' ? 30 : 10));
        const closeP = defs.latest_close || 100;
        const atrP = defs.atr_14 || closeP * 0.02;
        setPosEntryPrice(closeP);
        setPosStopPrice(Number(Math.max(0.05, closeP - 2.0 * atrP).toFixed(2)));
        setStopMethod('atr_2');
      }
    } catch (err) {
      const msg =
        err.response?.data?.detail ||
        err.message ||
        'Failed to load technical history.';
      setTaError(msg);
    } finally {
      setTaLoading(false);
    }
  };

  useEffect(() => {
    fetchTechnicalChart(timeframe);
    // Reset cached backtest when symbol/market changes so it re-fetches cleanly
    setBtData(null);
    setBtCostInput('');
    setExpandedTestId(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSymbol, activeMarket, timeframe, activeFairValue, activeVerdict]);

  // Fetch `/api/technical/backtest` lazily when the Backtester tab is opened or cost_bps is updated
  const fetchTechnicalBacktest = async (overrideCostBps = null) => {
    if (!activeSymbol) return;
    setBtLoading(true);
    setBtError(null);
    try {
      const params = {
        symbol: activeSymbol,
        market: activeMarket,
        period: '10y',
      };
      if (overrideCostBps !== null && overrideCostBps !== '' && !Number.isNaN(Number(overrideCostBps))) {
        params.cost_bps = Math.max(0, Math.min(500, Number(overrideCostBps)));
      }
      const resp = await axios.get('/api/technical/backtest', { params });
      const btPayload = resp.data?.backtest || null;
      setBtData(btPayload);
      if (btPayload?.round_trip_cost_bps != null) {
        setBtCostInput(String(btPayload.round_trip_cost_bps));
      }
    } catch (err) {
      const msg =
        err.response?.data?.detail ||
        err.message ||
        'Failed to run per-stock signal backtest.';
      setBtError(msg);
    } finally {
      setBtLoading(false);
    }
  };

  useEffect(() => {
    if (activeTaTab === 'backtest' && !btData && !btLoading) {
      fetchTechnicalBacktest();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTaTab, activeSymbol, activeMarket]);

  // Update stop price automatically when user switches stop method preset
  const handleStopMethodChange = (method) => {
    setStopMethod(method);
    const defs = taData?.position_sizing_defaults;
    const entry = Number(posEntryPrice) || defs?.latest_close || 100;
    const atr = defs?.atr_14 || entry * 0.02;
    const tick = taData?.market === 'IN' ? 0.05 : 0.01;
    const roundT = (v) => Number((Math.round(v / tick) * tick).toFixed(2));

    if (method === 'atr_1_5') {
      setPosStopPrice(roundT(Math.max(tick, entry - 1.5 * atr)));
    } else if (method === 'atr_2') {
      setPosStopPrice(roundT(Math.max(tick, entry - 2.0 * atr)));
    } else if (method === 'atr_3') {
      setPosStopPrice(roundT(Math.max(tick, entry - 3.0 * atr)));
    } else if (method === 'swing_low' && defs?.last_confirmed_swing_low) {
      setPosStopPrice(roundT(defs.last_confirmed_swing_low));
    } else if (method === 'support' && defs?.nearest_support_price) {
      setPosStopPrice(roundT(defs.nearest_support_price));
    }
  };

  const posCalc = useMemo(
    () =>
      computeLocalPositionSizing({
        capital: posCapital,
        riskPct: posRiskPct,
        maxWeightPct: posMaxWeightPct,
        entryPrice: posEntryPrice,
        stopPrice: posStopPrice,
        costBps: posCostBps,
        market: taData?.market || activeMarket,
      }),
    [posCapital, posRiskPct, posMaxWeightPct, posEntryPrice, posStopPrice, posCostBps, taData?.market, activeMarket]
  );

  // Build & Synchronize Lightweight Charts v5 Main Chart + Sub-Pane
  useEffect(() => {
    if (!taData?.chart?.bars?.length || !mainChartContainerRef.current) return;

    const chartPayload = taData.chart;
    const bars = chartPayload.bars;
    const dates = chartPayload.dates;
    const overlays = chartPayload.overlays || {};
    const panes = chartPayload.panes || {};
    const currSym = taData.currency_symbol || (taData.market === 'IN' ? '₹' : '$');

    // Clean up previous instances
    if (mainChartInstanceRef.current) {
      mainChartInstanceRef.current.remove();
      mainChartInstanceRef.current = null;
    }
    if (subChartInstanceRef.current) {
      subChartInstanceRef.current.remove();
      subChartInstanceRef.current = null;
    }

    const mainEl = mainChartContainerRef.current;
    const mainChart = createChart(mainEl, {
      width: mainEl.clientWidth || 800,
      height: window.innerWidth < 640 ? 340 : 440,
      layout: {
        background: { type: ColorType.Solid, color: '#0d121a' },
        textColor: '#a6b0c3',
        fontFamily: 'Plus Jakarta Sans, sans-serif',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(244, 238, 223, 0.05)' },
        horzLines: { color: 'rgba(244, 238, 223, 0.05)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: 'rgba(244, 238, 223, 0.12)',
        scaleMargins: { top: 0.08, bottom: 0.22 },
      },
      timeScale: {
        borderColor: 'rgba(244, 238, 223, 0.12)',
        timeVisible: false,
      },
    });
    mainChartInstanceRef.current = mainChart;

    // 1. Candlestick Series
    const candleSeries = mainChart.addSeries(CandlestickSeries, {
      upColor: '#34b38a',
      downColor: '#e07a5f',
      borderUpColor: '#34b38a',
      borderDownColor: '#e07a5f',
      wickUpColor: '#34b38a',
      wickDownColor: '#e07a5f',
    });
    candleSeries.setData(
      bars.map((b) => ({
        time: b.time,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }))
    );

    // 2. Volume Histogram (Bottom 20% of Main Chart)
    const volSeries = mainChart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume_scale',
    });
    mainChart.priceScale('volume_scale').applyOptions({
      scaleMargins: { top: 0.80, bottom: 0.0 },
    });
    volSeries.setData(
      bars.map((b) => ({
        time: b.time,
        value: b.volume,
        color: b.close >= b.open ? 'rgba(52, 179, 138, 0.28)' : 'rgba(224, 122, 95, 0.28)',
      }))
    );

    const buildLineSeriesData = (arr) => {
      if (!Array.isArray(arr)) return [];
      const out = [];
      for (let i = 0; i < dates.length; i += 1) {
        if (arr[i] != null && !Number.isNaN(Number(arr[i]))) {
          out.push({ time: dates[i], value: Number(arr[i]) });
        }
      }
      return out;
    };

    // 3. Moving Averages (SMA 20 / 50 / 200 & EMA 20 / 50)
    if (showSma) {
      const sma20Series = mainChart.addSeries(LineSeries, {
        color: '#8ab4f8',
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      sma20Series.setData(buildLineSeriesData(overlays.sma20));

      const sma50Series = mainChart.addSeries(LineSeries, {
        color: '#e3b23c',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      sma50Series.setData(buildLineSeriesData(overlays.sma50));

      const sma200Series = mainChart.addSeries(LineSeries, {
        color: '#c084fc',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      sma200Series.setData(buildLineSeriesData(overlays.sma200));
    }

    if (showEma) {
      const ema20Series = mainChart.addSeries(LineSeries, {
        color: '#38bdf8',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      ema20Series.setData(buildLineSeriesData(overlays.ema20));

      const ema50Series = mainChart.addSeries(LineSeries, {
        color: '#fb923c',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      ema50Series.setData(buildLineSeriesData(overlays.ema50));
    }

    // 4. Bollinger Bands (20, 2)
    if (showBollinger && overlays.bollinger) {
      const bbUpper = mainChart.addSeries(LineSeries, {
        color: 'rgba(138, 180, 248, 0.45)',
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      bbUpper.setData(buildLineSeriesData(overlays.bollinger.upper));

      const bbLower = mainChart.addSeries(LineSeries, {
        color: 'rgba(138, 180, 248, 0.45)',
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      bbLower.setData(buildLineSeriesData(overlays.bollinger.lower));
    }

    // 5. Anchored VWAP (YTD / 52W High / 52W Low / Swing Low)
    if (avwapAnchor !== 'none' && overlays.avwap?.[avwapAnchor]?.values) {
      const avwapSeries = mainChart.addSeries(LineSeries, {
        color: '#f472b6',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        title: `AVWAP (${overlays.avwap[avwapAnchor].label.replace(' Anchor', '')})`,
      });
      avwapSeries.setData(buildLineSeriesData(overlays.avwap[avwapAnchor].values));
    }

    // 6. Confirmed Support & Resistance Price Lines + Volume Profile POC
    if (showSrLevels && chartPayload.support_resistance?.levels) {
      chartPayload.support_resistance.levels.forEach((lv) => {
        candleSeries.createPriceLine({
          price: lv.price,
          color: lv.role === 'support' ? 'rgba(52, 179, 138, 0.65)' : 'rgba(224, 122, 95, 0.65)',
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `${lv.role === 'support' ? 'Sup' : 'Res'} (${lv.touches}x)`,
        });
      });
    }

    if (showVolumeProfile && chartPayload.volume_profile?.poc_price) {
      candleSeries.createPriceLine({
        price: chartPayload.volume_profile.poc_price,
        color: 'rgba(91, 143, 217, 0.85)',
        lineWidth: 1,
        lineStyle: LineStyle.SparseDotted,
        axisLabelVisible: true,
        title: 'VP POC (est.)',
      });
    }

    // 7. Model Fair Value Horizontal Line ("Model fair value (FCFF/DDM, v2.5.0, <date>)")
    const fcCard = taData?.headline_cards?.fundamental_context;
    if (showFairValueLine && fcCard?.fair_value != null && fcCard.fair_value > 0) {
      candleSeries.createPriceLine({
        price: Number(fcCard.fair_value),
        color: '#e3b23c',
        lineWidth: 2,
        lineStyle: LineStyle.LargeDashed,
        axisLabelVisible: true,
        title: `Fair Value (${currSym}${formatNum(fcCard.fair_value)})`,
      });
    }

    // 8. Split & Dividend Markers
    if (showCorpActions && chartPayload.corporate_actions) {
      const dateSet = new Set(dates);
      const markers = [];
      (chartPayload.corporate_actions.splits || []).forEach((sp) => {
        if (dateSet.has(sp.date)) {
          markers.push({
            time: sp.date,
            position: 'aboveBar',
            color: '#e3b23c',
            shape: 'arrowDown',
            text: sp.label,
          });
        }
      });
      (chartPayload.corporate_actions.dividends || []).slice(-16).forEach((dv) => {
        if (dateSet.has(dv.date)) {
          markers.push({
            time: dv.date,
            position: 'belowBar',
            color: '#8ab4f8',
            shape: 'circle',
            text: `Div ${currSym}${dv.amount}`,
          });
        }
      });
      markers.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
      if (markers.length > 0) {
        createSeriesMarkers(candleSeries, markers);
      }
    }

    // Apply Range Preset
    const applyVisibleRange = (chartInstance) => {
      if (!dates.length) return;
      const presetMap = {
        '3M': 63,
        '6M': 126,
        '1Y': 252,
        '3Y': 756,
        '5Y': 1260,
        '10Y': dates.length,
      };
      let barCount = presetMap[rangePreset] || 252;
      if (timeframe === '1W') barCount = Math.ceil(barCount / 5);
      if (timeframe === '1M') barCount = Math.ceil(barCount / 21);
      const fromIdx = Math.max(0, dates.length - barCount);
      chartInstance.timeScale().setVisibleRange({
        from: dates[fromIdx],
        to: dates[dates.length - 1],
      });
    };
    applyVisibleRange(mainChart);

    // Crosshair Legend Listener
    const lastIdx = bars.length - 1;
    setCrosshairInfo({
      ...bars[lastIdx],
      sma50: overlays.sma50?.[lastIdx],
      sma200: overlays.sma200?.[lastIdx],
      rsi14: panes.rsi14?.[lastIdx],
    });

    mainChart.subscribeCrosshairMove((param) => {
      if (!param?.time) {
        setCrosshairInfo({
          ...bars[lastIdx],
          sma50: overlays.sma50?.[lastIdx],
          sma200: overlays.sma200?.[lastIdx],
          rsi14: panes.rsi14?.[lastIdx],
        });
        return;
      }
      const idx = dates.indexOf(param.time);
      if (idx >= 0) {
        setCrosshairInfo({
          ...bars[idx],
          sma50: overlays.sma50?.[idx],
          sma200: overlays.sma200?.[idx],
          rsi14: panes.rsi14?.[idx],
        });
      }
    });

    // 9. Sub-Pane Chart (RSI 14 / MACD / ATR 14)
    if (subChartContainerRef.current) {
      const subEl = subChartContainerRef.current;
      const subChart = createChart(subEl, {
        width: subEl.clientWidth || 800,
        height: 155,
        layout: {
          background: { type: ColorType.Solid, color: '#0d121a' },
          textColor: '#a6b0c3',
          fontFamily: 'Plus Jakarta Sans, sans-serif',
          fontSize: 11,
        },
        grid: {
          vertLines: { color: 'rgba(244, 238, 223, 0.05)' },
          horzLines: { color: 'rgba(244, 238, 223, 0.05)' },
        },
        rightPriceScale: {
          borderColor: 'rgba(244, 238, 223, 0.12)',
          scaleMargins: { top: 0.12, bottom: 0.12 },
        },
        timeScale: {
          borderColor: 'rgba(244, 238, 223, 0.12)',
          visible: true,
        },
      });
      subChartInstanceRef.current = subChart;

      if (activeSubPane === 'rsi') {
        const rsiSeries = subChart.addSeries(LineSeries, {
          color: '#e3b23c',
          lineWidth: 2,
          title: 'RSI(14)',
        });
        rsiSeries.setData(buildLineSeriesData(panes.rsi14));
        rsiSeries.createPriceLine({
          price: 70,
          color: 'rgba(224, 122, 95, 0.5)',
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: '70',
        });
        rsiSeries.createPriceLine({
          price: 30,
          color: 'rgba(52, 179, 138, 0.5)',
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: '30',
        });
      } else if (activeSubPane === 'macd' && panes.macd) {
        const histSeries = subChart.addSeries(HistogramSeries, {
          title: 'Hist',
        });
        const histData = [];
        for (let i = 0; i < dates.length; i += 1) {
          const v = panes.macd.histogram?.[i];
          if (v != null && !Number.isNaN(Number(v))) {
            histData.push({
              time: dates[i],
              value: Number(v),
              color: Number(v) >= 0 ? 'rgba(52, 179, 138, 0.55)' : 'rgba(224, 122, 95, 0.55)',
            });
          }
        }
        histSeries.setData(histData);

        const macdLine = subChart.addSeries(LineSeries, {
          color: '#8ab4f8',
          lineWidth: 2,
          title: 'MACD(12,26)',
        });
        macdLine.setData(buildLineSeriesData(panes.macd.macd));

        const sigLine = subChart.addSeries(LineSeries, {
          color: '#e07a5f',
          lineWidth: 1,
          title: 'Signal(9)',
        });
        sigLine.setData(buildLineSeriesData(panes.macd.signal));
      } else if (activeSubPane === 'atr') {
        const atrSeries = subChart.addSeries(LineSeries, {
          color: '#34b38a',
          lineWidth: 2,
          title: 'ATR(14)',
        });
        atrSeries.setData(buildLineSeriesData(panes.atr14));
      }

      applyVisibleRange(subChart);

      // Sync horizontal time scales between main chart and sub chart
      mainChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (range && subChartInstanceRef.current) {
          subChartInstanceRef.current.timeScale().setVisibleLogicalRange(range);
        }
      });
    }

    const handleResize = () => {
      if (mainChartContainerRef.current && mainChartInstanceRef.current) {
        mainChartInstanceRef.current.applyOptions({
          width: mainChartContainerRef.current.clientWidth,
        });
      }
      if (subChartContainerRef.current && subChartInstanceRef.current) {
        subChartInstanceRef.current.applyOptions({
          width: subChartContainerRef.current.clientWidth,
        });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (mainChartInstanceRef.current) {
        mainChartInstanceRef.current.remove();
        mainChartInstanceRef.current = null;
      }
      if (subChartInstanceRef.current) {
        subChartInstanceRef.current.remove();
        subChartInstanceRef.current = null;
      }
    };
  }, [
    taData,
    timeframe,
    rangePreset,
    showSma,
    showEma,
    showBollinger,
    avwapAnchor,
    showSrLevels,
    showVolumeProfile,
    showFairValueLine,
    showCorpActions,
    activeSubPane,
    activeTaTab,
  ]);

  const currSym = taData?.currency_symbol || (analysisData?.company?.currency === 'INR' ? '₹' : '$');
  const cards = taData?.headline_cards || {};
  const tcCard = cards.technical_condition || {};
  const tsCard = cards.trend_stage || {};
  const klCard = cards.key_levels || {};
  const fcCard = cards.fundamental_context || {};
  const vpData = taData?.chart?.volume_profile;
  const metaData = taData?.data || {};

  const updatedTimeStr = useMemo(() => {
    if (!taData?.computed_at) return '';
    try {
      const d = new Date(taData.computed_at);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return taData.computed_at;
    }
  }, [taData?.computed_at]);

  // Monte Carlo Intrinsic Value Distribution Data (from analysisData or fcCard)
  const mcHist = analysisData?.monte_carlo?.histogram || fcCard.mc_histogram;
  const mcStats = analysisData?.monte_carlo?.stats || fcCard.mc_stats || {};
  const mcSimPrices = analysisData?.monte_carlo?.simulated_prices || [];
  const latestClose = klCard.nearest_support ? fcCard.current_price : (taData?.position_sizing_defaults?.latest_close || analysisData?.market_data?.current_price || 0);
  const pricePercentile = useMemo(() => {
    if (fcCard.price_percentile_in_mc != null) return fcCard.price_percentile_in_mc;
    if (Array.isArray(mcSimPrices) && mcSimPrices.length > 0 && latestClose > 0) {
      const below = mcSimPrices.filter((p) => p <= latestClose).length;
      return Math.round((below / mcSimPrices.length) * 100);
    }
    return null;
  }, [fcCard.price_percentile_in_mc, mcSimPrices, latestClose]);

  if (taLoading && !taData) {
    return (
      <div className="bg-[#141b26] rounded-2xl p-8 border border-[#f4eedf]/10 text-center space-y-3">
        <div className="w-10 h-10 mx-auto rounded-full border-3 border-[#e3b23c]/20 border-t-[#e3b23c] animate-spin" />
        <div className="font-display font-bold text-base text-[#f4eedf]">
          Loading 10-Year Split &amp; Total-Return History for {activeSymbol}...
        </div>
        <p className="text-xs text-[#a6b0c3]">
          Computing causal swing S/R levels, 24-bin Volume Profile, Anchored VWAPs &amp; Wilder indicators...
        </p>
      </div>
    );
  }

  if (taError && !taData) {
    return (
      <div className="bg-[#2c1618] border border-[#e07a5f]/50 rounded-2xl p-6 text-[#f4eedf] space-y-3">
        <div className="flex items-center gap-2 font-display font-bold text-base text-[#e07a5f]">
          <FiAlertTriangle className="w-5 h-5" />
          <span>Technical Analysis History Unavailable</span>
        </div>
        <p className="text-xs sm:text-sm text-[#f4eedf]/85">{taError}</p>
        <div className="flex items-center gap-3 pt-1">
          <button
            type="button"
            onClick={() => fetchTechnicalChart(timeframe)}
            className="px-4 py-2 rounded-xl bg-[#e3b23c] text-[#0f141c] text-xs font-bold cursor-pointer"
          >
            Retry Fetch
          </button>
          {onSwitchToFundamental && (
            <button
              type="button"
              onClick={onSwitchToFundamental}
              className="px-4 py-2 rounded-xl bg-[#141b26] border border-[#f4eedf]/15 text-xs font-bold text-[#f4eedf] cursor-pointer"
            >
              Return to Fundamental DCF
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 text-[#f4eedf]">
      {/* 1. DATA PROVENANCE & QUALITY BANNER */}
      <div className="bg-[#121824] rounded-xl px-4 py-2.5 border border-white/[0.08] flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          <span className="px-2 py-0.5 rounded bg-[#e3b23c]/15 text-[#e3b23c] border border-[#e3b23c]/30 font-mono font-bold text-[11px]">
            TA v0.2 · {tcCard.score_version || 'ta-score-v0.2'}
          </span>
          <span className="text-[#c5cedd]">
            Listing: <strong className="text-[#f4eedf] font-mono">{taData?.listing_used}</strong>
          </span>
          <span className="text-white/20">·</span>
          <span className="text-[#c5cedd]">
            Benchmark: <strong className="text-[#8ab4f8] font-mono">{taData?.benchmark}</strong>
          </span>
          <span className="text-white/20">·</span>
          <span className="text-[#c5cedd]">
            Last Session: <strong className="text-[#f4eedf] font-mono">{metaData.last_session || 'N/A'}</strong>
          </span>
          {metaData.is_forming_daily_bar && (
            <span className="px-2 py-0.5 rounded bg-[#5b8fd9]/15 text-[#8ab4f8] text-[10px] font-bold">
              Intraday Forming Bar
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2.5 text-[11px] text-[#a6b0c3]">
          <span>
            Basis: <strong className="text-[#f4eedf]">Split-Adj OHLC</strong> (Chart/Levels)
          </span>
          <span className="text-white/20">·</span>
          <span className="inline-flex items-center gap-1">
            <FiClock className="w-3 h-3 text-[#e3b23c]" />
            <span>Updated {updatedTimeStr}</span>
            {taData?.cached && <span className="text-[#34b38a] font-mono">(cached)</span>}
          </span>
          <span
            className={`px-2 py-0.5 rounded font-bold uppercase text-[10px] ${
              metaData.quality_status === 'complete'
                ? 'bg-[#34b38a]/15 text-[#34b38a] border border-[#34b38a]/30'
                : metaData.quality_status === 'stale'
                ? 'bg-[#e3b23c]/15 text-[#e3b23c] border border-[#e3b23c]/30'
                : 'bg-[#e07a5f]/15 text-[#e07a5f] border border-[#e07a5f]/30'
            }`}
          >
            Quality: {metaData.quality_status || 'complete'}
          </span>
        </div>
      </div>

      {/* Data Quality Warnings Banner (if any warnings exist) */}
      {metaData.warnings?.length > 0 && (
        <div className="bg-[#141b26] border border-[#e3b23c]/35 rounded-xl px-4 py-3 text-xs text-[#c5cedd] flex items-start gap-2.5">
          <FiAlertTriangle className="w-4 h-4 text-[#e3b23c] shrink-0 mt-0.5" />
          <div className="space-y-1">
            <div className="font-bold text-[#f4eedf]">Data Quality &amp; Provenance Notes:</div>
            <ul className="list-disc list-inside space-y-0.5 text-[11px] text-[#a6b0c3]">
              {metaData.warnings.map((w, idx) => (
                <li key={idx}>{w}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* 2. FOUR HEADLINE CARDS (2x2 on Tablet, 1x4 on Mobile, 4x1 on Desktop) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {/* Card 1: Technical Condition (Live Two-Stage v0.2 Score + Coverage Gate) */}
        <div className="bg-[#141b26] rounded-2xl p-4 sm:p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
          <div className="flex items-center justify-between gap-2 mb-1">
            <span className="text-xs font-bold uppercase tracking-wider text-[#a6b0c3] truncate">
              Technical Condition
            </span>
            <span className="px-2 py-0.5 rounded bg-[#e3b23c]/15 text-[#e3b23c] border border-[#e3b23c]/30 text-[10px] font-mono font-bold shrink-0">
              {tcCard.score_version || tcCard.badge || 'ta-score-v0.2'}
            </span>
          </div>
          {tcCard.status === 'available' && tcCard.score_mtf != null ? (
            <>
              <div className="flex items-baseline justify-between gap-2 my-1">
                <div
                  className={`font-display text-lg sm:text-xl font-bold truncate ${
                    tcCard.condition_tone === 'emerald'
                      ? 'text-[#34b38a]'
                      : tcCard.condition_tone === 'rose'
                      ? 'text-[#e07a5f]'
                      : 'text-[#e3b23c]'
                  }`}
                  title={tcCard.headline}
                >
                  {tcCard.headline || `Technical condition: ${tcCard.condition_short || 'Neutral'}`}
                </div>
                <div className="font-display text-2xl sm:text-3xl font-bold text-[#f4eedf] tabular-nums shrink-0">
                  {Number(tcCard.score_mtf).toFixed(1)}
                  <span className="text-xs text-[#818ea4] font-normal">/100</span>
                </div>
              </div>
              <div className="space-y-1.5 mt-1">
                <div className="w-full h-1.5 rounded-full bg-[#0d121a] overflow-hidden">
                  <div
                    className={`h-full ${
                      tcCard.condition_tone === 'emerald'
                        ? 'bg-[#34b38a]'
                        : tcCard.condition_tone === 'rose'
                        ? 'bg-[#e07a5f]'
                        : 'bg-[#e3b23c]'
                    }`}
                    style={{ width: `${Math.min(100, Math.max(0, tcCard.score_mtf))}%` }}
                  />
                </div>
                <div className="flex items-center justify-between text-[11px] text-[#a6b0c3] font-mono tabular-nums">
                  <span>
                    D: <strong className="text-[#f4eedf]">{tcCard.score_d ?? '—'}</strong> · W:{' '}
                    <strong className="text-[#f4eedf]">{tcCard.score_w ?? '—'}</strong> · M:{' '}
                    <strong className="text-[#f4eedf]">{tcCard.score_m ?? '—'}</strong>
                  </span>
                  <button
                    type="button"
                    onClick={() => setActiveTaTab('matrix')}
                    className="text-[#8ab4f8] hover:underline font-sans font-semibold cursor-pointer"
                  >
                    Matrix →
                  </button>
                </div>
              </div>
            </>
          ) : (
            <>
              <div className="font-display text-base sm:text-lg font-bold text-[#a6b0c3] my-1">
                {tcCard.headline || `Score unavailable (coverage ${tcCard.coverage_pct ?? 0}%)`}
              </div>
              <div className="space-y-1.5 mt-1">
                <div className="flex items-center justify-between text-xs text-[#a6b0c3]">
                  <span>Pillar Coverage Gate (≥70% req):</span>
                  <strong className="text-[#e3b23c] font-mono">{tcCard.coverage_pct ?? 0}%</strong>
                </div>
                <div className="w-full h-1.5 rounded-full bg-[#0d121a] overflow-hidden">
                  <div
                    className="h-full bg-[#e3b23c]"
                    style={{ width: `${tcCard.coverage_pct ?? 0}%` }}
                  />
                </div>
                <div className="text-[11px] text-[#818ea4] font-mono tabular-nums">
                  {tcCard.daily_bars || 0}D · {tcCard.weekly_bars || 0}W · {tcCard.monthly_returns || 0}M returns
                </div>
              </div>
            </>
          )}
        </div>

        {/* Card 2: Trend Stage Preview (Weinstein + Minervini) */}
        <div className="bg-[#141b26] rounded-2xl p-4 sm:p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
          <div className="flex items-center justify-between gap-2 mb-1">
            <span className="text-xs font-bold uppercase tracking-wider text-[#a6b0c3] truncate">
              Trend Stage (Preview)
            </span>
            {tsCard.eligible ? (
              <button
                type="button"
                onClick={() => setShowMinerviniModal(!showMinerviniModal)}
                className="text-[11px] font-semibold text-[#8ab4f8] hover:underline cursor-pointer shrink-0"
              >
                Minervini: {tsCard.minervini_passed}/{tsCard.minervini_total}
              </button>
            ) : (
              <span className="text-[10px] text-[#e07a5f] font-bold">Insufficient History</span>
            )}
          </div>
          <div
            className={`font-display text-xl sm:text-2xl font-bold my-1 truncate ${
              tsCard.weinstein_stage === 2
                ? 'text-[#34b38a]'
                : tsCard.weinstein_stage === 4
                ? 'text-[#e07a5f]'
                : 'text-[#e3b23c]'
            }`}
          >
            {tsCard.stage_label || 'Insufficient History'}
          </div>
          {tsCard.eligible ? (
            <div className="text-xs text-[#a6b0c3] flex flex-wrap items-center justify-between gap-2 tabular-nums">
              <span>
                200-DMA: <strong className="text-[#f4eedf]">{currSym}{formatNum(tsCard.sma200)}</strong>{' '}
                <span className={tsCard.price_vs_sma200_pct >= 0 ? 'text-[#34b38a]' : 'text-[#e07a5f]'}>
                  ({tsCard.price_vs_sma200_pct >= 0 ? '+' : ''}{tsCard.price_vs_sma200_pct}%)
                </span>
              </span>
              <span>
                30W Slope: <strong className="text-[#f4eedf]">{tsCard.sma30w_slope_4w_pct >= 0 ? '+' : ''}{tsCard.sma30w_slope_4w_pct}%</strong>
              </span>
            </div>
          ) : (
            <div className="text-xs text-[#a6b0c3]">{tsCard.message}</div>
          )}
        </div>

        {/* Card 3: Key Levels (Support / Resistance / POC — est. from daily bars) */}
        <div className="bg-[#141b26] rounded-2xl p-4 sm:p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
          <div className="flex items-center justify-between gap-2 mb-1">
            <span className="text-xs font-bold uppercase tracking-wider text-[#a6b0c3] truncate">
              Key Levels
            </span>
            <span className="text-[10px] font-mono text-[#818ea4] bg-[#0d121a] px-2 py-0.5 rounded border border-white/[0.06] shrink-0">
              {klCard.approximation_label || 'est. from daily bars'}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2 my-1 text-center">
            <div className="bg-[#0d121a] rounded-lg p-1.5 border border-white/[0.06]">
              <div className="text-[10px] text-[#34b38a] font-bold uppercase">Support</div>
              <div className="font-display font-bold text-xs sm:text-sm text-[#f4eedf] tabular-nums mt-0.5">
                {klCard.nearest_support ? `${currSym}${formatNum(klCard.nearest_support.price)}` : 'N/A'}
              </div>
            </div>
            <div className="bg-[#0d121a] rounded-lg p-1.5 border border-white/[0.06]">
              <div className="text-[10px] text-[#8ab4f8] font-bold uppercase">VP POC</div>
              <div className="font-display font-bold text-xs sm:text-sm text-[#f4eedf] tabular-nums mt-0.5">
                {klCard.poc_price ? `${currSym}${formatNum(klCard.poc_price)}` : 'N/A'}
              </div>
            </div>
            <div className="bg-[#0d121a] rounded-lg p-1.5 border border-white/[0.06]">
              <div className="text-[10px] text-[#e07a5f] font-bold uppercase">Resist.</div>
              <div className="font-display font-bold text-xs sm:text-sm text-[#f4eedf] tabular-nums mt-0.5">
                {klCard.nearest_resistance ? `${currSym}${formatNum(klCard.nearest_resistance.price)}` : 'N/A'}
              </div>
            </div>
          </div>
          <div className="text-xs text-[#a6b0c3] flex items-center justify-between tabular-nums">
            <span>
              ATR(14): <strong className="text-[#f4eedf]">{currSym}{formatNum(klCard.atr_14)}</strong>{' '}
              {klCard.atr_pct != null && <span>({klCard.atr_pct}%)</span>}
            </span>
            {klCard.val_price && klCard.vah_price && (
              <span className="text-[11px] text-[#818ea4]">
                VA: {currSym}{formatNum(klCard.val_price, 0)}–{currSym}{formatNum(klCard.vah_price, 0)}
              </span>
            )}
          </div>
        </div>

        {/* Card 4: Fundamental Context (Active Fair Value, ATR Distance & Qualified Valuation Outlook) */}
        <div className="bg-[#141b26] rounded-2xl p-4 sm:p-5 border border-[#e3b23c]/25 shadow-lg flex flex-col justify-between">
          <div className="flex items-center justify-between gap-2 mb-1">
            <span className="text-xs font-bold uppercase tracking-wider text-[#e3b23c] truncate">
              Fundamental Context
            </span>
            <span className="text-[10px] font-semibold text-[#a6b0c3] shrink-0">
              {fcCard.active_method || 'Enterprise DCF'}
            </span>
          </div>
          {fcCard.fair_value != null ? (
            <>
              <div className="flex items-baseline justify-between gap-2 my-1">
                <div>
                  <span className="text-[10px] text-[#a6b0c3] block">Intrinsic Fair Value</span>
                  <span className="font-display text-2xl sm:text-3xl font-bold text-[#e3b23c] tabular-nums">
                    {currSym}{formatNum(fcCard.fair_value)}
                  </span>
                </div>
                <div className="text-right tabular-nums">
                  <span
                    className={`text-xs font-bold block ${
                      (fcCard.upside_to_fair_value_pct || 0) >= 0 ? 'text-[#34b38a]' : 'text-[#e07a5f]'
                    }`}
                  >
                    {(fcCard.upside_to_fair_value_pct || 0) >= 0 ? '▲' : '▼'}{' '}
                    {Math.abs(fcCard.upside_to_fair_value_pct || 0).toFixed(1)}% vs Price
                  </span>
                  {fcCard.distance_in_atr_units != null && (
                    <span className="text-[11px] text-[#a6b0c3] font-mono block mt-0.5">
                      {fcCard.distance_in_atr_units >= 0 ? '+' : ''}
                      {fcCard.distance_in_atr_units}× ATR(14) dist.
                    </span>
                  )}
                </div>
              </div>
              <div className="text-xs font-bold pt-1 border-t border-white/[0.08] flex items-center justify-between gap-2">
                <span
                  className={
                    fcCard.raw_verdict?.includes('BULLISH')
                      ? 'text-[#34b38a]'
                      : fcCard.raw_verdict?.includes('BEARISH')
                      ? 'text-[#e07a5f]'
                      : 'text-[#e3b23c]'
                  }
                >
                  {fcCard.valuation_outlook_label || `Valuation outlook: ${fcCard.raw_verdict || 'NEUTRAL'}`}
                </span>
                {pricePercentile != null && (
                  <span className="text-[11px] text-[#8ab4f8] font-mono">
                    Price at P{pricePercentile}
                  </span>
                )}
              </div>
            </>
          ) : (
            <div className="text-xs text-[#a6b0c3] my-auto">
              Run DCF analysis to overlay Intrinsic Fair Value &amp; Monte Carlo quantiles.
            </div>
          )}
        </div>
      </div>

      {/* Expandable Minervini 8-Point Trend Template Drawer */}
      {showMinerviniModal && tsCard.minervini_checks && (
        <div className="bg-[#141b26] rounded-2xl p-4 border border-[#8ab4f8]/30 space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="font-display font-bold text-xs sm:text-sm text-[#f4eedf]">
              Minervini 8-Point SEPA Trend Template Checklist ({tsCard.minervini_passed}/{tsCard.minervini_total} Passed)
            </span>
            <button
              type="button"
              onClick={() => setShowMinerviniModal(false)}
              className="text-xs text-[#a6b0c3] hover:text-[#f4eedf] cursor-pointer"
            >
              Close
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 text-xs">
            {tsCard.minervini_checks.map((ch) => (
              <div
                key={ch.id}
                className={`p-2.5 rounded-xl border flex items-center gap-2 ${
                  ch.passed
                    ? 'bg-[#34b38a]/10 border-[#34b38a]/30 text-[#f4eedf]'
                    : 'bg-[#0d121a] border-white/[0.06] text-[#a6b0c3]'
                }`}
              >
                <span className={ch.passed ? 'text-[#34b38a] font-bold' : 'text-[#e07a5f] font-bold'}>
                  {ch.passed ? '✓' : '✗'}
                </span>
                <span>{ch.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TA WORKSPACE SUB-NAVIGATION TABS (Phase 2: Chart | Indicator Matrix | Regime & Confluence) */}
      <div className="bg-[#141b26] rounded-2xl p-1.5 border border-[#f4eedf]/10 shadow-lg flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1">
          {[
            { id: 'chart', label: 'Price Chart & Position Sizing', icon: <FiTrendingUp className="w-3.5 h-3.5" /> },
            { id: 'matrix', label: 'Indicator Matrix (D / W / M)', icon: <FiSliders className="w-3.5 h-3.5" /> },
            { id: 'regime', label: 'Regime, RS & Confluence Matrix', icon: <FiLayers className="w-3.5 h-3.5" /> },
            { id: 'backtest', label: 'Signal Backtester (40 Tests)', icon: <FiTarget className="w-3.5 h-3.5" /> },
          ].map((tab) => {
            const isActive = activeTaTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTaTab(tab.id)}
                className={`flex items-center gap-2 py-2 px-3.5 rounded-xl text-xs sm:text-sm font-bold transition-all cursor-pointer select-none ${
                  isActive
                    ? 'bg-[#e3b23c] text-[#0f141c] shadow-sm'
                    : 'text-[#a6b0c3] hover:text-[#f4eedf] hover:bg-[#0d121a]/60'
                }`}
              >
                {tab.icon}
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>
        <div className="hidden md:flex items-center gap-2 pr-3 text-[11px] text-[#a6b0c3]">
          <span>Two-Stage Composite:</span>
          <strong className="text-[#e3b23c] font-mono">0.50·D + 0.35·W + 0.15·M</strong>
          <span className="text-white/20">·</span>
          <span>Completed W/M bars only</span>
        </div>
      </div>

      {activeTaTab === 'chart' && (
        <>
      {/* 3. INTERACTIVE CHART + VOLUME PROFILE SIDEBAR */}
      <div className="bg-[#141b26] rounded-2xl p-4 sm:p-5 border border-[#f4eedf]/10 shadow-xl space-y-3">
        {/* Top Chart Controls Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-white/[0.08]">
          {/* Left: Timeframe (D/W/M) + Range Presets */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-xl bg-[#0d121a] p-1 border border-white/[0.08]">
              {['1D', '1W', '1M'].map((tf) => (
                <button
                  key={tf}
                  type="button"
                  onClick={() => setTimeframe(tf)}
                  className={`px-2.5 py-1 rounded-lg text-xs font-bold transition cursor-pointer ${
                    timeframe === tf
                      ? 'bg-[#e3b23c] text-[#0f141c]'
                      : 'text-[#a6b0c3] hover:text-[#f4eedf]'
                  }`}
                >
                  {tf}
                </button>
              ))}
            </div>

            <div className="inline-flex rounded-xl bg-[#0d121a] p-1 border border-white/[0.08]">
              {['3M', '6M', '1Y', '3Y', '5Y', '10Y'].map((rng) => (
                <button
                  key={rng}
                  type="button"
                  onClick={() => setRangePreset(rng)}
                  className={`px-2 py-1 rounded-lg text-[11px] font-semibold transition cursor-pointer ${
                    rangePreset === rng
                      ? 'bg-[#1f2b3e] text-[#e3b23c]'
                      : 'text-[#a6b0c3] hover:text-[#f4eedf]'
                  }`}
                >
                  {rng}
                </button>
              ))}
            </div>
          </div>

          {/* Right: Overlay Toggles & AVWAP Selector */}
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <button
              type="button"
              onClick={() => setShowSma(!showSma)}
              className={`px-2.5 py-1 rounded-lg border text-[11px] font-semibold cursor-pointer ${
                showSma
                  ? 'bg-[#8ab4f8]/15 border-[#8ab4f8]/40 text-[#8ab4f8]'
                  : 'bg-[#0d121a] border-white/[0.08] text-[#a6b0c3]'
              }`}
            >
              SMA 20/50/200
            </button>
            <button
              type="button"
              onClick={() => setShowEma(!showEma)}
              className={`px-2.5 py-1 rounded-lg border text-[11px] font-semibold cursor-pointer ${
                showEma
                  ? 'bg-[#38bdf8]/15 border-[#38bdf8]/40 text-[#38bdf8]'
                  : 'bg-[#0d121a] border-white/[0.08] text-[#a6b0c3]'
              }`}
            >
              EMA 20/50
            </button>
            <button
              type="button"
              onClick={() => setShowBollinger(!showBollinger)}
              className={`px-2.5 py-1 rounded-lg border text-[11px] font-semibold cursor-pointer ${
                showBollinger
                  ? 'bg-[#c084fc]/15 border-[#c084fc]/40 text-[#c084fc]'
                  : 'bg-[#0d121a] border-white/[0.08] text-[#a6b0c3]'
              }`}
            >
              BB (20,2)
            </button>
            <select
              value={avwapAnchor}
              onChange={(e) => setAvwapAnchor(e.target.value)}
              className="px-2.5 py-1 rounded-lg bg-[#0d121a] border border-white/[0.12] text-[11px] font-semibold text-[#f472b6] focus:outline-none cursor-pointer"
              title="Anchored VWAP"
            >
              <option value="none">AVWAP: Off</option>
              <option value="ytd">AVWAP: YTD</option>
              <option value="high_52w">AVWAP: 52W High</option>
              <option value="low_52w">AVWAP: 52W Low</option>
              <option value="swing_low">AVWAP: Swing Low</option>
            </select>
            <button
              type="button"
              onClick={() => setShowSrLevels(!showSrLevels)}
              className={`px-2.5 py-1 rounded-lg border text-[11px] font-semibold cursor-pointer ${
                showSrLevels
                  ? 'bg-[#34b38a]/15 border-[#34b38a]/40 text-[#34b38a]'
                  : 'bg-[#0d121a] border-white/[0.08] text-[#a6b0c3]'
              }`}
            >
              Confirmed S/R
            </button>
            <button
              type="button"
              onClick={() => setShowFairValueLine(!showFairValueLine)}
              className={`px-2.5 py-1 rounded-lg border text-[11px] font-semibold cursor-pointer ${
                showFairValueLine
                  ? 'bg-[#e3b23c]/20 border-[#e3b23c]/50 text-[#e3b23c]'
                  : 'bg-[#0d121a] border-white/[0.08] text-[#a6b0c3]'
              }`}
            >
              Fair Value Line
            </button>
            <button
              type="button"
              onClick={() => setShowCorpActions(!showCorpActions)}
              className={`px-2.5 py-1 rounded-lg border text-[11px] font-semibold cursor-pointer ${
                showCorpActions
                  ? 'bg-[#f4eedf]/15 border-[#f4eedf]/30 text-[#f4eedf]'
                  : 'bg-[#0d121a] border-white/[0.08] text-[#a6b0c3]'
              }`}
            >
              Splits/Divs
            </button>
          </div>
        </div>

        {/* Dynamic Crosshair Legend Strip */}
        {crosshairInfo && (
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-mono bg-[#0d121a] px-3 py-2 rounded-xl border border-white/[0.06] tabular-nums">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-[#e3b23c] font-bold">{crosshairInfo.time}</span>
              <span>O: <strong className="text-[#f4eedf]">{currSym}{formatNum(crosshairInfo.open)}</strong></span>
              <span>H: <strong className="text-[#34b38a]">{currSym}{formatNum(crosshairInfo.high)}</strong></span>
              <span>L: <strong className="text-[#e07a5f]">{currSym}{formatNum(crosshairInfo.low)}</strong></span>
              <span>C: <strong className="text-[#f4eedf]">{currSym}{formatNum(crosshairInfo.close)}</strong></span>
              <span>Vol: <strong className="text-[#a6b0c3]">{formatCompactVol(crosshairInfo.volume)}</strong></span>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-[11px]">
              {crosshairInfo.sma50 != null && (
                <span className="text-[#e3b23c]">SMA50: {currSym}{formatNum(crosshairInfo.sma50)}</span>
              )}
              {crosshairInfo.sma200 != null && (
                <span className="text-[#c084fc]">SMA200: {currSym}{formatNum(crosshairInfo.sma200)}</span>
              )}
              {crosshairInfo.rsi14 != null && (
                <span className="text-[#8ab4f8]">RSI(14): {formatNum(crosshairInfo.rsi14, 1)}</span>
              )}
            </div>
          </div>
        )}

        {/* Main Chart + 24-Bin Volume Profile Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-stretch">
          <div className="lg:col-span-9 flex flex-col gap-2 min-w-0">
            <div
              ref={mainChartContainerRef}
              className="w-full rounded-xl overflow-hidden border border-white/[0.08] bg-[#0d121a]"
            />

            {/* Sub-Pane Selector Tabs (Collapsible / Mobile-Friendly) */}
            <div className="flex items-center justify-between gap-2 pt-1">
              <div className="inline-flex items-center gap-1 bg-[#0d121a] p-1 rounded-xl border border-white/[0.08]">
                {[
                  { id: 'rsi', label: 'Wilder RSI (14)' },
                  { id: 'macd', label: 'MACD (12, 26, 9)' },
                  { id: 'atr', label: 'Wilder ATR (14)' },
                ].map((pane) => (
                  <button
                    key={pane.id}
                    type="button"
                    onClick={() => setActiveSubPane(pane.id)}
                    className={`px-3 py-1 rounded-lg text-xs font-bold transition cursor-pointer ${
                      activeSubPane === pane.id
                        ? 'bg-[#e3b23c] text-[#0f141c]'
                        : 'text-[#a6b0c3] hover:text-[#f4eedf]'
                    }`}
                  >
                    {pane.label}
                  </button>
                ))}
              </div>
              <a
                href="https://www.tradingview.com/lightweight-charts/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[10px] text-[#818ea4] hover:text-[#a6b0c3] underline"
              >
                Charts powered by TradingView Lightweight Charts™ (Apache 2.0)
              </a>
            </div>

            <div
              ref={subChartContainerRef}
              className="w-full rounded-xl overflow-hidden border border-white/[0.08] bg-[#0d121a]"
            />
          </div>

          {/* Right 3 Cols: 24-Bin Volume Profile & Causal S/R Table */}
          <div className="lg:col-span-3 bg-[#0d121a] rounded-xl p-3.5 border border-white/[0.08] flex flex-col justify-between space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="font-display font-bold text-xs uppercase tracking-wider text-[#f4eedf]">
                  Volume Profile (1Y)
                </span>
                <span className="text-[10px] font-mono text-[#e3b23c]">
                  {vpData?.approximation_label || 'est. from daily bars'}
                </span>
              </div>
              <p className="text-[11px] text-[#a6b0c3] mb-2.5">
                POC: <strong className="text-[#e3b23c]">{currSym}{formatNum(vpData?.poc_price)}</strong> · 70% VA:{' '}
                <strong className="text-[#8ab4f8]">
                  {currSym}{formatNum(vpData?.val_price, 0)}–{currSym}{formatNum(vpData?.vah_price, 0)}
                </strong>
              </p>

              {/* 24-Bin Horizontal Volume Profile Bars (Highest price at top) */}
              <div className="space-y-1 max-h-[260px] overflow-y-auto pr-1">
                {[...(vpData?.bins || [])].reverse().map((bin, idx) => (
                  <div key={idx} className="flex items-center gap-2 text-[10px] font-mono tabular-nums">
                    <span
                      className={`w-16 text-right shrink-0 ${
                        bin.is_poc
                          ? 'text-[#e3b23c] font-bold'
                          : bin.in_value_area
                          ? 'text-[#f4eedf]'
                          : 'text-[#818ea4]'
                      }`}
                    >
                      {currSym}{formatNum(bin.price_mid, 0)}
                    </span>
                    <div className="flex-1 h-2.5 bg-[#141b26] rounded overflow-hidden">
                      <div
                        className={`h-full rounded ${
                          bin.is_poc
                            ? 'bg-[#e3b23c]'
                            : bin.in_value_area
                            ? 'bg-[#5b8fd9]/75'
                            : 'bg-[#818ea4]/30'
                        }`}
                        style={{ width: `${Math.max(3, bin.pct_of_max)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Confirmed Causal Support & Resistance Zones */}
            <div className="pt-3 border-t border-white/[0.08]">
              <div className="flex items-center justify-between mb-2">
                <span className="font-display font-bold text-xs uppercase tracking-wider text-[#f4eedf]">
                  Confirmed S/R Zones
                </span>
                <span className="text-[10px] text-[#34b38a] font-mono">5-Bar Causal</span>
              </div>
              <div className="space-y-1.5 text-xs">
                {(taData?.chart?.support_resistance?.levels || []).map((lv, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-[#141b26] border border-white/[0.06] tabular-nums"
                  >
                    <span
                      className={`font-bold uppercase text-[10px] ${
                        lv.role === 'support' ? 'text-[#34b38a]' : 'text-[#e07a5f]'
                      }`}
                    >
                      {lv.role === 'support' ? 'Support' : 'Resist.'} ({lv.touches}x)
                    </span>
                    <span className="font-mono font-bold text-[#f4eedf]">
                      {currSym}{formatNum(lv.price)}
                    </span>
                    <span className="text-[10px] text-[#a6b0c3] font-mono">
                      {lv.distance_pct >= 0 ? '+' : ''}{lv.distance_pct}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 4. BOTTOM ROW: SEPARATE VALUATION PROBABILITY PANEL + FIXED-RISK POSITION SIZING CALCULATOR */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4 items-start">
        {/* Left 6 Cols: Valuation Panel (Separate from Price Axis so Chart Never Compresses) */}
        <div className="xl:col-span-6 bg-[#141b26] rounded-2xl p-4 sm:p-5 border border-[#f4eedf]/10 shadow-lg space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-white/[0.08]">
            <div>
              <h3 className="font-display font-bold text-base text-[#f4eedf]">
                Monte Carlo Intrinsic-Value Distribution (Separate Axis)
              </h3>
              <p className="text-xs text-[#a6b0c3]">
                Kept on an independent valuation scale so wide DCF spreads never compress candlestick price action
              </p>
            </div>
            {pricePercentile != null && (
              <span className="px-3 py-1 rounded-xl bg-[#5b8fd9]/15 border border-[#5b8fd9]/35 text-[#8ab4f8] font-display font-bold text-xs">
                Current price is at P{pricePercentile} of simulated values
              </span>
            )}
          </div>

          {mcHist?.bins?.length > 0 ? (
            <div className="space-y-3">
              {/* Compact SVG/CSS Histogram with Current Price & Fair Value Markers */}
              <div className="bg-[#0d121a] rounded-xl p-4 border border-white/[0.06] space-y-3">
                <div className="flex items-end gap-0.5 h-32 w-full">
                  {(() => {
                    const maxC = Math.max(...mcHist.counts, 1);
                    const step = Math.max(1, Math.floor(mcHist.bins.length / 48));
                    const sampled = [];
                    for (let i = 0; i < mcHist.bins.length; i += step) {
                      sampled.push({ bin: mcHist.bins[i], count: mcHist.counts[i] });
                    }
                    return sampled.map((item, idx) => {
                      const hPct = Math.max(4, (item.count / maxC) * 100);
                      const isNearPrice =
                        idx > 0 &&
                        sampled[idx - 1].bin <= latestClose &&
                        item.bin >= latestClose;
                      const isNearFv =
                        fcCard.fair_value &&
                        idx > 0 &&
                        sampled[idx - 1].bin <= fcCard.fair_value &&
                        item.bin >= fcCard.fair_value;
                      return (
                        <div
                          key={idx}
                          className="flex-1 flex flex-col justify-end h-full group relative"
                          title={`${currSym}${formatNum(item.bin)}: ${item.count} runs`}
                        >
                          <div
                            className={`w-full rounded-t transition-all ${
                              isNearPrice
                                ? 'bg-[#f4eedf]'
                                : isNearFv
                                ? 'bg-[#e3b23c]'
                                : item.bin < (mcStats.p25 || 0)
                                ? 'bg-[#34b38a]/65'
                                : item.bin > (mcStats.p75 || Infinity)
                                ? 'bg-[#e07a5f]/65'
                                : 'bg-[#5b8fd9]/65'
                            }`}
                            style={{ height: `${hPct}%` }}
                          />
                        </div>
                      );
                    });
                  })()}
                </div>

                {/* Quantile Summary Row */}
                <div className="grid grid-cols-5 gap-2 pt-2 border-t border-white/[0.08] text-center text-xs tabular-nums">
                  <div>
                    <div className="text-[10px] text-[#a6b0c3] uppercase">P5 (Bear)</div>
                    <div className="font-display font-bold text-[#e07a5f]">
                      {currSym}{formatNum(mcStats.p5 ?? 0)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-[#a6b0c3] uppercase">P25</div>
                    <div className="font-display font-bold text-[#f4eedf]">
                      {currSym}{formatNum(mcStats.p25 ?? 0)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-[#e3b23c] font-bold uppercase">P50 Median</div>
                    <div className="font-display font-bold text-[#e3b23c]">
                      {currSym}{formatNum(mcStats.median ?? fcCard.fair_value ?? 0)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-[#a6b0c3] uppercase">P75</div>
                    <div className="font-display font-bold text-[#f4eedf]">
                      {currSym}{formatNum(mcStats.p75 ?? 0)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-[#a6b0c3] uppercase">P95 (Bull)</div>
                    <div className="font-display font-bold text-[#34b38a]">
                      {currSym}{formatNum(mcStats.p95 ?? 0)}
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-[#a6b0c3]">
                <span>
                  <strong className="text-[#f4eedf]">{fcCard.valuation_outlook_label}</strong> · Model v{MODEL_VERSION}
                </span>
                {fcCard.fair_value_line_label && (
                  <span className="font-mono text-[11px] text-[#e3b23c]">
                    {fcCard.fair_value_line_label}
                  </span>
                )}
              </div>
            </div>
          ) : (
            <div className="bg-[#0d121a] rounded-xl p-6 text-center text-xs text-[#a6b0c3]">
              Simulated intrinsic-value distribution appears here when paired with a DCF valuation run.
            </div>
          )}
        </div>

        {/* Right 6 Cols: Fixed-Risk Position Sizing Calculator */}
        <div className="xl:col-span-6 bg-[#141b26] rounded-2xl p-4 sm:p-5 border border-[#f4eedf]/10 shadow-lg space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-white/[0.08]">
            <div>
              <h3 className="font-display font-bold text-base text-[#f4eedf]">
                Fixed-Risk Position Sizing Calculator
              </h3>
              <p className="text-xs text-[#a6b0c3]">
                Sizes whole-share lots from account risk budget, ATR/swing stop distance, round-trip friction &amp; max weight cap
              </p>
            </div>
            <span className="px-2.5 py-0.5 rounded bg-[#0d121a] border border-white/[0.08] text-[11px] font-mono text-[#e3b23c]">
              Tick: {currSym}{posCalc.tickSize || (taData?.market === 'IN' ? 0.05 : 0.01)}
            </span>
          </div>

          {/* Calculator Inputs Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs">
            <div>
              <label className="text-[#a6b0c3] block mb-1 font-semibold">
                Portfolio Capital ({currSym})
              </label>
              <input
                type="number"
                value={posCapital}
                onChange={(e) => setPosCapital(parseFloat(e.target.value) || 0)}
                className="w-full px-3 py-2 rounded-xl bg-[#0d121a] border border-white/[0.12] text-[#f4eedf] font-display font-bold tabular-nums focus:border-[#e3b23c] focus:outline-none"
              />
            </div>

            <div>
              <label className="text-[#a6b0c3] block mb-1 font-semibold">
                Risk Budget per Trade (%)
              </label>
              <input
                type="number"
                step="0.25"
                min="0.1"
                max="10"
                value={posRiskPct}
                onChange={(e) => setPosRiskPct(parseFloat(e.target.value) || 0)}
                className="w-full px-3 py-2 rounded-xl bg-[#0d121a] border border-white/[0.12] text-[#f4eedf] font-display font-bold tabular-nums focus:border-[#e3b23c] focus:outline-none"
              />
            </div>

            <div>
              <label className="text-[#a6b0c3] block mb-1 font-semibold">
                Max Position Weight (%)
              </label>
              <input
                type="number"
                step="1"
                min="1"
                max="100"
                value={posMaxWeightPct}
                onChange={(e) => setPosMaxWeightPct(parseFloat(e.target.value) || 0)}
                className="w-full px-3 py-2 rounded-xl bg-[#0d121a] border border-white/[0.12] text-[#f4eedf] font-display font-bold tabular-nums focus:border-[#e3b23c] focus:outline-none"
              />
            </div>

            <div>
              <label className="text-[#a6b0c3] block mb-1 font-semibold">
                Entry Price ({currSym})
              </label>
              <input
                type="number"
                step="0.05"
                value={posEntryPrice}
                onChange={(e) => setPosEntryPrice(parseFloat(e.target.value) || 0)}
                className="w-full px-3 py-2 rounded-xl bg-[#0d121a] border border-white/[0.12] text-[#f4eedf] font-display font-bold tabular-nums focus:border-[#e3b23c] focus:outline-none"
              />
            </div>

            <div>
              <label className="text-[#a6b0c3] block mb-1 font-semibold">
                Stop-Loss Method
              </label>
              <select
                value={stopMethod}
                onChange={(e) => handleStopMethodChange(e.target.value)}
                className="w-full px-2.5 py-2 rounded-xl bg-[#0d121a] border border-white/[0.12] text-[#e3b23c] font-semibold focus:border-[#e3b23c] focus:outline-none cursor-pointer"
              >
                <option value="atr_1_5">1.5× ATR(14) Stop</option>
                <option value="atr_2">2.0× ATR(14) Stop</option>
                <option value="atr_3">3.0× ATR(14) Stop</option>
                <option value="swing_low">Confirmed Swing Low</option>
                <option value="support">Nearest Support Level</option>
                <option value="manual">Manual Stop Price</option>
              </select>
            </div>

            <div>
              <label className="text-[#a6b0c3] block mb-1 font-semibold">
                Stop Price ({currSym})
              </label>
              <input
                type="number"
                step="0.05"
                value={posStopPrice}
                onChange={(e) => {
                  setStopMethod('manual');
                  setPosStopPrice(parseFloat(e.target.value) || 0);
                }}
                className="w-full px-3 py-2 rounded-xl bg-[#0d121a] border border-white/[0.12] text-[#e07a5f] font-display font-bold tabular-nums focus:border-[#e3b23c] focus:outline-none"
              />
            </div>
          </div>

          {/* Wrong-Side Stop Validation Alert OR Sizing Outputs */}
          {!posCalc.valid ? (
            <div className="bg-[#2c1618] border border-[#e07a5f]/60 rounded-xl p-3.5 text-xs text-[#f4eedf] flex items-center gap-2.5">
              <FiAlertTriangle className="w-4 h-4 text-[#e07a5f] shrink-0" />
              <span>{posCalc.error}</span>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-center tabular-nums">
                <div className="bg-[#0d121a] rounded-xl p-3 border border-white/[0.08]">
                  <div className="text-[10px] uppercase text-[#a6b0c3] font-bold">Shares (Whole Lot)</div>
                  <div className="font-display text-lg font-bold text-[#e3b23c] mt-0.5">
                    {posCalc.shares.toLocaleString()}
                  </div>
                  {posCalc.cappedByWeight && (
                    <div className="text-[10px] text-[#e3b23c]">Capped by {posMaxWeightPct}% Wt</div>
                  )}
                </div>

                <div className="bg-[#0d121a] rounded-xl p-3 border border-white/[0.08]">
                  <div className="text-[10px] uppercase text-[#a6b0c3] font-bold">Position Value</div>
                  <div className="font-display text-lg font-bold text-[#f4eedf] mt-0.5">
                    {currSym}{formatNum(posCalc.positionValue, 0)}
                  </div>
                  <div className="text-[10px] text-[#8ab4f8]">
                    {posCalc.portfolioWeightPct.toFixed(1)}% of Capital
                  </div>
                </div>

                <div className="bg-[#0d121a] rounded-xl p-3 border border-white/[0.08]">
                  <div className="text-[10px] uppercase text-[#a6b0c3] font-bold">Max Net Loss</div>
                  <div className="font-display text-lg font-bold text-[#e07a5f] mt-0.5">
                    -{currSym}{formatNum(posCalc.maxLossAmt, 0)}
                  </div>
                  <div className="text-[10px] text-[#a6b0c3]">
                    {posCalc.maxLossPct.toFixed(2)}% Risk (incl. {posCostBps} bps)
                  </div>
                </div>

                <div className="bg-[#0d121a] rounded-xl p-3 border border-white/[0.08]">
                  <div className="text-[10px] uppercase text-[#a6b0c3] font-bold">R-Multiple Targets</div>
                  <div className="text-xs font-mono font-bold text-[#34b38a] mt-1 space-y-0.5">
                    <div>2R: {currSym}{formatNum(posCalc.targets.r2)}</div>
                    <div className="text-[10px] text-[#a6b0c3]">3R: {currSym}{formatNum(posCalc.targets.r3)}</div>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-[#818ea4]">
                <span>
                  Stop Distance: <strong className="text-[#f4eedf]">-{posCalc.stopDistancePct.toFixed(2)}%</strong> ({currSym}{formatNum(posCalc.riskPerShare)}/sh net risk)
                </span>
                <div className="flex items-center gap-2">
                  <span>Round-Trip Cost (bps):</span>
                  <input
                    type="number"
                    min="0"
                    max="200"
                    step="5"
                    value={posCostBps}
                    onChange={(e) => setPosCostBps(parseFloat(e.target.value) || 0)}
                    className="w-14 px-2 py-0.5 rounded bg-[#0d121a] border border-white/[0.12] text-[#f4eedf] text-right font-mono"
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
        </>
      )}

      {/* ===================================================================== */}
      {/* TAB 2: TWO-STAGE INDICATOR MATRIX (D / W / M)                         */}
      {/* ===================================================================== */}
      {activeTaTab === 'matrix' && (() => {
        const p2 = taData?.phase2 || {};
        const comp = p2.composite_score || {};
        const rows = p2.indicator_matrix || [];
        const pillarsD = comp.pillars_d || {};
        const topBull = comp.top_bullish_contributors || [];
        const topBear = comp.top_bearish_contributors || [];

        const formatS = (val) => {
          if (val == null || Number.isNaN(Number(val))) return '—';
          const num = Number(val);
          return `${num >= 0 ? '+' : ''}${num.toFixed(2)}`;
        };

        const sColor = (val) => {
          if (val == null) return 'text-[#818ea4]';
          if (val >= 0.25) return 'text-[#34b38a]';
          if (val <= -0.25) return 'text-[#e07a5f]';
          return 'text-[#e3b23c]';
        };

        return (
          <div className="space-y-4">
            {/* Stage B Composite Summary & Multi-Timeframe Breakdown */}
            <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-4 pb-3 border-b border-white/[0.08]">
                <div>
                  <div className="flex items-center gap-2.5">
                    <h3 className="font-display font-bold text-lg text-[#f4eedf]">
                      Two-Stage Composite Score &amp; Pillar Decomposition
                    </h3>
                    <span className="px-2 py-0.5 rounded bg-[#e3b23c]/15 text-[#e3b23c] border border-[#e3b23c]/30 text-[11px] font-mono font-bold">
                      {comp.score_version || 'ta-score-v0.2'}
                    </span>
                  </div>
                  <p className="text-xs text-[#a6b0c3] mt-0.5">
                    Stage A maps 16 indicators into s_j ∈ [−1, +1] (one vote per concept). Stage B aggregates 6 fixed-weight pillars into S = 100·Σ W_k(P_k+1)/2 (no dynamic regime weighting).
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-3 bg-[#0d121a] px-4 py-2.5 rounded-xl border border-white/[0.08]">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-[#a6b0c3] font-bold">
                      Qualified Condition
                    </div>
                    <div
                      className={`font-display font-bold text-sm sm:text-base ${
                        comp.condition_tone === 'emerald'
                          ? 'text-[#34b38a]'
                          : comp.condition_tone === 'rose'
                          ? 'text-[#e07a5f]'
                          : 'text-[#e3b23c]'
                      }`}
                    >
                      {comp.condition_label || 'Score unavailable'}
                    </div>
                  </div>
                  {comp.available && comp.score_mtf != null && (
                    <>
                      <div className="h-7 w-px bg-white/[0.08]" />
                      <div className="text-right font-mono tabular-nums">
                        <div className="text-[10px] uppercase text-[#a6b0c3]">S_MTF Score</div>
                        <div className="font-display font-bold text-xl text-[#f4eedf]">
                          {Number(comp.score_mtf).toFixed(1)} <span className="text-xs text-[#818ea4]">/ 100</span>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </div>

              {/* 6 Fixed-Weight Pillar Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
                {Object.values(pillarsD).map((p) => {
                  const score100 = p.score_100;
                  return (
                    <div
                      key={p.id}
                      className="bg-[#0d121a] rounded-xl p-3.5 border border-white/[0.08] flex flex-col justify-between space-y-2"
                    >
                      <div className="flex items-center justify-between gap-1">
                        <span className="text-xs font-bold text-[#f4eedf] truncate" title={p.label}>
                          {p.label}
                        </span>
                        <span className="text-[10px] font-mono text-[#e3b23c] bg-[#141b26] px-1.5 py-0.5 rounded border border-white/[0.06] shrink-0">
                          W={Math.round((p.weight || 0) * 100)}%
                        </span>
                      </div>
                      <div className="flex items-baseline justify-between tabular-nums">
                        <span className={`font-display text-lg font-bold ${sColor(p.p_k)}`}>
                          {score100 != null ? `${score100.toFixed(1)}/100` : 'Gated'}
                        </span>
                        <span className="text-[11px] font-mono text-[#a6b0c3]">
                          P_k = {formatS(p.p_k)}
                        </span>
                      </div>
                      <div className="w-full h-1.5 bg-[#141b26] rounded-full overflow-hidden">
                        <div
                          className={`h-full ${
                            (p.p_k || 0) >= 0.2
                              ? 'bg-[#34b38a]'
                              : (p.p_k || 0) <= -0.2
                              ? 'bg-[#e07a5f]'
                              : 'bg-[#e3b23c]'
                          }`}
                          style={{ width: `${score100 != null ? Math.min(100, Math.max(4, score100)) : 0}%` }}
                        />
                      </div>
                      <div className="text-[10px] text-[#818ea4] flex items-center justify-between font-mono">
                        <span>Coverage: {Math.round((p.coverage || 0) * 100)}%</span>
                        <span className={p.passes_gate ? 'text-[#34b38a]' : 'text-[#e07a5f]'}>
                          {p.passes_gate ? '≥60% OK' : '<60% Gate'}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Top-3 Bullish & Top-3 Bearish Contributors */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
                <div className="bg-[#0d121a] rounded-xl p-3.5 border border-[#34b38a]/25 space-y-2">
                  <div className="text-xs font-bold uppercase tracking-wider text-[#34b38a] flex items-center justify-between">
                    <span>Top-3 Bullish Contributors (s_MTF &gt; 0)</span>
                    <span className="text-[10px] font-mono text-[#a6b0c3]">Signed Edge vs Neutral</span>
                  </div>
                  {topBull.length > 0 ? (
                    <div className="space-y-1.5 text-xs">
                      {topBull.map((item) => (
                        <div key={item.id} className="flex items-center justify-between gap-2 bg-[#141b26] px-3 py-1.5 rounded-lg border border-white/[0.05]">
                          <span className="font-semibold text-[#f4eedf] truncate">{item.name}</span>
                          <span className="font-mono text-[#34b38a] font-bold shrink-0">
                            s={formatS(item.s_mtf)} ({item.signed_edge_pts >= 0 ? '+' : ''}{item.signed_edge_pts.toFixed(2)} pts)
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-xs text-[#818ea4]">No positive indicator contributors currently active.</div>
                  )}
                </div>

                <div className="bg-[#0d121a] rounded-xl p-3.5 border border-[#e07a5f]/25 space-y-2">
                  <div className="text-xs font-bold uppercase tracking-wider text-[#e07a5f] flex items-center justify-between">
                    <span>Top-3 Bearish Contributors (s_MTF &lt; 0)</span>
                    <span className="text-[10px] font-mono text-[#a6b0c3]">Signed Edge vs Neutral</span>
                  </div>
                  {topBear.length > 0 ? (
                    <div className="space-y-1.5 text-xs">
                      {topBear.map((item) => (
                        <div key={item.id} className="flex items-center justify-between gap-2 bg-[#141b26] px-3 py-1.5 rounded-lg border border-white/[0.05]">
                          <span className="font-semibold text-[#f4eedf] truncate">{item.name}</span>
                          <span className="font-mono text-[#e07a5f] font-bold shrink-0">
                            s={formatS(item.s_mtf)} ({item.signed_edge_pts.toFixed(2)} pts)
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-xs text-[#818ea4]">No negative indicator contributors currently active.</div>
                  )}
                </div>
              </div>
            </div>

            {/* Full 16-Indicator D / W / M Matrix Table */}
            <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="font-display font-bold text-base text-[#f4eedf]">
                    Complete 16-Indicator Audit Matrix (D / W / M → Raw Value → Rule → s_j → Weight → Contribution)
                  </h3>
                  <p className="text-xs text-[#a6b0c3]">
                    Weekly (1W) and Monthly (1M) columns strictly evaluate completed bars only to prevent intra-period flicker
                  </p>
                </div>
                <div className="text-xs font-mono text-[#a6b0c3]">
                  S_D: <strong className="text-[#f4eedf]">{comp.score_d ?? '—'}</strong> · S_W:{' '}
                  <strong className="text-[#f4eedf]">{comp.score_w ?? '—'}</strong> · S_M:{' '}
                  <strong className="text-[#f4eedf]">{comp.score_m ?? '—'}</strong>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full min-w-[980px] text-left text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-white/[0.10] text-[#a6b0c3] uppercase text-[10px] tracking-wider">
                      <th className="py-2.5 pr-3">Pillar &amp; Indicator</th>
                      <th className="py-2.5 px-3">Daily (1D) Raw &amp; s_D</th>
                      <th className="py-2.5 px-3">Weekly (1W) Raw &amp; s_W</th>
                      <th className="py-2.5 px-3">Monthly (1M) Raw &amp; s_M</th>
                      <th className="py-2.5 px-3">Stage-A Mapping Rule</th>
                      <th className="py-2.5 px-3 text-right">s_MTF</th>
                      <th className="py-2.5 px-3 text-right">Weight (W_k·w_j)</th>
                      <th className="py-2.5 pl-3 text-right">Contribution</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.06] tabular-nums">
                    {rows.map((r) => (
                      <tr key={r.id} className="hover:bg-white/[0.02]">
                        <td className="py-2.5 pr-3">
                          <div className="font-bold text-[#f4eedf]">{r.name}</div>
                          <div className="text-[10px] text-[#e3b23c] font-semibold">
                            {r.pillar_label} ({Math.round(r.pillar_weight * 100)}% × {Math.round(r.indicator_weight * 100)}%)
                          </div>
                        </td>
                        <td className="py-2.5 px-3 font-mono">
                          <div className="text-[#f4eedf]">{r.raw_d}</div>
                          <div className={`text-[11px] font-bold ${sColor(r.s_d)}`}>s_D = {formatS(r.s_d)}</div>
                        </td>
                        <td className="py-2.5 px-3 font-mono">
                          <div className="text-[#f4eedf]">{r.raw_w}</div>
                          <div className={`text-[11px] font-bold ${sColor(r.s_w)}`}>s_W = {formatS(r.s_w)}</div>
                        </td>
                        <td className="py-2.5 px-3 font-mono">
                          <div className="text-[#f4eedf]">{r.raw_m}</div>
                          <div className={`text-[11px] font-bold ${sColor(r.s_m)}`}>s_M = {formatS(r.s_m)}</div>
                        </td>
                        <td className="py-2.5 px-3 text-[11px] text-[#a6b0c3] max-w-[260px]">
                          {r.rule}
                        </td>
                        <td className={`py-2.5 px-3 text-right font-mono font-bold ${sColor(r.s_mtf)}`}>
                          {formatS(r.s_mtf)}
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono text-[#c5cedd]">
                          {(r.effective_weight * 100).toFixed(2)}%
                        </td>
                        <td className="py-2.5 pl-3 text-right font-mono">
                          <div className="font-bold text-[#f4eedf]">
                            {r.points_100 != null ? `${r.points_100.toFixed(2)} pts` : '—'}
                          </div>
                          <div className={`text-[10px] ${sColor(r.s_mtf)}`}>
                            ({r.signed_edge_pts >= 0 ? '+' : ''}{r.signed_edge_pts.toFixed(2)} vs 50)
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        );
      })()}

      {/* ===================================================================== */}
      {/* TAB 3: REGIME DIAGNOSTICS, RELATIVE STRENGTH & CONFLUENCE MATRIX      */}
      {/* ===================================================================== */}
      {activeTaTab === 'regime' && (() => {
        const p2 = taData?.phase2 || {};
        const cm = p2.classification_matrix || {};
        const diag = p2.diagnostics || {};
        const hurst = diag.hurst_dfa1 || {};
        const vr = diag.lo_mackinlay_vr || {};
        const yz = diag.yang_zhang_vol || {};
        const rs = diag.relative_strength || {};
        const dw = diag.dow_wyckoff || {};

        return (
          <div className="space-y-4">
            {/* 1. 3x4 FUNDAMENTAL OUTLOOK x WEINSTEIN STAGE CLASSIFICATION MATRIX (R6) */}
            <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-white/[0.08]">
                <div>
                  <h3 className="font-display font-bold text-lg text-[#f4eedf]">
                    Fundamental Valuation Outlook × Weinstein Stage Classification Matrix
                  </h3>
                  <p className="text-xs text-[#a6b0c3]">
                    Rows equal the live Fundamental Valuation Outlook ({cm.live_verdict || 'NEUTRAL'}); columns equal completed-weekly Weinstein Stage 1–4. Descriptive classification only.
                  </p>
                </div>
                {cm.active_cell && (
                  <div className="px-3.5 py-2 rounded-xl bg-[#e3b23c]/15 border border-[#e3b23c]/40 text-right">
                    <div className="text-[10px] uppercase tracking-wider text-[#e3b23c] font-bold">
                      Active Cell Classification
                    </div>
                    <div className="font-display font-bold text-xs sm:text-sm text-[#f4eedf]">
                      {cm.active_cell.title}
                    </div>
                  </div>
                )}
              </div>

              {cm.active_cell && (
                <div className="bg-[#0d121a] rounded-xl p-4 border border-[#e3b23c]/35 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="space-y-1">
                    <div className="text-xs font-bold text-[#e3b23c]">
                      {cm.active_cell.title} — {cm.active_cell.subtitle}
                    </div>
                    <p className="text-xs text-[#c5cedd]">{cm.active_cell.description}</p>
                  </div>
                  <div className="shrink-0 flex items-center gap-2 text-xs font-mono">
                    <span className="px-2.5 py-1 rounded-lg bg-[#141b26] border border-white/[0.08] text-[#f4eedf]">
                      Valuation outlook: <strong className="text-[#e3b23c]">{cm.live_verdict}</strong>
                    </span>
                    <span className="px-2.5 py-1 rounded-lg bg-[#141b26] border border-white/[0.08] text-[#8ab4f8]">
                      Stage: <strong>{cm.active_stage ?? 'N/A'}</strong>
                    </span>
                  </div>
                </div>
              )}

              <div className="overflow-x-auto">
                <table className="w-full min-w-[880px] text-left text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-white/[0.10] text-[#a6b0c3] uppercase text-[10px] tracking-wider">
                      <th className="py-2.5 pr-3 w-52">Fundamental Valuation Row</th>
                      {(cm.columns || []).map((col) => (
                        <th key={col.stage} className="py-2.5 px-3">
                          {col.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.06]">
                    {(cm.rows || []).map((row) => (
                      <tr
                        key={row.id}
                        className={row.is_greyed ? 'opacity-40 bg-[#090d14]/40' : ''}
                      >
                        <td className="py-3 pr-3 align-top">
                          <div className="font-display font-bold text-[#f4eedf] flex items-center gap-1.5">
                            {row.is_active_row && (
                              <span className="w-2 h-2 rounded-full bg-[#e3b23c] shrink-0" />
                            )}
                            <span>{row.label}</span>
                          </div>
                          <div className="text-[10px] text-[#818ea4] mt-0.5">{row.sub}</div>
                        </td>
                        {(row.cells || []).map((cell) => (
                          <td key={cell.stage} className="py-2.5 px-2 align-top">
                            <div
                              className={`p-3 rounded-xl border transition-all h-full ${
                                cell.is_active
                                  ? 'bg-[#e3b23c]/15 border-[#e3b23c] shadow-md ring-1 ring-[#e3b23c]/50'
                                  : 'bg-[#0d121a] border-white/[0.06]'
                              }`}
                            >
                              <div className="flex items-center justify-between gap-1 mb-1">
                                <span
                                  className={`font-display font-bold text-xs ${
                                    cell.is_active ? 'text-[#e3b23c]' : 'text-[#f4eedf]'
                                  }`}
                                >
                                  {cell.subtitle}
                                </span>
                                {cell.is_active && (
                                  <span className="px-1.5 py-0.5 rounded bg-[#e3b23c] text-[#0f141c] font-bold text-[9px] uppercase">
                                    Active
                                  </span>
                                )}
                              </div>
                              <p className="text-[11px] text-[#a6b0c3] leading-snug">
                                {cell.description}
                              </p>
                            </div>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* 2. STATISTICAL REGIME DIAGNOSTICS (SEPARATE CARDS — NEVER COMBINED INTO ONE CALL) */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {/* Card A: Hurst DFA-1 */}
              <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between space-y-3">
                <div>
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="text-xs font-bold uppercase tracking-wider text-[#e3b23c]">
                      Hurst Exponent (DFA-1)
                    </span>
                    <span className="text-[10px] font-mono text-[#a6b0c3] bg-[#0d121a] px-2 py-0.5 rounded border border-white/[0.06]">
                      {hurst.window_bars || 504}B · Scales 10–126
                    </span>
                  </div>
                  <div className="font-display text-2xl font-bold text-[#f4eedf] tabular-nums my-1">
                    {hurst.available ? `H = ${hurst.hurst.toFixed(3)}` : 'Unavailable'}
                  </div>
                  <div
                    className={`text-xs font-bold ${
                      hurst.state_code === 'persistent'
                        ? 'text-[#34b38a]'
                        : hurst.state_code === 'mean_reverting'
                        ? 'text-[#8ab4f8]'
                        : 'text-[#e3b23c]'
                    }`}
                  >
                    {hurst.regime || hurst.reason}
                  </div>
                </div>

                {hurst.available && (
                  <div className="bg-[#0d121a] rounded-xl p-3 border border-white/[0.06] space-y-1.5 text-xs font-mono tabular-nums">
                    <div className="flex justify-between">
                      <span className="text-[#a6b0c3]">Block-Bootstrap 95% CI:</span>
                      <strong className="text-[#f4eedf]">
                        [{hurst.ci_95?.[0]?.toFixed(3)}, {hurst.ci_95?.[1]?.toFixed(3)}]
                      </strong>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[#a6b0c3]">10-Day Hysteresis Ref:</span>
                      <strong className="text-[#f4eedf]">H_−10d = {hurst.hurst_10d_ago?.toFixed(3)}</strong>
                    </div>
                    <div className="text-[10px] text-[#818ea4] font-sans pt-1 border-t border-white/[0.06]">
                      Reports &ldquo;Indeterminate&rdquo; whenever the 95% block-bootstrap CI spans 0.50 or 10D hysteresis is unconfirmed.
                    </div>
                  </div>
                )}
              </div>

              {/* Card B: Lo-MacKinlay Variance Ratio + Chow-Denning */}
              <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between space-y-3">
                <div>
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="text-xs font-bold uppercase tracking-wider text-[#8ab4f8]">
                      Lo–MacKinlay Variance Ratio
                    </span>
                    <span className="text-[10px] font-mono text-[#a6b0c3] bg-[#0d121a] px-2 py-0.5 rounded border border-white/[0.06]">
                      Robust z*(q) &amp; Chow–Denning
                    </span>
                  </div>
                  <div className="font-display text-lg font-bold text-[#f4eedf] my-1">
                    {vr.available
                      ? `Joint CD* = ${vr.chow_denning_stat?.toFixed(2)} (95% Crit: ${vr.chow_denning_crit_95})`
                      : 'Unavailable'}
                  </div>
                  <div className="text-xs font-semibold text-[#c5cedd]">
                    {vr.joint_verdict || vr.reason}
                  </div>
                </div>

                {vr.available && (
                  <div className="grid grid-cols-4 gap-2 text-center font-mono text-xs tabular-nums">
                    {(vr.profiles || []).map((p) => (
                      <div
                        key={p.q}
                        className={`p-2 rounded-xl border ${
                          p.significant_95
                            ? 'bg-[#e3b23c]/15 border-[#e3b23c]/40'
                            : 'bg-[#0d121a] border-white/[0.06]'
                        }`}
                      >
                        <div className="text-[10px] text-[#a6b0c3]">VR({p.q})</div>
                        <div className="font-bold text-[#f4eedf] mt-0.5">{p.vr.toFixed(2)}</div>
                        <div className="text-[10px] text-[#8ab4f8]">z*={p.z_star >= 0 ? '+' : ''}{p.z_star.toFixed(2)}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Card C: Yang-Zhang Realized Volatility */}
              <div className="bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between space-y-3">
                <div>
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="text-xs font-bold uppercase tracking-wider text-[#34b38a]">
                      Yang–Zhang Realized Vol
                    </span>
                    <span className="text-[10px] font-mono text-[#e3b23c] bg-[#0d121a] px-2 py-0.5 rounded border border-white/[0.06]">
                      {yz.units || '% annualized'}
                    </span>
                  </div>
                  <div className="flex items-baseline gap-4 my-1 tabular-nums">
                    <div>
                      <span className="text-[10px] text-[#a6b0c3] block">20D Annualized</span>
                      <span className="font-display text-2xl font-bold text-[#f4eedf]">
                        {yz.yz_20d_pct != null ? `${yz.yz_20d_pct.toFixed(2)}%` : 'N/A'}
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-[#a6b0c3] block">60D Annualized</span>
                      <span className="font-display text-xl font-bold text-[#c5cedd]">
                        {yz.yz_60d_pct != null ? `${yz.yz_60d_pct.toFixed(2)}%` : 'N/A'}
                      </span>
                    </div>
                  </div>
                  <div className="text-xs font-semibold text-[#8ab4f8]">{yz.regime_label}</div>
                </div>

                {yz.available && (
                  <div className="bg-[#0d121a] rounded-xl p-3 border border-white/[0.06] space-y-2 text-xs font-mono tabular-nums">
                    <div className="flex items-center justify-between">
                      <span className="text-[#a6b0c3]">1Y (252D) Percentile:</span>
                      <strong className="text-[#f4eedf]">
                        {yz.pct_rank_1y != null ? `P${yz.pct_rank_1y.toFixed(0)}` : 'N/A'}
                      </strong>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-[#a6b0c3]">5Y (1260D) Percentile:</span>
                      <strong className="text-[#f4eedf]">
                        {yz.pct_rank_5y != null ? `P${yz.pct_rank_5y.toFixed(0)}` : 'Requires 5Y'}
                      </strong>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* 3. BENCHMARK RELATIVE STRENGTH + DOW THEORY HH/HL + WYCKOFF VSA SUITE */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
              {/* Left 6 Cols: Benchmark Relative Strength */}
              <div className="lg:col-span-6 bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg space-y-4">
                <div className="flex items-center justify-between gap-2 pb-2.5 border-b border-white/[0.08]">
                  <div>
                    <h3 className="font-display font-bold text-base text-[#f4eedf]">
                      Benchmark Relative Strength vs {rs.benchmark_label || taData?.benchmark}
                    </h3>
                    <p className="text-xs text-[#a6b0c3]">
                      Mansfield 52-Week RS zero-line gauge &amp; 63-day OLS regression α / β
                    </p>
                  </div>
                  <span className="px-2.5 py-1 rounded-lg bg-[#0d121a] border border-white/[0.08] font-mono text-xs text-[#8ab4f8]">
                    {rs.benchmark_symbol || taData?.benchmark}
                  </span>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-center font-mono tabular-nums">
                  <div className="bg-[#0d121a] rounded-xl p-3 border border-white/[0.06]">
                    <div className="text-[10px] text-[#a6b0c3] uppercase">Mansfield RS</div>
                    <div
                      className={`font-display text-lg font-bold mt-0.5 ${
                        (rs.mansfield_rs || 0) >= 0 ? 'text-[#34b38a]' : 'text-[#e07a5f]'
                      }`}
                    >
                      {rs.mansfield_rs != null
                        ? `${rs.mansfield_rs >= 0 ? '+' : ''}${rs.mansfield_rs.toFixed(2)}`
                        : 'N/A'}
                    </div>
                  </div>
                  <div className="bg-[#0d121a] rounded-xl p-3 border border-white/[0.06]">
                    <div className="text-[10px] text-[#a6b0c3] uppercase">63D Alpha (Ann.)</div>
                    <div
                      className={`font-display text-lg font-bold mt-0.5 ${
                        (rs.alpha_63d_annualized_pct || 0) >= 0 ? 'text-[#34b38a]' : 'text-[#e07a5f]'
                      }`}
                    >
                      {rs.alpha_63d_annualized_pct != null
                        ? `${rs.alpha_63d_annualized_pct >= 0 ? '+' : ''}${rs.alpha_63d_annualized_pct.toFixed(1)}%`
                        : 'N/A'}
                    </div>
                  </div>
                  <div className="bg-[#0d121a] rounded-xl p-3 border border-white/[0.06]">
                    <div className="text-[10px] text-[#a6b0c3] uppercase">63D α t-stat</div>
                    <div className="font-display text-lg font-bold text-[#f4eedf] mt-0.5">
                      {rs.alpha_63d_tstat != null
                        ? `${rs.alpha_63d_tstat >= 0 ? '+' : ''}${rs.alpha_63d_tstat.toFixed(2)}`
                        : 'N/A'}
                    </div>
                  </div>
                  <div className="bg-[#0d121a] rounded-xl p-3 border border-white/[0.06]">
                    <div className="text-[10px] text-[#a6b0c3] uppercase">Beta (63D / 1Y)</div>
                    <div className="font-display text-base font-bold text-[#e3b23c] mt-0.5">
                      {rs.beta_63d ?? '—'} / {rs.beta_252d ?? '—'}
                    </div>
                  </div>
                </div>

                {rs.excess_returns_pct && Object.keys(rs.excess_returns_pct).length > 0 && (
                  <div className="overflow-x-auto pt-1">
                    <table className="w-full text-xs text-left border-collapse font-mono tabular-nums">
                      <thead>
                        <tr className="border-b border-white/[0.08] text-[#a6b0c3] text-[10px] uppercase">
                          <th className="py-1.5">Horizon</th>
                          <th className="py-1.5 text-right">Stock Return</th>
                          <th className="py-1.5 text-right">Benchmark</th>
                          <th className="py-1.5 text-right">Excess Spread</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/[0.05]">
                        {Object.entries(rs.excess_returns_pct).map(([hKey, hObj]) => (
                          <tr key={hKey}>
                            <td className="py-1.5 font-bold text-[#f4eedf]">{hKey}</td>
                            <td className="py-1.5 text-right text-[#c5cedd]">
                              {hObj.stock_pct >= 0 ? '+' : ''}{hObj.stock_pct}%
                            </td>
                            <td className="py-1.5 text-right text-[#a6b0c3]">
                              {hObj.benchmark_pct >= 0 ? '+' : ''}{hObj.benchmark_pct}%
                            </td>
                            <td
                              className={`py-1.5 text-right font-bold ${
                                hObj.excess_pct >= 0 ? 'text-[#34b38a]' : 'text-[#e07a5f]'
                              }`}
                            >
                              {hObj.excess_pct >= 0 ? '+' : ''}{hObj.excess_pct}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Right 6 Cols: Dow Theory HH/HL & Wyckoff Volume-Spread Analysis (VSA) */}
              <div className="lg:col-span-6 bg-[#141b26] rounded-2xl p-5 border border-[#f4eedf]/10 shadow-lg space-y-4">
                <div className="flex items-center justify-between gap-2 pb-2.5 border-b border-white/[0.08]">
                  <div>
                    <h3 className="font-display font-bold text-base text-[#f4eedf]">
                      Dow Theory Pivot Structure &amp; Wyckoff VSA Tags
                    </h3>
                    <p className="text-xs text-[#a6b0c3]">
                      Causal 5-bar confirmed swing progression &amp; recent institutional volume-spread events
                    </p>
                  </div>
                  <span className="px-2.5 py-1 rounded-lg bg-[#0d121a] border border-white/[0.08] font-bold text-xs text-[#e3b23c]">
                    {dw.dow_state || 'Consolidation'}
                  </span>
                </div>

                <div className="bg-[#0d121a] rounded-xl p-3 border border-white/[0.06] text-xs text-[#c5cedd]">
                  <strong className="text-[#f4eedf]">Pivot Sequence: </strong>
                  {dw.dow_detail}
                </div>

                <div className="space-y-2">
                  <div className="text-xs font-bold uppercase tracking-wider text-[#a6b0c3]">
                    Recent Wyckoff Volume-Spread Analysis (VSA) Events (Trailing 60 Sessions)
                  </div>
                  {(dw.wyckoff_vsa_events || []).length > 0 ? (
                    <div className="space-y-1.5 max-h-[210px] overflow-y-auto pr-1">
                      {dw.wyckoff_vsa_events.map((ev, i) => (
                        <div
                          key={i}
                          className="p-2.5 rounded-xl bg-[#0d121a] border border-white/[0.06] flex items-start justify-between gap-2 text-xs"
                        >
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-[#e3b23c] font-bold">{ev.date}</span>
                              <span
                                className={`font-bold ${
                                  ev.bias === 'bullish' ? 'text-[#34b38a]' : 'text-[#e07a5f]'
                                }`}
                              >
                                {ev.tag}
                              </span>
                            </div>
                            <p className="text-[11px] text-[#a6b0c3] mt-0.5">{ev.detail}</p>
                          </div>
                          <div className="text-right font-mono text-[10px] text-[#c5cedd] shrink-0">
                            <div>Vol: {ev.rel_volume}×</div>
                            <div>Spread: {ev.rel_spread_atr}×ATR</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-xs text-[#818ea4] bg-[#0d121a] p-3 rounded-xl border border-white/[0.06]">
                      No extreme Wyckoff VSA bars detected in the trailing 60 sessions.
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        );
      })()}

      {/* =====================================================================
          PHASE 3 TAB 4: PER-STOCK SIGNAL BACKTESTER (10 SIGNALS x 4 HORIZONS = 40 TESTS)
         ===================================================================== */}
      {activeTaTab === 'backtest' && (() => {
        if (btLoading && !btData) {
          return (
            <div className="bg-[#141b26] rounded-2xl p-8 border border-[#f4eedf]/10 text-center space-y-3">
              <div className="inline-flex items-center justify-center w-10 h-10 rounded-xl bg-[#e3b23c]/15 text-[#e3b23c] animate-pulse">
                <FiTarget className="w-5 h-5" />
              </div>
              <div className="font-display font-bold text-base text-[#f4eedf]">
                Running 40 Walk-Forward Signal Tests for {activeSymbol}...
              </div>
              <p className="text-xs text-[#a6b0c3]">
                Evaluating 10 frozen canonical signals across 5D, 10D, 20D &amp; 60D horizons with 20-bar de-clustering, 1,000-iteration event-block bootstrap CIs &amp; Benjamini–Hochberg FDR...
              </p>
            </div>
          );
        }

        if (btError && !btData) {
          return (
            <div className="bg-[#2c1618] border border-[#e07a5f]/50 rounded-2xl p-6 text-[#f4eedf] space-y-3">
              <div className="flex items-center gap-2 font-display font-bold text-base text-[#e07a5f]">
                <FiAlertTriangle className="w-5 h-5" />
                <span>Per-Stock Signal Backtest Failed</span>
              </div>
              <p className="text-xs sm:text-sm text-[#f4eedf]/85">{btError}</p>
              <button
                type="button"
                onClick={() => fetchTechnicalBacktest(btCostInput)}
                className="px-4 py-2 rounded-xl bg-[#e3b23c] text-[#0f141c] text-xs font-bold cursor-pointer"
              >
                Retry Backtest
              </button>
            </div>
          );
        }

        const bt = btData || {};
        const tests = bt.tests || [];
        const signals = bt.signals || [];
        const split = bt.sample_split || {};
        const counts = bt.summary_counts || {};
        const pendingList = bt.pending_signals || [];

        const getLabelStyle = (label) => {
          if (label === 'Historically favourable') {
            return 'bg-[#34b38a]/15 text-[#34b38a] border-[#34b38a]/35';
          }
          if (label === 'Insufficient evidence') {
            return 'bg-[#e3b23c]/15 text-[#e3b23c] border-[#e3b23c]/35';
          }
          return 'bg-white/[0.06] text-[#c5cedd] border-white/[0.12]';
        };

        const filteredTests = tests.filter((c) => {
          if (btHorizonFilter !== 'all' && Number(c.horizon_days) !== Number(btHorizonFilter)) {
            return false;
          }
          if (btLabelFilter !== 'all' && c.label !== btLabelFilter) {
            return false;
          }
          return true;
        });

        const cellLookup = {};
        tests.forEach((c) => {
          cellLookup[`${c.signal_id}_${c.horizon_days}`] = c;
        });

        return (
          <div className="space-y-4">
            {/* 1. Survivorship-Bias & Look-Back Disclosure Banner */}
            <div className="bg-[#121824] border border-[#e3b23c]/30 rounded-xl px-4 py-3 text-xs text-[#c5cedd] flex items-start gap-2.5">
              <FiShield className="w-4 h-4 text-[#e3b23c] shrink-0 mt-0.5" />
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-bold text-[#f4eedf]">
                    Survivorship-Bias &amp; Single-Security Look-Back Disclosure
                  </span>
                  <span className="px-2 py-0.5 rounded bg-[#e3b23c]/15 text-[#e3b23c] font-mono text-[10px] font-bold">
                    {bt.version || 'ta-backtest-v0.3'}
                  </span>
                </div>
                <p className="text-[11px] text-[#a6b0c3] leading-relaxed">
                  {bt.disclosure}
                </p>
                {bt.coverage_note && (
                  <p className="text-[11px] text-[#e3b23c] font-medium pt-0.5">
                    Note: {bt.coverage_note}
                  </p>
                )}
              </div>
            </div>

            {/* 2. Top 4 Summary Cards: FDR Counts | 70/30 Split | Execution Contract | Editable Friction */}
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
              {/* Card A: 40-Test Classification Summary */}
              <div className="bg-[#141b26] rounded-2xl p-4 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-[#a6b0c3]">
                    40-Test Multiple-Testing Gate
                  </span>
                  <span className="px-2 py-0.5 rounded bg-[#5b8fd9]/15 text-[#8ab4f8] text-[10px] font-mono font-bold">
                    BH-FDR q &lt; 0.10
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2 my-1">
                  <div className="bg-[#0d121a] rounded-xl p-2.5 border border-[#34b38a]/25 text-center">
                    <div className="font-display text-lg font-bold text-[#34b38a]">
                      {counts.historically_favourable ?? 0}
                    </div>
                    <div className="text-[10px] text-[#a6b0c3] leading-tight mt-0.5">
                      Historically Favourable
                    </div>
                  </div>
                  <div className="bg-[#0d121a] rounded-xl p-2.5 border border-white/[0.08] text-center">
                    <div className="font-display text-lg font-bold text-[#f4eedf]">
                      {counts.no_reliable_edge ?? 0}
                    </div>
                    <div className="text-[10px] text-[#a6b0c3] leading-tight mt-0.5">
                      No Reliable Edge
                    </div>
                  </div>
                  <div className="bg-[#0d121a] rounded-xl p-2.5 border border-[#e3b23c]/25 text-center">
                    <div className="font-display text-lg font-bold text-[#e3b23c]">
                      {counts.insufficient_evidence ?? 0}
                    </div>
                    <div className="text-[10px] text-[#a6b0c3] leading-tight mt-0.5">
                      Insufficient (N_IS &lt; 15)
                    </div>
                  </div>
                </div>
                <div className="text-[11px] text-[#818ea4] mt-2">
                  Requires Net IS Excess &gt; 0, 95% CI &gt; 0, q &lt; 0.10 &amp; OOS &gt; 0.
                </div>
              </div>

              {/* Card B: Chronological 70 / 30 In-Sample / Out-of-Sample Split */}
              <div className="bg-[#141b26] rounded-2xl p-4 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-[#a6b0c3]">
                    Chronological 70 / 30 Split
                  </span>
                  <span className="px-2 py-0.5 rounded bg-white/[0.06] text-[#f4eedf] text-[10px] font-mono">
                    {bt.observations || 0} Daily Bars
                  </span>
                </div>
                <div className="space-y-1.5 text-xs font-mono">
                  <div className="bg-[#0d121a] rounded-xl px-3 py-2 border border-white/[0.06] flex items-center justify-between">
                    <span className="text-[#a6b0c3]">In-Sample (70%):</span>
                    <span className="text-[#f4eedf] font-bold">
                      {split.is_start_date || '—'} → {split.is_end_date || '—'} ({split.is_observations || 0})
                    </span>
                  </div>
                  <div className="bg-[#0d121a] rounded-xl px-3 py-2 border border-white/[0.06] flex items-center justify-between">
                    <span className="text-[#a6b0c3]">Out-of-Sample (30%):</span>
                    <span className="text-[#8ab4f8] font-bold">
                      {split.oos_start_date || '—'} → {split.oos_end_date || '—'} ({split.oos_observations || 0})
                    </span>
                  </div>
                </div>
                <div className="text-[11px] text-[#818ea4] mt-2">
                  Parameters are canonical and frozen across IS &amp; OOS.
                </div>
              </div>

              {/* Card C: Zero Look-Ahead Execution & De-Clustering Contract */}
              <div className="bg-[#141b26] rounded-2xl p-4 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-[#a6b0c3]">
                    Execution &amp; De-Clustering
                  </span>
                  <span className="px-2 py-0.5 rounded bg-[#34b38a]/15 text-[#34b38a] text-[10px] font-mono font-bold">
                    Zero Look-Ahead
                  </span>
                </div>
                <div className="space-y-1 text-xs text-[#c5cedd]">
                  <div className="flex justify-between">
                    <span className="text-[#a6b0c3]">Signal Evaluation:</span>
                    <span className="font-mono text-[#f4eedf]">Confirmed Close[t]</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#a6b0c3]">Entry / Exit Fill:</span>
                    <span className="font-mono text-[#e3b23c]">Open_tr[t+1] → Close_tr[t+h]</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#a6b0c3]">Event De-Clustering:</span>
                    <span className="font-mono text-[#f4eedf]">{bt.decluster_cooldown_bars || 20}-Bar Cooldown</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#a6b0c3]">Price Series Basis:</span>
                    <span className="font-mono text-[#34b38a]">Total-Return (ohlc_tr)</span>
                  </div>
                </div>
                <div className="text-[11px] text-[#818ea4] mt-2">
                  Both raw and de-clustered trigger counts are reported below.
                </div>
              </div>

              {/* Card D: Editable Round-Trip Transaction Cost (bps) */}
              <div className="bg-[#141b26] rounded-2xl p-4 border border-[#f4eedf]/10 shadow-lg flex flex-col justify-between">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-[#a6b0c3]">
                    Round-Trip Friction (bps)
                  </span>
                  <span className="px-2 py-0.5 rounded bg-[#e3b23c]/15 text-[#e3b23c] text-[10px] font-mono font-bold">
                    Active: {bt.round_trip_cost_bps ?? (bt.market === 'IN' ? 30 : 10)} bps
                  </span>
                </div>
                <div className="flex items-center gap-2 my-1">
                  <input
                    type="number"
                    min="0"
                    max="500"
                    step="5"
                    value={btCostInput}
                    onChange={(e) => setBtCostInput(e.target.value)}
                    className="w-full bg-[#0d121a] border border-white/[0.12] rounded-xl px-3 py-1.5 text-sm font-mono text-[#f4eedf] focus:outline-none focus:border-[#e3b23c]"
                    placeholder="e.g. 10 or 30"
                  />
                  <button
                    type="button"
                    disabled={btLoading}
                    onClick={() => fetchTechnicalBacktest(btCostInput)}
                    className="px-3.5 py-1.5 rounded-xl bg-[#e3b23c] text-[#0f141c] text-xs font-bold hover:bg-[#e3b23c]/90 transition cursor-pointer shrink-0"
                  >
                    {btLoading ? '...' : 'Apply'}
                  </button>
                </div>
                <div className="flex flex-wrap items-center gap-1.5 mt-1">
                  {[
                    { label: '0 bps (Gross)', val: 0 },
                    { label: '10 bps (US)', val: 10 },
                    { label: '30 bps (IN)', val: 30 },
                    { label: '50 bps', val: 50 },
                  ].map((preset) => (
                    <button
                      key={preset.val}
                      type="button"
                      onClick={() => {
                        setBtCostInput(String(preset.val));
                        fetchTechnicalBacktest(preset.val);
                      }}
                      className={`px-2 py-0.5 rounded text-[10px] font-mono cursor-pointer border transition ${
                        Number(bt.round_trip_cost_bps) === preset.val
                          ? 'bg-[#e3b23c]/20 text-[#e3b23c] border-[#e3b23c]/40 font-bold'
                          : 'bg-[#0d121a] text-[#a6b0c3] border-white/[0.08] hover:text-[#f4eedf]'
                      }`}
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* 3. Active / Pending Signals Strip (if any triggered within last 60 sessions) */}
            {pendingList.length > 0 && (
              <div className="bg-[#141b26] rounded-2xl p-4 border border-[#8ab4f8]/30 shadow-lg space-y-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-xs font-bold text-[#8ab4f8] uppercase tracking-wider">
                    <FiClock className="w-4 h-4" />
                    <span>
                      Recently Triggered Signals with Unfinished Holding Horizons ({pendingList.length} Excluded from Completed Stats)
                    </span>
                  </div>
                  <span className="text-[11px] text-[#a6b0c3]">
                    Excluded from completed statistics until Close_tr[t + h] is observed
                  </span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 text-xs">
                  {pendingList.slice(0, 6).map((p, idx) => (
                    <div
                      key={`${p.signal_id}_${p.signal_date}_${idx}`}
                      className="bg-[#0d121a] rounded-xl p-3 border border-white/[0.07] flex items-center justify-between gap-2"
                    >
                      <div>
                        <div className="font-bold text-[#f4eedf]">{p.signal_name}</div>
                        <div className="text-[11px] text-[#a6b0c3] font-mono mt-0.5">
                          Signal: {p.signal_date} ({p.bars_elapsed}d ago)
                        </div>
                      </div>
                      <div className="text-right font-mono shrink-0">
                        <span className="px-2 py-0.5 rounded bg-[#5b8fd9]/15 text-[#8ab4f8] text-[10px] font-bold">
                          Pending: {p.pending_horizons.map((h) => `${h}D`).join(', ')}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 4. 10 x 4 Signal x Horizon Overview Heatmap Matrix */}
            <div className="bg-[#141b26] rounded-2xl p-4 sm:p-5 border border-[#f4eedf]/10 shadow-xl space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-white/[0.08]">
                <div>
                  <h3 className="font-display font-bold text-base text-[#f4eedf]">
                    10 Frozen Signals × 4 Horizons Matrix (40 Hypothesis Tests)
                  </h3>
                  <p className="text-xs text-[#a6b0c3]">
                    Click any horizon cell to inspect its trade-by-trade event dates below. All tests use de-clustered triggers (20-bar window).
                  </p>
                </div>
                <div className="flex items-center gap-2 text-[11px] font-mono text-[#a6b0c3]">
                  <span>Benchmark: <strong className="text-[#8ab4f8]">{bt.benchmark}</strong></span>
                  <span>·</span>
                  <span>Costs: <strong className="text-[#e3b23c]">{bt.round_trip_cost_bps} bps</strong></span>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left border-collapse">
                  <thead>
                    <tr className="border-b border-white/[0.08] text-[#a6b0c3] text-[10px] uppercase tracking-wider">
                      <th className="py-2.5 pr-3">Frozen Signal Definition</th>
                      <th className="py-2.5 px-2 text-center">Direction</th>
                      <th className="py-2.5 px-2 text-right">Triggers (De-clust / Raw)</th>
                      {[5, 10, 20, 60].map((h) => (
                        <th key={h} className="py-2.5 px-2 text-center min-w-[145px]">
                          {h}-Day Horizon (t+1 → t+{h})
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.06]">
                    {signals.map((sig) => (
                      <tr key={sig.id} className="hover:bg-white/[0.02] transition">
                        <td className="py-3 pr-3">
                          <div className="font-bold text-[#f4eedf]">{sig.name}</div>
                          <div className="text-[11px] text-[#818ea4] line-clamp-1" title={sig.rule_summary}>
                            {sig.rule_summary}
                          </div>
                        </td>
                        <td className="py-3 px-2 text-center font-mono text-[11px]">
                          <span
                            className={`px-2 py-0.5 rounded border ${
                              sig.direction > 0
                                ? 'bg-[#34b38a]/10 text-[#34b38a] border-[#34b38a]/30'
                                : 'bg-[#e07a5f]/10 text-[#e07a5f] border-[#e07a5f]/30'
                            }`}
                          >
                            {sig.direction_label}
                          </span>
                        </td>
                        <td className="py-3 px-2 text-right font-mono tabular-nums text-[#c5cedd]">
                          <div className="font-bold text-[#f4eedf]">
                            {sig.n_declustered_triggers} <span className="text-[#818ea4] font-normal">/ {sig.n_raw_triggers}</span>
                          </div>
                          <div className="text-[10px] text-[#818ea4]">
                            IS: {sig.n_declustered_is} · OOS: {sig.n_declustered_oos}
                          </div>
                        </td>
                        {[5, 10, 20, 60].map((h) => {
                          const cell = cellLookup[`${sig.id}_${h}`];
                          if (!cell) return <td key={h} className="py-3 px-2 text-center">—</td>;
                          const isEx = cell.in_sample?.net_excess_vs_drift_pct;
                          const oosEx = cell.out_of_sample?.net_excess_vs_drift_pct;
                          const isSelected = expandedTestId === cell.test_id;
                          return (
                            <td key={h} className="py-2 px-1.5">
                              <button
                                type="button"
                                onClick={() =>
                                  setExpandedTestId(isSelected ? null : cell.test_id)
                                }
                                title={cell.label_reason}
                                className={`w-full text-left p-2 rounded-xl border transition cursor-pointer ${
                                  isSelected
                                    ? 'ring-2 ring-[#e3b23c] bg-[#1a2333] border-[#e3b23c]/50'
                                    : 'bg-[#0d121a] border-white/[0.07] hover:border-white/[0.20]'
                                }`}
                              >
                                <div className="flex items-center justify-between gap-1 mb-1">
                                  <span
                                    className={`px-1.5 py-0.5 rounded text-[9px] font-bold border truncate ${getLabelStyle(
                                      cell.label
                                    )}`}
                                  >
                                    {cell.label}
                                  </span>
                                  <span className="text-[10px] font-mono text-[#818ea4]">
                                    q={cell.q_value_fdr != null ? cell.q_value_fdr.toFixed(2) : '1.00'}
                                  </span>
                                </div>
                                <div className="flex items-baseline justify-between font-mono text-[11px] tabular-nums">
                                  <span className="text-[#a6b0c3]">IS Ex:</span>
                                  <span
                                    className={`font-bold ${
                                      isEx == null
                                        ? 'text-[#818ea4]'
                                        : isEx > 0
                                        ? 'text-[#34b38a]'
                                        : 'text-[#e07a5f]'
                                    }`}
                                  >
                                    {isEx != null ? `${isEx >= 0 ? '+' : ''}${isEx.toFixed(2)}%` : 'N/A'}
                                  </span>
                                </div>
                                <div className="flex items-baseline justify-between font-mono text-[10px] tabular-nums text-[#818ea4]">
                                  <span>OOS Ex:</span>
                                  <span
                                    className={
                                      oosEx == null
                                        ? 'text-[#818ea4]'
                                        : oosEx > 0
                                        ? 'text-[#34b38a]'
                                        : 'text-[#e07a5f]'
                                    }
                                  >
                                    {oosEx != null ? `${oosEx >= 0 ? '+' : ''}${oosEx.toFixed(2)}%` : '—'}
                                  </span>
                                </div>
                              </button>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* 5. Detailed 40-Test Statistical Table with Filters & Expandable Event Dates */}
            <div className="bg-[#141b26] rounded-2xl p-4 sm:p-5 border border-[#f4eedf]/10 shadow-xl space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-white/[0.08]">
                <div>
                  <h3 className="font-display font-bold text-base text-[#f4eedf]">
                    Detailed Walk-Forward Test Ledger ({filteredTests.length} of {tests.length} Tests)
                  </h3>
                  <p className="text-xs text-[#a6b0c3]">
                    Gross vs Net returns, Excess vs Unconditional Drift &amp; Benchmark, Wilson 95% Win-Rate CIs, Event-Block Bootstrap CIs, BH-FDR q-values, and MAE/MFE
                  </p>
                </div>

                {/* Filters */}
                <div className="flex flex-wrap items-center gap-2">
                  <div className="inline-flex rounded-xl bg-[#0d121a] p-1 border border-white/[0.08]">
                    {[
                      { id: 'all', label: 'All Horizons' },
                      { id: 5, label: '5D' },
                      { id: 10, label: '10D' },
                      { id: 20, label: '20D' },
                      { id: 60, label: '60D' },
                    ].map((hOpt) => (
                      <button
                        key={hOpt.id}
                        type="button"
                        onClick={() => setBtHorizonFilter(hOpt.id)}
                        className={`px-2.5 py-1 rounded-lg text-xs font-bold transition cursor-pointer ${
                          String(btHorizonFilter) === String(hOpt.id)
                            ? 'bg-[#e3b23c] text-[#0f141c]'
                            : 'text-[#a6b0c3] hover:text-[#f4eedf]'
                        }`}
                      >
                        {hOpt.label}
                      </button>
                    ))}
                  </div>

                  <select
                    value={btLabelFilter}
                    onChange={(e) => setBtLabelFilter(e.target.value)}
                    className="bg-[#0d121a] border border-white/[0.12] rounded-xl px-3 py-1.5 text-xs font-bold text-[#f4eedf] focus:outline-none focus:border-[#e3b23c]"
                  >
                    <option value="all">All Classifications (40)</option>
                    <option value="Historically favourable">Historically favourable</option>
                    <option value="No reliable edge">No reliable edge</option>
                    <option value="Insufficient evidence">Insufficient evidence</option>
                  </select>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left border-collapse font-mono tabular-nums">
                  <thead>
                    <tr className="border-b border-white/[0.08] text-[#a6b0c3] text-[10px] uppercase tracking-wider font-sans">
                      <th className="py-2.5 pr-3">Signal &amp; Horizon</th>
                      <th className="py-2.5 px-2 text-right">IS / OOS (Raw)</th>
                      <th className="py-2.5 px-2 text-right">IS Gross / Net</th>
                      <th className="py-2.5 px-2 text-right">IS Net Excess (Drift / Bench)</th>
                      <th className="py-2.5 px-2 text-right">95% Bootstrap CI &amp; FDR q</th>
                      <th className="py-2.5 px-2 text-right">Net Win % (Wilson 95% CI)</th>
                      <th className="py-2.5 px-2 text-right">OOS (30%) Net Excess</th>
                      <th className="py-2.5 px-2 text-right">Median MAE / MFE</th>
                      <th className="py-2.5 px-2 text-center">Classification</th>
                      <th className="py-2.5 pl-2 text-right">Events</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.06]">
                    {filteredTests.map((cell) => {
                      const isS = cell.in_sample || {};
                      const oosS = cell.out_of_sample || {};
                      const cnt = cell.counts || {};
                      const ci = isS.bootstrap_95_ci_pct || [null, null];
                      const wci = isS.wilson_95_ci_pct || [null, null];
                      const isExpanded = expandedTestId === cell.test_id;

                      return (
                        <React.Fragment key={cell.test_id}>
                          <tr className="hover:bg-white/[0.02] transition">
                            <td className="py-3 pr-3 font-sans">
                              <div className="font-bold text-[#f4eedf]">
                                {cell.signal_name}{' '}
                                <span className="px-1.5 py-0.5 rounded bg-[#e3b23c]/15 text-[#e3b23c] font-mono text-[10px]">
                                  {cell.horizon_days}D
                                </span>
                              </div>
                              <div className="text-[10px] text-[#818ea4]">{cell.direction_label}</div>
                            </td>

                            <td className="py-3 px-2 text-right">
                              <div className="text-[#f4eedf] font-bold">
                                {cnt.n_is} / {cnt.n_oos}
                              </div>
                              <div className="text-[10px] text-[#818ea4]">
                                raw: {cnt.n_raw_is}/{cnt.n_raw_oos}
                              </div>
                            </td>

                            <td className="py-3 px-2 text-right">
                              <div className="text-[#c5cedd]">
                                {isS.mean_gross_return_pct != null
                                  ? `${isS.mean_gross_return_pct >= 0 ? '+' : ''}${isS.mean_gross_return_pct.toFixed(2)}%`
                                  : 'N/A'}
                              </div>
                              <div
                                className={`font-bold ${
                                  (isS.mean_net_return_pct || 0) >= 0 ? 'text-[#34b38a]' : 'text-[#e07a5f]'
                                }`}
                              >
                                {isS.mean_net_return_pct != null
                                  ? `${isS.mean_net_return_pct >= 0 ? '+' : ''}${isS.mean_net_return_pct.toFixed(2)}%`
                                  : 'N/A'}
                              </div>
                            </td>

                            <td className="py-3 px-2 text-right">
                              <div
                                className={`font-bold ${
                                  (isS.net_excess_vs_drift_pct || 0) > 0 ? 'text-[#34b38a]' : 'text-[#e07a5f]'
                                }`}
                              >
                                {isS.net_excess_vs_drift_pct != null
                                  ? `${isS.net_excess_vs_drift_pct >= 0 ? '+' : ''}${isS.net_excess_vs_drift_pct.toFixed(2)}%`
                                  : 'N/A'}
                              </div>
                              <div className="text-[10px] text-[#a6b0c3]">
                                vs Bench:{' '}
                                {isS.net_excess_vs_benchmark_pct != null
                                  ? `${isS.net_excess_vs_benchmark_pct >= 0 ? '+' : ''}${isS.net_excess_vs_benchmark_pct.toFixed(2)}%`
                                  : '—'}
                              </div>
                            </td>

                            <td className="py-3 px-2 text-right">
                              <div className="text-[#c5cedd]">
                                {ci[0] != null && ci[1] != null
                                  ? `[${ci[0].toFixed(2)}%, ${ci[1].toFixed(2)}%]`
                                  : 'N/A'}
                              </div>
                              <div className="text-[10px] text-[#8ab4f8]">
                                q = {cell.q_value_fdr != null ? cell.q_value_fdr.toFixed(3) : '1.000'} (p={isS.p_value != null ? isS.p_value.toFixed(3) : '1.000'})
                              </div>
                            </td>

                            <td className="py-3 px-2 text-right">
                              <div className="text-[#f4eedf] font-bold">
                                {isS.win_rate_net_pct != null ? `${isS.win_rate_net_pct.toFixed(1)}%` : 'N/A'}
                              </div>
                              <div className="text-[10px] text-[#818ea4]">
                                {wci[0] != null && wci[1] != null
                                  ? `[${wci[0].toFixed(1)}–${wci[1].toFixed(1)}%]`
                                  : '—'}
                              </div>
                            </td>

                            <td className="py-3 px-2 text-right">
                              <div
                                className={`font-bold ${
                                  oosS.net_excess_vs_drift_pct == null
                                    ? 'text-[#818ea4]'
                                    : oosS.net_excess_vs_drift_pct > 0
                                    ? 'text-[#34b38a]'
                                    : 'text-[#e07a5f]'
                                }`}
                              >
                                {oosS.net_excess_vs_drift_pct != null
                                  ? `${oosS.net_excess_vs_drift_pct >= 0 ? '+' : ''}${oosS.net_excess_vs_drift_pct.toFixed(2)}%`
                                  : 'N/A'}
                              </div>
                              <div className="text-[10px] text-[#818ea4]">
                                Net:{' '}
                                {oosS.mean_net_return_pct != null
                                  ? `${oosS.mean_net_return_pct >= 0 ? '+' : ''}${oosS.mean_net_return_pct.toFixed(2)}%`
                                  : '—'}
                              </div>
                            </td>

                            <td className="py-3 px-2 text-right">
                              <div className="text-[#e07a5f]">
                                {isS.median_mae_pct != null ? `${isS.median_mae_pct.toFixed(2)}%` : '—'}
                              </div>
                              <div className="text-[#34b38a] text-[10px]">
                                +{isS.median_mfe_pct != null ? `${isS.median_mfe_pct.toFixed(2)}%` : '—'}
                              </div>
                            </td>

                            <td className="py-3 px-2 text-center font-sans">
                              <span
                                className={`inline-block px-2 py-0.5 rounded-lg text-[10px] font-bold border ${getLabelStyle(
                                  cell.label
                                )}`}
                                title={cell.label_reason}
                              >
                                {cell.label}
                              </span>
                            </td>

                            <td className="py-3 pl-2 text-right font-sans">
                              <button
                                type="button"
                                onClick={() =>
                                  setExpandedTestId(isExpanded ? null : cell.test_id)
                                }
                                className="px-2.5 py-1 rounded-lg bg-[#0d121a] border border-white/[0.10] hover:border-[#e3b23c]/50 text-[11px] font-bold text-[#e3b23c] cursor-pointer"
                              >
                                {isExpanded ? 'Hide' : `Log (${cnt.n_declustered_total})`}
                              </button>
                            </td>
                          </tr>

                          {/* Expandable Event-Date Audit Drawer */}
                          {isExpanded && (
                            <tr className="bg-[#0d121a]">
                              <td colSpan={10} className="p-4 border-t border-white/[0.08] font-sans">
                                <div className="space-y-3">
                                  <div className="flex flex-wrap items-center justify-between gap-2">
                                    <div>
                                      <div className="font-bold text-xs text-[#f4eedf]">
                                        Reproducible De-Clustered Event Log — {cell.signal_name} ({cell.horizon_days}D Horizon)
                                      </div>
                                      <div className="text-[11px] text-[#a6b0c3] mt-0.5">
                                        Gate Diagnostic: <span className="text-[#e3b23c]">{cell.label_reason}</span>
                                      </div>
                                    </div>
                                    <div className="text-[11px] font-mono text-[#a6b0c3]">
                                      Showing most recent {(cell.recent_events || []).length} of {cnt.n_declustered_total} de-clustered events
                                    </div>
                                  </div>

                                  {(cell.recent_events || []).length > 0 ? (
                                    <div className="overflow-x-auto max-h-[260px] overflow-y-auto rounded-xl border border-white/[0.08]">
                                      <table className="w-full text-[11px] text-left border-collapse font-mono tabular-nums">
                                        <thead className="bg-[#141b26] text-[#a6b0c3] uppercase text-[10px] sticky top-0">
                                          <tr>
                                            <th className="py-2 px-3">Signal Close (t)</th>
                                            <th className="py-2 px-3">Entry Open (t+1)</th>
                                            <th className="py-2 px-3">Exit Close (t+{cell.horizon_days})</th>
                                            <th className="py-2 px-2 text-center">Split</th>
                                            <th className="py-2 px-2 text-right">Entry_tr</th>
                                            <th className="py-2 px-2 text-right">Exit_tr</th>
                                            <th className="py-2 px-2 text-right">Gross %</th>
                                            <th className="py-2 px-2 text-right">Net %</th>
                                            <th className="py-2 px-2 text-right">vs Bench %</th>
                                            <th className="py-2 px-3 text-right">MAE / MFE</th>
                                          </tr>
                                        </thead>
                                        <tbody className="divide-y divide-white/[0.05]">
                                          {[...(cell.recent_events || [])].reverse().map((ev, idx) => (
                                            <tr key={`${ev.signal_date}_${idx}`} className="hover:bg-white/[0.02]">
                                              <td className="py-1.5 px-3 font-bold text-[#e3b23c]">{ev.signal_date}</td>
                                              <td className="py-1.5 px-3 text-[#c5cedd]">{ev.entry_date}</td>
                                              <td className="py-1.5 px-3 text-[#c5cedd]">{ev.exit_date}</td>
                                              <td className="py-1.5 px-2 text-center">
                                                <span
                                                  className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                                                    ev.sample === 'OOS'
                                                      ? 'bg-[#5b8fd9]/20 text-[#8ab4f8]'
                                                      : 'bg-white/[0.07] text-[#c5cedd]'
                                                  }`}
                                                >
                                                  {ev.sample}
                                                </span>
                                              </td>
                                              <td className="py-1.5 px-2 text-right text-[#c5cedd]">
                                                {ev.entry_price_tr.toFixed(2)}
                                              </td>
                                              <td className="py-1.5 px-2 text-right text-[#c5cedd]">
                                                {ev.exit_price_tr.toFixed(2)}
                                              </td>
                                              <td className="py-1.5 px-2 text-right text-[#c5cedd]">
                                                {ev.gross_return_pct >= 0 ? '+' : ''}{ev.gross_return_pct.toFixed(2)}%
                                              </td>
                                              <td
                                                className={`py-1.5 px-2 text-right font-bold ${
                                                  ev.net_return_pct >= 0 ? 'text-[#34b38a]' : 'text-[#e07a5f]'
                                                }`}
                                              >
                                                {ev.net_return_pct >= 0 ? '+' : ''}{ev.net_return_pct.toFixed(2)}%
                                              </td>
                                              <td
                                                className={`py-1.5 px-2 text-right ${
                                                  ev.net_excess_vs_benchmark_pct >= 0 ? 'text-[#34b38a]' : 'text-[#e07a5f]'
                                                }`}
                                              >
                                                {ev.net_excess_vs_benchmark_pct >= 0 ? '+' : ''}{ev.net_excess_vs_benchmark_pct.toFixed(2)}%
                                              </td>
                                              <td className="py-1.5 px-3 text-right">
                                                <span className="text-[#e07a5f]">{ev.mae_pct.toFixed(1)}%</span>
                                                <span className="text-white/20"> / </span>
                                                <span className="text-[#34b38a]">+{ev.mfe_pct.toFixed(1)}%</span>
                                              </td>
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    </div>
                                  ) : (
                                    <div className="text-xs text-[#818ea4]">
                                      No completed historical events recorded for this signal-horizon pair.
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
};

export default TechnicalWorkspace;
