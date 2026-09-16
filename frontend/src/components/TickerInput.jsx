import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';

export default function TickerInput({ ticker, setTicker, market, setMarket, onAnalyze, loading, vertical = false }) {
  const [query, setQuery] = useState(ticker);
  const [suggestions, setSuggestions] = useState([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [searching, setSearching] = useState(false);
  const dropdownRef = useRef(null);
  const timeoutRef = useRef(null);

  // Sync prop changes (e.g. from reset or initial) to local query
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

  const fetchSuggestions = async (q) => {
    if (!q || q.length < 2) {
      setSuggestions([]);
      setShowDropdown(false);
      return;
    }
    
    setSearching(true);
    try {
      const response = await axios.get(`/api/search?q=${encodeURIComponent(q)}`);
      setSuggestions(response.data.results || []);
      setShowDropdown(true);
    } catch (err) {
      console.error("Search failed:", err);
    } finally {
      setSearching(false);
    }
  };

  const handleInputChange = (e) => {
    const val = e.target.value;
    setQuery(val);
    setTicker(val); // optimistic update
    
    // Debounce search
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => {
      fetchSuggestions(val);
    }, 300);
  };

  const handleSelectSuggestion = (sym, name) => {
    if (sym.endsWith('.NS') || sym.endsWith('.BO')) {
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
      onAnalyze();
    }
  };

  return (
    <div className={`bg-zinc-900/40 rounded-xl border border-zinc-800/80 shadow-xl backdrop-blur-sm ${vertical ? 'p-4 mb-6' : 'p-6'}`}>
      <form onSubmit={handleSubmit} className={`flex ${vertical ? 'flex-col gap-4' : 'flex-col sm:flex-row gap-4 items-end'}`}>
        <div className="flex-1 relative w-full" ref={dropdownRef}>
          <label className="block text-sm font-medium text-zinc-400 mb-1.5">Company or Ticker Symbol</label>
          <input
            type="text"
            value={query}
            onChange={handleInputChange}
            onFocus={() => { if(suggestions.length > 0) setShowDropdown(true); }}
            className="w-full bg-zinc-950/60 border border-zinc-800 rounded-lg py-2.5 px-4 text-zinc-100 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30 uppercase transition-all"
            placeholder="e.g. Reliance, TCS, Apple..."
            autoComplete="off"
          />
          
          {/* Autocomplete Dropdown */}
          {showDropdown && suggestions.length > 0 && (
            <div className="absolute z-50 w-full mt-2 bg-zinc-900 border border-zinc-800 rounded-lg shadow-2xl max-h-60 overflow-y-auto overflow-x-hidden">
              {suggestions.map((item, idx) => (
                <div 
                  key={idx}
                  onClick={() => handleSelectSuggestion(item.symbol, item.name)}
                  className="px-4 py-3 hover:bg-zinc-800/80 cursor-pointer flex justify-between items-center border-b border-zinc-800/50 last:border-0 transition-colors"
                >
                  <span className="font-semibold text-blue-400">{item.symbol}</span>
                  <span className="text-xs text-zinc-500 truncate ml-4 max-w-[150px] sm:max-w-[200px] text-right">{item.name}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        
        <div className={vertical ? "w-full" : "w-48"}>
          <label className="block text-sm font-medium text-zinc-400 mb-1.5">Market</label>
          <select
            value={market}
            onChange={(e) => setMarket(e.target.value)}
            className="w-full bg-zinc-950/60 border border-zinc-800 rounded-lg py-2.5 px-3 text-zinc-100 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30 transition-all appearance-none"
          >
            <option value="auto">Auto-detect</option>
            <option value="US">US Market</option>
            <option value="IN">Indian Market</option>
          </select>
        </div>

        <button
          type="submit"
          disabled={loading || !ticker.trim()}
          className={`w-full ${vertical ? '' : 'sm:w-auto px-8'} py-2.5 rounded-lg font-semibold transition-all ${
            loading || !ticker.trim()
              ? 'bg-zinc-800/50 text-zinc-500 cursor-not-allowed' 
              : 'bg-zinc-100 hover:bg-zinc-200 text-zinc-950 shadow-lg shadow-zinc-100/10'
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
            'Analyze'
          )}
        </button>
      </form>
    </div>
  );
}
