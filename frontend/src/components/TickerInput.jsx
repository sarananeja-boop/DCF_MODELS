import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';

export default function TickerInput({ ticker, setTicker, market, setMarket, onAnalyze, loading }) {
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
    // If user picks an .NS stock, auto-switch market to IN
    if (sym.endsWith('.NS') || sym.endsWith('.BO')) {
      // Strip .NS since backend appends it for Indian Market, or keep it?
      // Our backend says "Appends market suffix if needed", so if we send RELIANCE and IN it appends .NS.
      // Let's strip the .NS for cleaner UI if we also set market to IN.
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
      onAnalyze(); // App.jsx expects no args, uses its own state
    }
  };

  return (
    <div className="bg-navy-800 p-4 rounded-lg shadow-lg mb-6 border border-navy-600">
      <form onSubmit={handleSubmit} className="flex flex-col md:flex-row gap-4 items-end">
        <div className="flex-1 relative" ref={dropdownRef}>
          <label className="block text-sm font-medium text-text-secondary mb-1">Company or Ticker Symbol</label>
          <input
            type="text"
            value={query}
            onChange={handleInputChange}
            onFocus={() => { if(suggestions.length > 0) setShowDropdown(true); }}
            className="w-full bg-navy-900 border border-navy-600 rounded-md py-2 px-3 text-white focus:outline-none focus:border-accent-blue focus:ring-1 focus:ring-accent-blue uppercase"
            placeholder="e.g. Reliance, TCS, Apple..."
            autoComplete="off"
          />
          
          {/* Autocomplete Dropdown */}
          {showDropdown && suggestions.length > 0 && (
            <div className="absolute z-50 w-full mt-1 bg-navy-900 border border-navy-600 rounded-md shadow-2xl max-h-60 overflow-y-auto">
              {suggestions.map((item, idx) => (
                <div 
                  key={idx}
                  onClick={() => handleSelectSuggestion(item.symbol, item.name)}
                  className="px-4 py-2 hover:bg-navy-700 cursor-pointer flex justify-between items-center border-b border-navy-800 last:border-0"
                >
                  <span className="font-semibold text-accent-blue">{item.symbol}</span>
                  <span className="text-xs text-text-secondary truncate ml-4 max-w-[200px] text-right">{item.name}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        
        <div className="w-48">
          <label className="block text-sm font-medium text-text-secondary mb-1">Market</label>
          <select
            value={market}
            onChange={(e) => setMarket(e.target.value)}
            className="w-full bg-navy-900 border border-navy-600 rounded-md py-2 px-3 text-white focus:outline-none focus:border-accent-blue focus:ring-1 focus:ring-accent-blue"
          >
            <option value="auto">Auto-detect</option>
            <option value="US">US Market</option>
            <option value="IN">Indian Market</option>
          </select>
        </div>

        <button
          type="submit"
          disabled={loading || !ticker.trim()}
          className={`px-6 py-2 rounded-md font-semibold text-white transition-all ${
            loading || !ticker.trim()
              ? 'bg-navy-600 cursor-not-allowed opacity-70' 
              : 'bg-gradient-to-r from-accent-blue to-indigo-600 hover:shadow-lg hover:shadow-accent-blue/30'
          }`}
        >
          {loading ? (
            <span className="flex items-center gap-2">
              <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
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
