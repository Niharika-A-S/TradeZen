import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="bg-[#11161F] border border-[#2A313C] rounded-xl p-8 max-w-xl mx-auto my-12 text-center space-y-4 shadow-xl">
          <div className="w-12 h-12 rounded-full bg-[#EF4444]/15 text-[#EF4444] flex items-center justify-center mx-auto border border-[#EF4444]/30">
            <AlertTriangle className="w-6 h-6" />
          </div>
          <h3 className="text-base font-bold text-[#F9FAFB]">
            {this.props.fallbackTitle || 'A view rendering error occurred'}
          </h3>
          <p className="text-xs text-[#9CA3AF] max-w-md mx-auto leading-relaxed">
            {this.state.error?.message || 'An unexpected error occurred while loading this view.'}
          </p>
          <div className="pt-2">
            <button
              type="button"
              onClick={this.handleReset}
              className="inline-flex items-center gap-2 bg-[#2563EB] hover:bg-[#1D4ED8] text-white px-4 py-2 rounded-lg text-xs font-semibold transition-all shadow"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Retry / Reload View</span>
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
