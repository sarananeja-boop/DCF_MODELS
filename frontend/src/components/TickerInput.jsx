import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { FiSearch, FiArrowUpRight } from 'react-icons/fi';
import rawStocks from '../data/stocks.json';

// Comprehensive 3,100+ active equity database (NSE India & US Markets) for instant 0ms autocomplete
const mapRawStocks = (list) =>
  list.map((item) => ({
    symbol: item.s,
    name: item.n,
    market: item.m,
    aliases: (item.a || '').toLowerCase(),
  }));

let STOCK_UNIVERSE = mapRawStocks(rawStocks);

export default function TickerInput({ 
  ticker, 
  setTicker, 
  market, 
  setMarket, 
  onAnalyze, 
  loading, 
  vertical = false,
  compact = false,
  heroMode = false
}) {
  const [query, setQuery] = useState(ticker);
  const [suggestions, setSuggestions] = useState([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [searching, setSearching] = useState(false);
  const dropdownRef = useRef(null);
  const timeoutRef = useRef(null);
  const searchCache = useRef(new Map());

  useEffect(() => {
    setQuery(ticker);
  }, [ticker]);

  // Auto-sync live ticker universe from backend (/api/universe)
  useEffect(() => {
    const CACHE_KEY = 'vl_universe_v2';
    const CACHE_TTL = 12 * 60 * 60 * 1000;
    try {
      const cachedRaw = localStorage.getItem(CACHE_KEY);
      if (cachedRaw) {
        const parsed = JSON.parse(cachedRaw);
        if (parsed && Array.isArray(parsed.stocks) && parsed.stocks.length > 1000) {
          STOCK_UNIVERSE = mapRawStocks(parsed.stocks);
          if (Date.now() - (parsed.ts || 0) < CACHE_TTL) {
            return;
          }
        }
      }
    } catch (_) {}

    let cancelled = false;
    axios
      .get('/api/universe', { timeout: 10000 })
      .then((res) => {
        if (cancelled) return;
        const stocks = res.data?.stocks;
        if (Array.isArray(stocks) && stocks.length > 1000) {
          STOCK_UNIVERSE = mapRawStocks(stocks);
          searchCache.current.clear();
          try {
            localStorage.setItem(CACHE_KEY, JSON.stringify({ ts: Date.now(), stocks }));
          } catch (_) {}
        }
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const filterLocal = (q) => {
    if (!q || q.trim().length < 1) return [];
    const lower = q.trim().toLowerCase();
    const cleanLower = lower.replace(/\.(ns|bo)$/, '').trim();
    const queryTokens = cleanLower.split(/\s+/).filter(Boolean);

    const exactMatches = [];
    const exactAliasMatches = [];
    const prefixSymbolMatches = [];
    const namePrefixMatches = [];
    const containSymbolMatches = [];
    const multiTokenAndAliasMatches = [];

    for (let i = 0; i < STOCK_UNIVERSE.length; i++) {
      const item = STOCK_UNIVERSE[i];
      const symClean = item.symbol.replace('.NS', '').replace('.BO', '').toLowerCase();
      const symFull = item.symbol.toLowerCase();
      const name = item.name.toLowerCase();
      const aliases = item.aliases || '';
      const aliasTokens = aliases ? aliases.split(/\s+/) : [];

      if (symClean === cleanLower || symFull === lower) {
        exactMatches.push(item);
      } else if (aliasTokens.includes(cleanLower)) {
        exactAliasMatches.push(item);
      } else if (symClean.startsWith(cleanLower) || symFull.startsWith(lower)) {
        prefixSymbolMatches.push(item);
      } else if (name.startsWith(cleanLower) || name.includes(' ' + cleanLower)) {
        namePrefixMatches.push(item);
      } else if (aliases && (aliases.startsWith(cleanLower) || aliases.includes(' ' + cleanLower))) {
        multiTokenAndAliasMatches.push(item);
      } else if (
        queryTokens.length > 1 &&
        queryTokens.every((tok) => symClean.includes(tok) || name.includes(tok) || aliases.includes(tok))
      ) {
        multiTokenAndAliasMatches.push(item);
      } else if (symClean.includes(cleanLower) || symFull.includes(lower)) {
        containSymbolMatches.push(item);
      }
    }

    prefixSymbolMatches.sort((a, b) => {
      const aLen = a.symbol.replace('.NS', '').length;
      const bLen = b.symbol.replace('.NS', '').length;
      return aLen - bLen;
    });

    const combined = [
      ...exactMatches,
      ...exactAliasMatches,
      ...prefixSymbolMatches,
      ...namePrefixMatches,
      ...multiTokenAndAliasMatches,
      ...containSymbolMatches,
    ];
    const seenBase = new Set();
    const unique = [];
    for (const item of combined) {
      const baseKey = `${item.market}:${item.symbol.replace('.NS', '').replace('.BO', '')}`;
      if (!seenBase.has(baseKey)) {
        seenBase.add(baseKey);
        unique.push(item);
        if (unique.length >= 8) break;
      }
    }
    return unique;
  };

  const fetchSuggestions = async (q, localMatches = []) => {
    if (!q || q.length < 2) return;
    if (localMatches.length >= 5) return;

    const cacheKey = q.trim().toLowerCase();
    if (searchCache.current.has(cacheKey)) {
      const cached = searchCache.current.get(cacheKey);
      setSuggestions(cached);
      setShowDropdown(cached.length > 0);
      return;
    }

    setSearching(true);
    try {
      const response = await axios.get(`/api/search?q=${encodeURIComponent(q)}`, { timeout: 12000 });
      const remoteResults = response.data.results || [];
      
      const seenBase = new Set(
        localMatches.map((m) => `${m.market}:${m.symbol.replace('.NS', '').replace('.BO', '')}`)
      );
      const combined = [...localMatches];
      for (const item of remoteResults) {
        const isIN = item.market === 'IN' || item.symbol.endsWith('.NS') || item.symbol.endsWith('.BO');
        const mkt = isIN ? 'IN' : 'US';
        const baseKey = `${mkt}:${item.symbol.replace('.NS', '').replace('.BO', '')}`;
        if (!seenBase.has(baseKey)) {
          seenBase.add(baseKey);
          combined.push({
            symbol: item.symbol,
            name: item.name,
            market: mkt,
          });
        }
      }
      const finalSuggestions = combined.slice(0, 8);
      searchCache.current.set(cacheKey, finalSuggestions);
      setSuggestions(finalSuggestions);
      setShowDropdown(finalSuggestions.length > 0);
    } catch (err) {
      if (localMatches.length > 0) {
        setSuggestions(localMatches);
        setShowDropdown(true);
      }
    } finally {
      setSearching(false);
    }
  };

  const handleInputChange = (e) => {
    const val = e.target.value;
    setQuery(val);
    setTicker(val);
    
    const localMatches = filterLocal(val);
    if (localMatches.length > 0) {
      setSuggestions(localMatches);
      setShowDropdown(true);
    } else if (val.trim().length >= 2) {
      setSuggestions([]);
      setShowDropdown(true);
    } else {
      setSuggestions([]);
      setShowDropdown(false);
    }

    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => {
      fetchSuggestions(val, localMatches);
    }, 250);
  };

  const handleSelectSuggestion = (sym, name, itemMarket) => {
    const isIN = itemMarket === 'IN' || sym.endsWith('.NS') || sym.endsWith('.BO');
    const cleanSym = isIN ? sym.replace('.NS', '').replace('.BO', '') : sym;
    const resolvedMarket = isIN ? 'IN' : 'US';
    
    setMarket(resolvedMarket);
    setQuery(cleanSym);
    setTicker(cleanSym);
    setShowDropdown(false);

    onAnalyze({}, true, cleanSym, resolvedMarket);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const cleanQuery = query.trim().toUpperCase();
    if (cleanQuery) {
      setShowDropdown(false);
      
      const localMatches = filterLocal(cleanQuery);
      const topMatch = suggestions.find(s => 
        s.symbol.toUpperCase().replace(/\.(NS|BO)$/, '') === cleanQuery || 
        s.symbol.toUpperCase() === cleanQuery
      ) || localMatches.find(s => 
        s.symbol.toUpperCase().replace(/\.(NS|BO)$/, '') === cleanQuery || 
        s.symbol.toUpperCase() === cleanQuery
      );

      if (topMatch) {
        handleSelectSuggestion(topMatch.symbol, topMatch.name, topMatch.market);
        return;
      }

      onAnalyze({}, true, cleanQuery, market);
    }
  };

  const renderDropdown = () => {
    if (!showDropdown || query.trim().length < 2) return null;
    return (
      <div className="absolute left-0 right-0 z-[9999] mt-2 bg-[#121824] border border-[#2d3848] rounded-xl shadow-[0_25px_60px_rgba(0,0,0,0.95)] max-h-80 overflow-y-auto overflow-x-hidden divide-y divide-[#2d3848]/60 text-left font-sans">
        {suggestions.length > 0 ? (
          <>
            {suggestions.map((item, idx) => {
              const isIN = item.market === 'IN' || item.symbol.endsWith('.NS');
              const cleanSymbol = item.symbol.replace('.NS', '').replace('.BO', '');
              return (
                <div 
                  key={idx}
                  onClick={() => handleSelectSuggestion(item.symbol, item.name, item.market)}
                  className="px-4 py-3 bg-[#121824] hover:bg-[#1c2436] cursor-pointer flex items-center justify-between gap-3 transition-colors group"
                >
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <span className="text-[10px] font-display font-semibold px-2 py-0.5 rounded border border-[#f4eedf]/10 bg-[#161d2a] text-[#a6b0c3] shrink-0">
                      {isIN ? 'NSE' : 'US'}
                    </span>
                    <div className="flex flex-col min-w-0 overflow-hidden">
                      <span className="font-display font-bold text-sm text-[#f4eedf] group-hover:text-[#e3b23c] transition-colors truncate">
                        {cleanSymbol}
                      </span>
                      <span className="text-xs text-[#a6b0c3] truncate max-w-[320px] sm:max-w-lg font-normal">
                        {item.name}
                      </span>
                    </div>
                  </div>
                  <span className="text-[11px] text-[#a6b0c3] font-display shrink-0 hidden sm:inline-block">
                    {isIN ? '₹ INR' : '$ USD'}
                  </span>
                </div>
              );
            })}
            {searching && (
              <div className="px-4 py-2 bg-[#0c1017] text-[11px] text-[#a6b0c3] flex items-center gap-2">
                <span className="w-3 h-3 rounded-full border-2 border-[#e3b23c]/20 border-t-[#e3b23c] animate-spin shrink-0"></span>
                <span>Searching global exchange directory...</span>
              </div>
            )}
          </>
        ) : searching ? (
          <div className="px-5 py-6 bg-[#121824] text-center flex flex-col items-center justify-center gap-2">
            <div className="w-6 h-6 rounded-full border-2 border-[#e3b23c]/20 border-t-[#e3b23c] animate-spin mb-1"></div>
            <p className="font-semibold text-xs text-[#f4eedf]">
              Searching live market database...
            </p>
          </div>
        ) : (
          <div className="px-5 py-4 bg-[#121824] text-center flex flex-col items-center justify-center gap-1">
            <p className="font-medium text-xs text-[#f4eedf]">
              Press <kbd className="px-1.5 py-0.5 rounded bg-[#1e293b] border border-[#f4eedf]/20 font-display text-[10px] text-[#e3b23c]">Enter</kbd> to query Yahoo Finance directly for &ldquo;{query}&rdquo;
            </p>
          </div>
        )}
      </div>
    );
  };

  // Wide, prominent search bar for the workspace top header
  if (compact) {
    return (
      <div className="relative w-full max-w-2xl" ref={dropdownRef}>
        <form onSubmit={handleSubmit} className="flex items-center gap-2 bg-[#121824] border border-[#2d3848] hover:border-[#3e4c63] focus-within:border-[#e3b23c] rounded-xl px-4 py-2 transition-all shadow-md">
          <FiSearch className="w-4 h-4 text-[#e3b23c] shrink-0" />
          <input
            type="text"
            value={query}
            onChange={handleInputChange}
            onFocus={() => { if (query.trim().length >= 2) setShowDropdown(true); }}
            className="w-full bg-transparent text-sm text-[#f4eedf] placeholder-[#a6b0c3]/70 focus:outline-none font-sans font-medium tracking-wide"
            placeholder="Search any Indian or US company (e.g. RELIANCE, HUL, HDFCBANK, AAPL)..."
            autoComplete="off"
          />
          <select
            value={market}
            onChange={(e) => setMarket(e.target.value)}
            className="bg-[#0c1017] text-xs text-[#f4eedf]/90 border border-[#2d3848] rounded-lg px-2.5 py-1.5 focus:outline-none cursor-pointer font-sans font-medium shrink-0"
            title="Exchange"
          >
            <option value="auto">🌐 Auto</option>
            <option value="IN">🇮🇳 NSE India</option>
            <option value="US">🇺🇸 US Market</option>
          </select>
          <button
            type="submit"
            disabled={loading || !ticker.trim()}
            className="px-4 py-1.5 rounded-lg bg-[#e3b23c] hover:bg-[#eab949] disabled:opacity-40 text-[#0f141c] font-sans font-bold text-xs transition shrink-0 cursor-pointer"
          >
            {loading ? '...' : 'Run DCF'}
          </button>
        </form>
        {renderDropdown()}
      </div>
    );
  }

  return (
    <div className={`${heroMode ? '' : 'bg-[#151c27]/90 rounded-2xl border border-[#f4eedf]/12 shadow-2xl backdrop-blur-md'} ${vertical ? 'p-4' : heroMode ? '' : 'p-5 sm:p-6'}`}>
      <form onSubmit={handleSubmit} className={`flex ${vertical ? 'flex-col gap-3.5' : 'flex-col sm:flex-row gap-3 items-stretch sm:items-end'}`}>
        <div className="flex-1 relative w-full" ref={dropdownRef}>
          <label className="block text-xs font-sans font-semibold uppercase tracking-wider text-[#f4eedf]/85 mb-2">
            Search Company or Ticker Symbol
          </label>
          <div className="relative">
            <FiSearch className="w-4 h-4 text-[#f4eedf]/60 absolute left-4 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              value={query}
              onChange={handleInputChange}
              onFocus={() => { if (query.trim().length >= 2) setShowDropdown(true); }}
              className="w-full bg-[#0b1322]/80 border border-[#f4eedf]/25 hover:border-[#f4eedf]/45 focus:border-[#e3b23c] rounded-xl py-3.5 pl-11 pr-4 text-[#f4eedf] placeholder-[#f4eedf]/50 focus:outline-none focus:ring-2 focus:ring-[#e3b23c]/25 font-sans font-medium text-sm sm:text-base transition-all"
              placeholder="Search e.g. Hindustan Unilever, Reliance, Apple, NVIDIA..."
              autoComplete="off"
            />
            {searching && (
              <div className="absolute right-3.5 top-3.5 pointer-events-none">
                <svg className="animate-spin h-4 w-4 text-[#e3b23c]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
              </div>
            )}
          </div>
          {renderDropdown()}
        </div>
        
        <div className={vertical ? "w-full" : "w-full sm:w-44"}>
          <label className="block text-xs font-sans font-semibold uppercase tracking-wider text-[#f4eedf]/85 mb-2">
            Exchange
          </label>
          <select
            value={market}
            onChange={(e) => setMarket(e.target.value)}
            className="w-full bg-[#0b1322]/80 border border-[#f4eedf]/25 hover:border-[#f4eedf]/45 focus:border-[#e3b23c] rounded-xl py-3.5 px-3.5 text-sm sm:text-base text-[#f4eedf] focus:outline-none focus:ring-2 focus:ring-[#e3b23c]/25 transition-all cursor-pointer font-sans font-medium"
          >
            <option value="auto">🌐 Auto-detect</option>
            <option value="IN">🇮🇳 India (NSE)</option>
            <option value="US">🇺🇸 US Market</option>
          </select>
        </div>

        <button
          type="submit"
          disabled={loading || !ticker.trim()}
          className={`w-full ${vertical ? '' : 'sm:w-auto px-7'} py-3.5 rounded-xl font-sans text-sm sm:text-base font-bold tracking-tight transition-all flex items-center justify-center gap-1.5 cursor-pointer ${
            loading || !ticker.trim()
              ? 'bg-[#f4eedf]/10 text-[#f4eedf]/40 cursor-not-allowed border border-[#f4eedf]/15' 
              : 'bg-[#e3b23c] hover:bg-[#ecc052] text-[#0d131f] shadow-lg shadow-[#000000]/30 active:scale-[0.99]'
          }`}
        >
          {loading ? (
            <span>Valuating...</span>
          ) : (
            <>
              <span>Run DCF</span>
              <FiArrowUpRight className="w-4 h-4" />
            </>
          )}
        </button>
      </form>
    </div>
  );
}
