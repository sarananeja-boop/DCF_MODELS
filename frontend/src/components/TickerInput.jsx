import React, { useState, useEffect, useRef, useMemo } from 'react';
import axios from 'axios';
import rawStocks from '../data/stocks.json';

// Comprehensive 2,750+ equity database (NSE India & US Markets) for instant 0ms autocomplete
const STOCK_UNIVERSE = rawStocks.map(item => ({
  symbol: item.s,
  name: item.n,
  market: item.m
}));

export default function TickerInput({ 
  ticker, 
  setTicker, 
  market, 
  setMarket, 
  onAnalyze, 
  loading, 
  vertical = false 
}) {
  const [query, setQuery] = useState(ticker);
  const [suggestions, setSuggestions] = useState([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [searching, setSearching] = useState(false);
  const dropdownRef = useRef(null);
  const timeoutRef = useRef(null);
  const searchCache = useRef(new Map());

  // Sync prop changes (e.g. from reset or popular pill clicks) to local query
  useEffect(() => {
    setQuery(ticker);
  }, [ticker]);

  // Handle outside click to close dropdown
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Instant 0ms client-side search across equities with smart relevance ranking
  const filterLocal = (q) => {
    if (!q || q.trim().length < 1) return [];
    const lower = q.trim().toLowerCase();
    const cleanLower = lower.replace(/\.(ns|bo)$/, '');

    const exactMatches = [];
    const prefixSymbolMatches = [];
    const containSymbolMatches = [];
    const nameMatches = [];

    for (let i = 0; i < STOCK_UNIVERSE.length; i++) {
      const item = STOCK_UNIVERSE[i];
      const symClean = item.symbol.replace('.NS', '').replace('.BO', '').toLowerCase();
      const symFull = item.symbol.toLowerCase();
      const name = item.name.toLowerCase();

      if (symClean === cleanLower || symFull === lower) {
        exactMatches.push(item);
      } else if (symClean.startsWith(cleanLower) || symFull.startsWith(lower)) {
        prefixSymbolMatches.push(item);
      } else if (symClean.includes(cleanLower) || symFull.includes(lower)) {
        containSymbolMatches.push(item);
      } else if (name.startsWith(cleanLower) || name.includes(' ' + cleanLower)) {
        nameMatches.push(item);
      }
    }

    // Sort prefix symbol matches by ticker length ascending (e.g. NVDA, NTPC before NIPPOBATRY)
    prefixSymbolMatches.sort((a, b) => {
      const aLen = a.symbol.replace('.NS', '').length;
      const bLen = b.symbol.replace('.NS', '').length;
      return aLen - bLen;
    });

    const combined = [...exactMatches, ...prefixSymbolMatches, ...containSymbolMatches, ...nameMatches];
    const seen = new Set();
    const unique = [];
    for (const item of combined) {
      if (!seen.has(item.symbol)) {
        seen.add(item.symbol);
        unique.push(item);
        if (unique.length >= 8) break;
      }
    }
    return unique;
  };

  const fetchSuggestions = async (q, localMatches = []) => {
    if (!q || q.length < 2) return;
    
    // If local database already provides plenty of high-relevance matches, skip remote network call!
    if (localMatches.length >= 6) {
      return;
    }

    const cacheKey = q.trim().toLowerCase();
    if (searchCache.current.has(cacheKey)) {
      const cached = searchCache.current.get(cacheKey);
      setSuggestions(cached);
      setShowDropdown(cached.length > 0);
      return;
    }

    setSearching(true);
    try {
      const response = await axios.get(`/api/search?q=${encodeURIComponent(q)}`, { timeout: 3500 });
      const remoteResults = response.data.results || [];
      
      // Merge remote results with local matches, avoiding duplicates
      const seen = new Set(localMatches.map(m => m.symbol));
      const combined = [...localMatches];
      for (const item of remoteResults) {
        if (!seen.has(item.symbol)) {
          seen.add(item.symbol);
          const isIN = item.symbol.endsWith('.NS') || item.symbol.endsWith('.BO');
          combined.push({
            symbol: item.symbol,
            name: item.name,
            market: isIN ? 'IN' : 'US'
          });
        }
      }
      const finalSuggestions = combined.slice(0, 8);
      searchCache.current.set(cacheKey, finalSuggestions);
      setSuggestions(finalSuggestions);
      setShowDropdown(finalSuggestions.length > 0);
    } catch (err) {
      // If remote search times out or errors, local matches still shine!
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
    setTicker(val); // optimistic update
    
    // 1. Instant 0ms local match across full database
    const localMatches = filterLocal(val);
    if (localMatches.length > 0) {
      setSuggestions(localMatches);
      setShowDropdown(true);
    } else if (val.trim().length < 2) {
      setSuggestions([]);
      setShowDropdown(false);
    }

    // 2. Debounced background fallback lookup only for ultra-obscure tickers
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => {
      fetchSuggestions(val, localMatches);
    }, 250);
  };

  const handleSelectSuggestion = (sym, name, itemMarket) => {
    const isIN = itemMarket === 'IN' || sym.endsWith('.NS') || sym.endsWith('.BO');
    if (isIN) {
      setMarket('IN');
      const cleanSym = sym.replace('.NS', '').replace('.BO', '');
      setQuery(cleanSym);
      setTicker(cleanSym);
    } else {
      setMarket('US');
      setQuery(sym);
      setTicker(sym);
    }
    setShowDropdown(false);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (ticker.trim()) {
      setShowDropdown(false);
      onAnalyze({}, true);
    }
  };

  return (
    <div className={`bg-zinc-900/50 rounded-2xl border border-zinc-800 shadow-2xl backdrop-blur-md ${vertical ? 'p-4' : 'p-6 sm:p-7'}`}>
      <form onSubmit={handleSubmit} className={`flex ${vertical ? 'flex-col gap-4' : 'flex-col sm:flex-row gap-4 items-end'}`}>
        <div className="flex-1 relative w-full" ref={dropdownRef}>
          <label className="block text-sm font-medium text-zinc-300 mb-2">Company or Ticker Symbol</label>
          <div className="relative">
            <input
              type="text"
              value={query}
              onChange={handleInputChange}
              onFocus={() => { if(suggestions.length > 0) setShowDropdown(true); }}
              className="w-full bg-zinc-950/80 border border-zinc-700/80 hover:border-zinc-600 focus:border-blue-500 rounded-xl py-3 px-4 text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 uppercase font-medium tracking-wide transition-all shadow-inner"
              placeholder="e.g. AAPL, Reliance, HINDUNILVR, NVDA..."
              autoComplete="off"
            />
            {searching && (
              <div className="absolute right-3.5 top-3.5 pointer-events-none">
                <svg className="animate-spin h-5 w-5 text-blue-400 opacity-80" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
              </div>
            )}
          </div>
          
          {/* Instant 0ms Autocomplete Dropdown */}
          {showDropdown && suggestions.length > 0 && (
            <div className="absolute z-50 w-full mt-2 bg-zinc-900 border border-zinc-700/90 rounded-xl shadow-2xl max-h-80 overflow-y-auto overflow-x-hidden divide-y divide-zinc-800/60 backdrop-blur-xl">
              {suggestions.map((item, idx) => {
                const isIN = item.market === 'IN' || item.symbol.endsWith('.NS');
                const cleanSymbol = item.symbol.replace('.NS', '').replace('.BO', '');
                return (
                  <div 
                    key={idx}
                    onClick={() => handleSelectSuggestion(item.symbol, item.name, item.market)}
                    className="px-4 py-2.5 hover:bg-zinc-800/90 cursor-pointer flex items-center justify-between gap-3 transition-colors group"
                  >
                    <div className="flex items-center gap-3 min-w-0 flex-1">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border shrink-0 ${
                        isIN 
                          ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' 
                          : 'bg-blue-500/10 text-blue-400 border-blue-500/20'
                      }`}>
                        {isIN ? 'NSE' : 'US'}
                      </span>
                      <div className="flex flex-col min-w-0 overflow-hidden">
                        <span className="font-semibold text-sm text-zinc-100 group-hover:text-blue-400 transition-colors truncate">
                          {cleanSymbol}
                        </span>
                        <span className="text-xs text-zinc-400 truncate max-w-[280px] sm:max-w-md font-normal">
                          {item.name}
                        </span>
                      </div>
                    </div>
                    <span className="text-[11px] text-zinc-500 font-mono shrink-0 hidden sm:inline-block">
                      {isIN ? '₹ INR' : '$ USD'}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        
        <div className={vertical ? "w-full" : "w-full sm:w-48"}>
          <label className="block text-sm font-medium text-zinc-300 mb-2">Market</label>
          <select
            value={market}
            onChange={(e) => setMarket(e.target.value)}
            className="w-full bg-zinc-950/80 border border-zinc-700/80 hover:border-zinc-600 focus:border-blue-500 rounded-xl py-3 px-3.5 text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 transition-all cursor-pointer font-medium"
          >
            <option value="auto">🌐 Auto-detect</option>
            <option value="US">🇺🇸 US Market</option>
            <option value="IN">🇮🇳 Indian Market</option>
          </select>
        </div>

        <button
          type="submit"
          disabled={loading || !ticker.trim()}
          className={`w-full ${vertical ? '' : 'sm:w-auto px-8'} py-3 rounded-xl font-bold tracking-wide transition-all ${
            loading || !ticker.trim()
              ? 'bg-zinc-800/50 text-zinc-500 cursor-not-allowed border border-zinc-800' 
              : 'bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-600/25 hover:shadow-blue-500/35 active:scale-[0.98]'
          }`}
        >
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="animate-spin h-4 w-4 text-current" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Analyzing...
            </span>
          ) : (
            'Run DCF'
          )}
        </button>
      </form>
    </div>
  );
}
