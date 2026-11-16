import React, { useState, useEffect } from 'react';
import {
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  CheckCircle2,
  DollarSign,
  ShieldAlert,
  ArrowUpRight,
  ArrowDownRight,
  Loader2
} from 'lucide-react';
import CandlestickChart from './CandlestickChart';
import { api } from '../api';

const REASON_MESSAGES = {
  token_problem: 'Token Problem',
  connecting: 'Connecting...',
  market_closed: 'Market Closed',
  no_ticks_yet: 'Waiting for ticks...',
  feed_error: 'Feed Error',
  feed_disabled: 'Feed Disabled',
  live_feed_not_installed: 'Feed Not Installed',
  unknown_symbol: 'Unknown Symbol',
};

const formatIST = (isoStr) => {
  if (!isoStr) return '--:--:-- IST';
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) {
      return String(isoStr).slice(11, 19) + ' IST';
    }
    return d.toLocaleTimeString('en-IN', { hour12: false, timeZone: 'Asia/Kolkata' }) + ' IST';
  } catch {
    return String(isoStr).slice(11, 19) + ' IST';
  }
};

export default function TradingView({
  symbols = ['INFY', 'RELIANCE', 'TCS', 'HDFCBANK', 'SBIN'],
  selectedSymbol,
  onSelectSymbol,
  currentPrice,
  bars,
  onOrderPlaced,
  userRules,
  userId = 1,
  isLiveMode = false,
  livePrices = {},
}) {
  const [side, setSide] = useState('BUY');
  const [orderType, setOrderType] = useState('MARKET');
  const [quantity, setQuantity] = useState(10);
  const [limitPrice, setLimitPrice] = useState('');
  const [stopLoss, setStopLoss] = useState('');
  const [productType, setProductType] = useState('MIS');

  const [isChecking, setIsChecking] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [preCheckWarnings, setPreCheckWarnings] = useState(null);
  const [showWarningModal, setShowWarningModal] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [submitSuccess, setSubmitSuccess] = useState(null);

  // Current effective price (live tick if in live mode, else replay bar close)
  const selectedLive = isLiveMode ? livePrices?.[selectedSymbol] : null;
  const liveLtp = selectedLive?.ok ? selectedLive.ltp : null;
  const effectiveMarketPrice = isLiveMode ? liveLtp : (currentPrice?.close || null);

  // Sync limit price default to current market price
  useEffect(() => {
    const priceToSync = effectiveMarketPrice;
    if (priceToSync && !limitPrice) {
      setLimitPrice(priceToSync.toFixed(2));
    }
  }, [effectiveMarketPrice]);

  const activePrice = orderType === 'LIMIT' && limitPrice ? parseFloat(limitPrice) : (effectiveMarketPrice || 0);
  const orderValue = activePrice * (quantity || 0);

  // Suggested risk estimation based on stop loss
  const estimatedRisk = stopLoss && activePrice
    ? Math.abs(activePrice - parseFloat(stopLoss)) * quantity
    : null;

  const handlePreCheckAndPlace = async (forceBypass = false) => {
    setSubmitError(null);
    setSubmitSuccess(null);

    const priceNum = orderType === 'LIMIT' ? parseFloat(limitPrice) : null;
    const stopLossNum = stopLoss ? parseFloat(stopLoss) : null;

    if (!quantity || quantity <= 0) {
      setSubmitError('Quantity must be greater than 0.');
      return;
    }
    if (orderType === 'LIMIT' && (!priceNum || priceNum <= 0)) {
      setSubmitError('Please specify a valid limit price.');
      return;
    }
    if (orderType === 'MARKET' && (!activePrice || activePrice <= 0)) {
      setSubmitError('Market price is currently unavailable. Please wait for a live quote or place a Limit order.');
      return;
    }

    const payload = {
      user_id: userId,
      symbol: selectedSymbol,
      side: side,
      order_type: orderType,
      quantity: parseInt(quantity, 10),
      price: priceNum,
      product_type: productType,
      stop_loss: stopLossNum,
      apply_slippage: true,
    };

    // If not bypassing, check rules first
    if (!forceBypass) {
      setIsChecking(true);
      try {
        const checkResult = await api.preCheckOrder(payload);
        if (checkResult.has_warnings && checkResult.warnings.length > 0) {
          setPreCheckWarnings(checkResult.warnings);
          setShowWarningModal(true);
          setIsChecking(false);
          return;
        }
      } catch (err) {
        console.warn('Pre-check error:', err);
      } finally {
        setIsChecking(false);
      }
    }

    // Proceed to place order
    setIsSubmitting(true);
    try {
      const order = await api.placeOrder(payload);
      setShowWarningModal(false);
      setPreCheckWarnings(null);
      setSubmitSuccess(`Order #${order.order_id || order.id} placed: ${order.side} ${order.quantity} ${order.symbol} @ ₹${(order.average_fill_price || order.execution_price || activePrice).toFixed(2)}`);
      if (onOrderPlaced) onOrderPlaced(order);
    } catch (err) {
      setSubmitError(err.message || 'Failed to place order.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Stock Selection Pills */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-[#11161F] p-3 rounded-lg border border-[#2A313C]">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-[#9CA3AF] uppercase font-mono mr-1">Watchlist:</span>
          {symbols.map((sym) => {
            const isSelected = sym === selectedSymbol;
            const symLive = isLiveMode ? livePrices?.[sym] : null;

            return (
              <button
                key={sym}
                onClick={() => onSelectSymbol(sym)}
                className={`px-3 py-1.5 rounded text-xs font-semibold font-mono tracking-wider transition-all flex items-center gap-1.5 ${
                  isSelected
                    ? 'bg-[#3B82F6] text-[#F9FAFB] shadow-md shadow-[#3B82F6]/20'
                    : 'bg-[#1A1F29] text-[#D1D5DB] border border-[#2A313C] hover:border-[#3B82F6]/50 hover:text-[#F9FAFB]'
                }`}
              >
                <span>{sym}</span>
                {isLiveMode && symLive?.ok && symLive?.ltp && (
                  <span className="text-[11px] font-normal opacity-90">
                    ₹{Number(symLive.ltp).toFixed(1)}
                  </span>
                )}
                {isLiveMode && symLive?.ok && symLive?.change_pct !== null && symLive?.change_pct !== undefined && (
                  <span
                    className={`text-[10px] font-bold ${
                      symLive.change_pct >= 0 ? 'text-[#34D399]' : 'text-[#F87171]'
                    }`}
                  >
                    {symLive.change_pct >= 0 ? '+' : ''}
                    {Number(symLive.change_pct).toFixed(1)}%
                  </span>
                )}
                {isLiveMode && symLive && !symLive.ok && (
                  <span className="text-[9px] px-1 py-0.2 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
                    {REASON_MESSAGES[symLive.reason] || 'Offline'}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Price & Status Header for Selected Stock */}
        {isLiveMode ? (
          <div className="flex items-center gap-4">
            {selectedLive?.ok ? (
              <>
                <div className="text-right">
                  <div className="flex items-center justify-end gap-1.5 mb-0.5">
                    <span className="text-xs text-[#9CA3AF] font-mono">Live LTP</span>
                    {selectedLive.market_status && selectedLive.market_status !== 'NORMAL_OPEN' && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wider bg-amber-500/20 text-amber-400 border border-amber-500/40">
                        MARKET CLOSED
                      </span>
                    )}
                    {selectedLive.stale && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wider bg-yellow-500/20 text-yellow-300 border border-yellow-500/40">
                        STALE
                      </span>
                    )}
                  </div>
                  <div className="flex items-baseline justify-end gap-2">
                    <span className="text-lg font-bold font-mono text-[#F9FAFB]">
                      ₹{Number(selectedLive.ltp).toFixed(2)}
                    </span>
                    {selectedLive.change !== null && selectedLive.change !== undefined && (
                      <span
                        className={`text-xs font-mono font-semibold ${
                          selectedLive.change >= 0 ? 'text-[#34D399]' : 'text-[#F87171]'
                        }`}
                      >
                        {selectedLive.change >= 0 ? '+' : ''}
                        ₹{Number(selectedLive.change).toFixed(2)} (
                        {selectedLive.change_pct >= 0 ? '+' : ''}
                        {Number(selectedLive.change_pct).toFixed(2)}%)
                      </span>
                    )}
                  </div>
                </div>

                <div className="text-right pl-3 border-l border-[#2A313C]">
                  <span className="text-[10px] text-[#9CA3AF] font-mono block">Last Trade (IST)</span>
                  <span className="text-xs font-mono text-[#D1D5DB]">
                    {formatIST(selectedLive.last_trade_time)}
                  </span>
                </div>
              </>
            ) : (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded bg-[#1A1F29] border border-amber-500/30 text-amber-400 text-xs font-mono">
                <AlertTriangle className="w-4 h-4 shrink-0 text-amber-400" />
                <span>
                  {selectedLive?.reason
                    ? (REASON_MESSAGES[selectedLive.reason] || selectedLive.reason)
                    : 'Connecting to Live Feed...'}
                </span>
                {selectedLive?.detail && (
                  <span className="text-[10px] text-[#9CA3AF] max-w-xs truncate" title={selectedLive.detail}>
                    ({selectedLive.detail})
                  </span>
                )}
              </div>
            )}
          </div>
        ) : (
          currentPrice && (
            <div className="flex items-center gap-4">
              <div className="text-right">
                <span className="text-xs text-[#9CA3AF] font-mono block">Replay Price</span>
                <span className="text-lg font-bold font-mono text-[#F9FAFB]">
                  ₹{Number(currentPrice.close).toFixed(2)}
                </span>
              </div>
              <div className="text-right pl-3 border-l border-[#2A313C]">
                <span className="text-[10px] text-[#9CA3AF] font-mono block">Day Range</span>
                <span className="text-xs font-mono text-[#D1D5DB]">
                  ₹{Number(currentPrice.low).toFixed(1)} - ₹{Number(currentPrice.high).toFixed(1)}
                </span>
              </div>
            </div>
          )
        )}
      </div>

      {/* Main Trading Workspace: Candlestick Chart (Left/Center) + Order Entry (Right) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Candlestick Chart Box */}
        <div className="lg:col-span-8 flex flex-col gap-2">
          <CandlestickChart
            bars={bars}
            symbol={selectedSymbol}
            currentPrice={effectiveMarketPrice || currentPrice?.close}
            isLiveMode={isLiveMode}
          />
        </div>

        {/* Order Entry Form */}
        <div className="lg:col-span-4 bg-[#1A1F29] border border-[#2A313C] rounded-lg p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-3 mb-3 border-b border-[#2A313C]">
              <h2 className="text-sm font-bold text-[#F9FAFB] uppercase tracking-wider">Place Order</h2>
              <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-[#0E1116] border border-[#2A313C] text-[#9CA3AF]">
                {selectedSymbol}
              </span>
            </div>

            {/* BUY / SELL Direction Buttons */}
            <div className="grid grid-cols-2 gap-2 mb-3">
              <button
                type="button"
                onClick={() => setSide('BUY')}
                className={`py-2 rounded font-bold text-xs uppercase tracking-wider transition-colors ${
                  side === 'BUY'
                    ? 'bg-[#34D399] text-[#0E1116] shadow-sm'
                    : 'bg-[#0E1116] text-[#9CA3AF] border border-[#2A313C] hover:text-[#34D399]'
                }`}
              >
                BUY / Long
              </button>
              <button
                type="button"
                onClick={() => setSide('SELL')}
                className={`py-2 rounded font-bold text-xs uppercase tracking-wider transition-colors ${
                  side === 'SELL'
                    ? 'bg-[#F87171] text-[#0E1116] shadow-sm'
                    : 'bg-[#0E1116] text-[#9CA3AF] border border-[#2A313C] hover:text-[#F87171]'
                }`}
              >
                SELL / Short
              </button>
            </div>

            {/* Order Type & Product Type Selectors */}
            <div className="grid grid-cols-2 gap-2 mb-3">
              <div>
                <label className="block text-[11px] font-mono text-[#9CA3AF] mb-1">Order Type</label>
                <div className="grid grid-cols-2 gap-1 bg-[#0E1116] p-0.5 rounded border border-[#2A313C]">
                  <button
                    type="button"
                    onClick={() => setOrderType('MARKET')}
                    className={`py-1 text-[11px] font-mono font-medium rounded ${
                      orderType === 'MARKET' ? 'bg-[#1E3A5F] text-[#60A5FA]' : 'text-[#9CA3AF]'
                    }`}
                  >
                    MKT
                  </button>
                  <button
                    type="button"
                    onClick={() => setOrderType('LIMIT')}
                    className={`py-1 text-[11px] font-mono font-medium rounded ${
                      orderType === 'LIMIT' ? 'bg-[#1E3A5F] text-[#60A5FA]' : 'text-[#9CA3AF]'
                    }`}
                  >
                    LMT
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-mono text-[#9CA3AF] mb-1">Product</label>
                <div className="grid grid-cols-2 gap-1 bg-[#0E1116] p-0.5 rounded border border-[#2A313C]">
                  <button
                    type="button"
                    onClick={() => setProductType('MIS')}
                    className={`py-1 text-[11px] font-mono font-medium rounded ${
                      productType === 'MIS' ? 'bg-[#1E3A5F] text-[#60A5FA]' : 'text-[#9CA3AF]'
                    }`}
                  >
                    MIS
                  </button>
                  <button
                    type="button"
                    onClick={() => setProductType('CNC')}
                    className={`py-1 text-[11px] font-mono font-medium rounded ${
                      productType === 'CNC' ? 'bg-[#1E3A5F] text-[#60A5FA]' : 'text-[#9CA3AF]'
                    }`}
                  >
                    CNC
                  </button>
                </div>
              </div>
            </div>

            {/* Quantity Input */}
            <div className="mb-3">
              <label className="block text-[11px] font-mono text-[#9CA3AF] mb-1">Quantity</label>
              <input
                type="number"
                min="1"
                value={quantity}
                onChange={(e) => setQuantity(parseInt(e.target.value, 10) || '')}
                className="w-full bg-[#0E1116] text-[#F9FAFB] border border-[#2A313C] rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-[#3B82F6]"
                placeholder="Shares"
              />
            </div>

            {/* Limit Price Input if LIMIT */}
            {orderType === 'LIMIT' && (
              <div className="mb-3">
                <label className="block text-[11px] font-mono text-[#9CA3AF] mb-1">Limit Price (₹)</label>
                <input
                  type="number"
                  step="0.05"
                  value={limitPrice}
                  onChange={(e) => setLimitPrice(e.target.value)}
                  className="w-full bg-[#0E1116] text-[#F9FAFB] border border-[#2A313C] rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-[#3B82F6]"
                  placeholder="Price"
                />
              </div>
            )}

            {/* Stop Loss Input */}
            <div className="mb-3">
              <div className="flex justify-between items-center mb-1">
                <label className="text-[11px] font-mono text-[#9CA3AF]">Stop Loss Price (₹)</label>
                {userRules?.require_stop_loss && (
                  <span className="text-[10px] text-[#FBBF24] font-mono">Required by Rule</span>
                )}
              </div>
              <input
                type="number"
                step="0.05"
                value={stopLoss}
                onChange={(e) => setStopLoss(e.target.value)}
                className={`w-full bg-[#0E1116] text-[#F9FAFB] border rounded px-3 py-1.5 text-sm font-mono focus:outline-none ${
                  !stopLoss && userRules?.require_stop_loss
                    ? 'border-[#FBBF24]/50 focus:border-[#FBBF24]'
                    : 'border-[#2A313C] focus:border-[#3B82F6]'
                }`}
                placeholder="Optional SL trigger"
              />
            </div>

            {/* Order Summary Calc */}
            <div className="bg-[#0E1116] rounded p-2.5 border border-[#2A313C] text-[11px] font-mono text-[#9CA3AF] flex flex-col gap-1 mb-3">
              <div className="flex justify-between">
                <span>Est. Value:</span>
                <span className="text-[#F9FAFB]">₹{orderValue.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>
              </div>
              <div className="flex justify-between">
                <span>Brokerage Charges:</span>
                <span className="text-[#F9FAFB]">₹20.00</span>
              </div>
              {estimatedRisk !== null && (
                <div className="flex justify-between border-t border-[#2A313C] pt-1">
                  <span>Planned Risk:</span>
                  <span className="text-[#FBBF24]">₹{estimatedRisk.toFixed(2)}</span>
                </div>
              )}
            </div>

            {/* Success and Error messages */}
            {submitSuccess && (
              <div className="mb-3 p-2 rounded bg-[#064E3B] border border-[#34D399]/30 text-xs text-[#34D399] flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <span>{submitSuccess}</span>
              </div>
            )}

            {submitError && (
              <div className="mb-3 p-2 rounded bg-[#3A2E0F] border border-[#FBBF24]/40 text-xs text-[#FBBF24] flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{submitError}</span>
              </div>
            )}
          </div>

          {/* Place Order CTA */}
          <button
            type="button"
            disabled={isChecking || isSubmitting}
            onClick={() => handlePreCheckAndPlace(false)}
            className={`w-full py-2.5 rounded font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-2 transition-all ${
              side === 'BUY'
                ? 'bg-[#34D399] hover:bg-[#10B981] text-[#0E1116]'
                : 'bg-[#F87171] hover:bg-[#EF4444] text-[#0E1116]'
            } disabled:opacity-50`}
          >
            {isChecking || isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>{isChecking ? 'Checking Rules...' : 'Placing Order...'}</span>
              </>
            ) : (
              <span>Execute {side} Order</span>
            )}
          </button>
        </div>
      </div>

      {/* Pre-trade Warning Modal */}
      {showWarningModal && preCheckWarnings && (
        <div className="fixed inset-0 z-50 bg-[#0E1116]/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#1A1F29] border border-[#FBBF24]/60 rounded-xl max-w-md w-full p-5 shadow-2xl">
            <div className="flex items-center gap-2.5 text-[#FBBF24] mb-3">
              <AlertTriangle className="w-5 h-5 shrink-0" />
              <h3 className="font-bold text-sm text-[#F9FAFB]">Rule Violation Warning</h3>
            </div>

            <p className="text-xs text-[#D1D5DB] mb-3">
              The proposed order breaches your configured risk & behavioral rules:
            </p>

            <div className="flex flex-col gap-2 mb-4 max-h-48 overflow-y-auto">
              {preCheckWarnings.map((warn, i) => (
                <div
                  key={i}
                  className="bg-[#3A2E0F] border border-[#FBBF24]/30 rounded p-2 text-xs text-[#FBBF24] flex flex-col"
                >
                  <span className="font-semibold text-[11px] uppercase tracking-wider">
                    {warn.rule}
                  </span>
                  <span className="text-[#D1D5DB] text-[11px] mt-0.5">{warn.message}</span>
                </div>
              ))}
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-[#2A313C]">
              <button
                type="button"
                onClick={() => setShowWarningModal(false)}
                className="px-3 py-1.5 rounded text-xs text-[#D1D5DB] hover:text-[#F9FAFB] bg-[#0E1116] border border-[#2A313C]"
              >
                Cancel Order
              </button>
              <button
                type="button"
                onClick={() => handlePreCheckAndPlace(true)}
                className="px-3.5 py-1.5 rounded text-xs font-semibold bg-[#FBBF24] text-[#0E1116] hover:bg-[#F59E0B]"
              >
                Proceed Anyway
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
