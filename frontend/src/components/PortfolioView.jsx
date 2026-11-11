import React, { useState } from 'react';
import {
  Wallet,
  TrendingUp,
  TrendingDown,
  PieChart,
  History,
  RotateCcw,
  CheckCircle,
  ExternalLink,
  ShieldCheck,
  Ban
} from 'lucide-react';
import { api } from '../api';

export default function PortfolioView({
  account,
  positions = [],
  trades = [],
  onRefreshPortfolio,
}) {
  const [activeTab, setActiveTab] = useState('positions'); // 'positions' | 'trades'
  const [isSquaringOff, setIsSquaringOff] = useState(false);

  const handleSquareOffAll = async () => {
    if (!window.confirm('Are you sure you want to square off all intraday (MIS) positions?')) return;
    setIsSquaringOff(true);
    try {
      await api.squareOff(1);
      if (onRefreshPortfolio) onRefreshPortfolio();
    } catch (e) {
      alert(`Square-off error: ${e.message}`);
    } finally {
      setIsSquaringOff(false);
    }
  };

  const cash = account?.cash_balance ?? 1000000;
  const portfolioVal = account?.portfolio_value ?? cash;
  const unrealizedPnl = account?.unrealized_pnl ?? 0;
  const realizedPnl = account?.realized_pnl ?? 0;
  const totalPnl = unrealizedPnl + realizedPnl;

  return (
    <div className="flex flex-col gap-4">
      {/* Account KPI Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {/* Cash Balance */}
        <div className="bg-[#1A1F29] border border-[#2A313C] rounded-lg p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between text-[#9CA3AF] text-xs">
            <span className="font-mono uppercase tracking-wider">Available Cash</span>
            <Wallet className="w-4 h-4 text-[#3B82F6]" />
          </div>
          <div className="mt-2">
            <div className="text-lg font-bold font-mono text-[#F9FAFB]">
              ₹{cash.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
            </div>
            <span className="text-[11px] text-[#9CA3AF]">Initial: ₹10,00,000.00</span>
          </div>
        </div>

        {/* Total Portfolio Value */}
        <div className="bg-[#1A1F29] border border-[#2A313C] rounded-lg p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between text-[#9CA3AF] text-xs">
            <span className="font-mono uppercase tracking-wider">Portfolio Equity</span>
            <PieChart className="w-4 h-4 text-[#60A5FA]" />
          </div>
          <div className="mt-2">
            <div className="text-lg font-bold font-mono text-[#F9FAFB]">
              ₹{portfolioVal.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
            </div>
            <span className="text-[11px] text-[#9CA3AF]">Cash + Open Holdings</span>
          </div>
        </div>

        {/* Unrealized P&L */}
        <div className="bg-[#1A1F29] border border-[#2A313C] rounded-lg p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between text-[#9CA3AF] text-xs">
            <span className="font-mono uppercase tracking-wider">Unrealized P&L</span>
            {unrealizedPnl >= 0 ? (
              <TrendingUp className="w-4 h-4 text-[#34D399]" />
            ) : (
              <TrendingDown className="w-4 h-4 text-[#F87171]" />
            )}
          </div>
          <div className="mt-2">
            <div
              className={`text-lg font-bold font-mono ${
                unrealizedPnl >= 0 ? 'text-[#34D399]' : 'text-[#F87171]'
              }`}
            >
              {unrealizedPnl >= 0 ? '+' : ''}₹{unrealizedPnl.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
            </div>
            <span className="text-[11px] text-[#9CA3AF]">Open Positions</span>
          </div>
        </div>

        {/* Realized P&L */}
        <div className="bg-[#1A1F29] border border-[#2A313C] rounded-lg p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between text-[#9CA3AF] text-xs">
            <span className="font-mono uppercase tracking-wider">Realized P&L</span>
            {realizedPnl >= 0 ? (
              <TrendingUp className="w-4 h-4 text-[#34D399]" />
            ) : (
              <TrendingDown className="w-4 h-4 text-[#F87171]" />
            )}
          </div>
          <div className="mt-2">
            <div
              className={`text-lg font-bold font-mono ${
                realizedPnl >= 0 ? 'text-[#34D399]' : 'text-[#F87171]'
              }`}
            >
              {realizedPnl >= 0 ? '+' : ''}₹{realizedPnl.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
            </div>
            <span className="text-[11px] text-[#9CA3AF]">Closed Trades (Net ₹20 fees)</span>
          </div>
        </div>
      </div>

      {/* Tabs & Table Header */}
      <div className="bg-[#1A1F29] border border-[#2A313C] rounded-lg overflow-hidden flex flex-col">
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#2A313C] bg-[#11161F]">
          <div className="flex items-center gap-1">
            <button
              onClick={() => setActiveTab('positions')}
              className={`px-3 py-1.5 rounded text-xs font-semibold uppercase tracking-wider transition-colors ${
                activeTab === 'positions'
                  ? 'bg-[#1E3A5F] text-[#60A5FA] border border-[#3B82F6]/30'
                  : 'text-[#9CA3AF] hover:text-[#F9FAFB]'
              }`}
            >
              Open Positions ({positions.length})
            </button>
            <button
              onClick={() => setActiveTab('trades')}
              className={`px-3 py-1.5 rounded text-xs font-semibold uppercase tracking-wider transition-colors ${
                activeTab === 'trades'
                  ? 'bg-[#1E3A5F] text-[#60A5FA] border border-[#3B82F6]/30'
                  : 'text-[#9CA3AF] hover:text-[#F9FAFB]'
              }`}
            >
              Today's Trades ({trades.length})
            </button>
          </div>

          {activeTab === 'positions' && positions.length > 0 && (
            <button
              onClick={handleSquareOffAll}
              disabled={isSquaringOff}
              className="px-2.5 py-1 text-xs font-mono font-medium rounded bg-[#0E1116] text-[#F87171] border border-[#F87171]/40 hover:bg-[#EF4444] hover:text-[#0E1116] disabled:opacity-50 transition-colors"
            >
              {isSquaringOff ? 'Squaring off...' : 'Square Off All (MIS)'}
            </button>
          )}
        </div>

        {/* Positions View */}
        {activeTab === 'positions' && (
          <div className="overflow-x-auto">
            {positions.length === 0 ? (
              <div className="p-8 text-center text-[#9CA3AF] text-xs font-mono">
                No open positions at this time.
              </div>
            ) : (
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-[#0E1116] text-[#9CA3AF] border-b border-[#2A313C] uppercase text-[10px]">
                  <tr>
                    <th className="py-2.5 px-4">Symbol</th>
                    <th className="py-2.5 px-3">Product</th>
                    <th className="py-2.5 px-3 text-right">Quantity</th>
                    <th className="py-2.5 px-3 text-right">Avg Entry</th>
                    <th className="py-2.5 px-3 text-right">LTP</th>
                    <th className="py-2.5 px-4 text-right">Unrealized P&L</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#2A313C]">
                  {positions.map((pos) => {
                    const avgPrice = pos.average_price ?? pos.avg_price ?? 0;
                    const pnl = pos.unrealized_pnl ?? 0;
                    const pnlPct = avgPrice ? (pnl / (avgPrice * pos.quantity)) * 100 : 0;
                    return (
                      <tr key={pos.position_id || pos.id} className="hover:bg-[#0E1116]/50 transition-colors">
                        <td className="py-3 px-4 font-bold text-[#F9FAFB]">{pos.symbol}</td>
                        <td className="py-3 px-3">
                          <span className="px-1.5 py-0.5 rounded text-[10px] bg-[#0E1116] border border-[#2A313C] text-[#9CA3AF]">
                            {pos.product_type}
                          </span>
                        </td>
                        <td className="py-3 px-3 text-right text-[#F9FAFB]">{pos.quantity}</td>
                        <td className="py-3 px-3 text-right text-[#D1D5DB]">₹{avgPrice.toFixed(2)}</td>
                        <td className="py-3 px-3 text-right text-[#D1D5DB]">
                          ₹{pos.current_price ? pos.current_price.toFixed(2) : '-'}
                        </td>
                        <td
                          className={`py-3 px-4 text-right font-semibold ${
                            pnl >= 0 ? 'text-[#34D399]' : 'text-[#F87171]'
                          }`}
                        >
                          {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(2)}{' '}
                          <span className="text-[10px] opacity-80">({pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%)</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* Trades Ledger View */}
        {activeTab === 'trades' && (
          <div className="overflow-x-auto">
            {trades.length === 0 ? (
              <div className="p-8 text-center text-[#9CA3AF] text-xs font-mono">
                No trades executed yet today.
              </div>
            ) : (
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-[#0E1116] text-[#9CA3AF] border-b border-[#2A313C] uppercase text-[10px]">
                  <tr>
                    <th className="py-2.5 px-4">Time</th>
                    <th className="py-2.5 px-3">Symbol</th>
                    <th className="py-2.5 px-3">Side</th>
                    <th className="py-2.5 px-3 text-right">Qty</th>
                    <th className="py-2.5 px-3 text-right">Price</th>
                    <th className="py-2.5 px-3 text-right">Fee</th>
                    <th className="py-2.5 px-4 text-right">Realized P&L</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#2A313C]">
                  {trades.map((t) => {
                    const isBuy = t.side === 'BUY';
                    const rawTime = t.executed_at || t.timestamp || '';
                    const timeOnly = rawTime ? (rawTime.includes('T') ? rawTime.split('T')[1].slice(0, 8) : rawTime.split(' ')[1] || rawTime) : '';
                    return (
                      <tr key={t.trade_id || t.id} className="hover:bg-[#0E1116]/50 transition-colors">
                        <td className="py-3 px-4 text-[#9CA3AF] text-[11px]">{timeOnly}</td>
                        <td className="py-3 px-3 font-bold text-[#F9FAFB]">{t.symbol}</td>
                        <td className="py-3 px-3">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                              isBuy
                                ? 'bg-[#064E3B] text-[#34D399] border border-[#34D399]/30'
                                : 'bg-[#3A2E0F] text-[#F87171] border border-[#F87171]/30'
                            }`}
                          >
                            {t.side}
                          </span>
                        </td>
                        <td className="py-3 px-3 text-right text-[#F9FAFB]">{t.quantity}</td>
                        <td className="py-3 px-3 text-right text-[#D1D5DB]">₹{t.price.toFixed(2)}</td>
                        <td className="py-3 px-3 text-right text-[#9CA3AF]">₹{t.charges?.toFixed(2) || '20.00'}</td>
                        <td
                          className={`py-3 px-4 text-right font-semibold ${
                            t.realized_pnl === null || t.realized_pnl === undefined
                              ? 'text-[#9CA3AF]'
                              : t.realized_pnl >= 0
                              ? 'text-[#34D399]'
                              : 'text-[#F87171]'
                          }`}
                        >
                          {t.realized_pnl !== null && t.realized_pnl !== undefined
                            ? `${t.realized_pnl >= 0 ? '+' : ''}₹${t.realized_pnl.toFixed(2)}`
                            : '-'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
