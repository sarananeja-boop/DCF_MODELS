import React from 'react';
import { FiAlertTriangle, FiRefreshCw } from 'react-icons/fi';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="bg-zinc-900 border border-red-500/40 rounded-xl p-6 my-4 text-center">
          <div className="flex justify-center mb-3">
            <div className="p-3 bg-red-500/10 rounded-full text-red-400">
              <FiAlertTriangle size={32} />
            </div>
          </div>
          <h3 className="text-lg font-semibold text-slate-100 mb-2">Something went wrong in this tab</h3>
          <p className="text-sm text-slate-400 max-w-md mx-auto mb-4 font-mono text-xs bg-zinc-950 p-2 rounded border border-zinc-800 text-red-300">
            {this.state.error?.toString() || "Unknown rendering error"}
          </p>
          <button
            onClick={this.handleReset}
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium transition-colors"
          >
            <FiRefreshCw size={16} /> Reload Platform
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
