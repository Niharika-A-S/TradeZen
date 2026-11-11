import React, { useMemo, useState } from 'react';

/**
 * High-performance SVG Candlestick Chart for 1-minute price bars.
 * Strictly adheres to TradeZen Dark Theme specifications:
 * - Gain Candle: #34D399
 * - Loss Candle: #F87171
 * - Grid: #2A313C
 * - Axis text: #9CA3AF
 * - Accent: #3B82F6
 */
export default function CandlestickChart({ bars = [], symbol = 'INFY', currentPrice = null }) {
  const [hoveredBar, setHoveredBar] = useState(null);

  // Filter or take most recent bars if many
  const visibleBars = useMemo(() => {
    if (!bars || bars.length === 0) return [];
    // Show up to the last 90 bars for crisp intraday view
    return bars.slice(-90);
  }, [bars]);

  // Compute price bounds
  const { minPrice, maxPrice, priceRange } = useMemo(() => {
    if (visibleBars.length === 0) {
      return { minPrice: 1000, maxPrice: 1100, priceRange: 100 };
    }
    let min = Infinity;
    let max = -Infinity;
    for (const b of visibleBars) {
      if (b.low < min) min = b.low;
      if (b.high > max) max = b.high;
    }
    const padding = (max - min) * 0.08 || 1.0;
    return {
      minPrice: min - padding,
      maxPrice: max + padding,
      priceRange: (max + padding) - (min - padding),
    };
  }, [visibleBars]);

  // Chart dimensions
  const width = 800;
  const height = 340;
  const margin = { top: 20, right: 65, bottom: 30, left: 15 };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;

  const barCount = visibleBars.length;
  const candleSlotWidth = barCount > 0 ? chartWidth / barCount : 10;
  const candleBodyWidth = Math.max(2, Math.min(8, candleSlotWidth * 0.7));

  // Scale functions
  const getY = (val) => {
    if (priceRange === 0) return chartHeight / 2;
    return margin.top + chartHeight - ((val - minPrice) / priceRange) * chartHeight;
  };

  const getX = (idx) => {
    return margin.left + idx * candleSlotWidth + candleSlotWidth / 2;
  };

  // Generate 5 horizontal price grid lines
  const gridTicks = useMemo(() => {
    const ticks = [];
    const count = 5;
    for (let i = 0; i < count; i++) {
      const val = minPrice + (priceRange / (count - 1)) * i;
      ticks.push(val);
    }
    return ticks;
  }, [minPrice, priceRange]);

  if (visibleBars.length === 0) {
    return (
      <div className="h-[340px] w-full flex flex-col items-center justify-center bg-[#1A1F29] rounded-lg border border-[#2A313C] text-[#9CA3AF]">
        <div className="animate-spin w-6 h-6 border-2 border-[#3B82F6] border-t-transparent rounded-full mb-3" />
        <span className="text-xs">Loading market candles for {symbol}...</span>
      </div>
    );
  }

  const activeBar = hoveredBar || visibleBars[visibleBars.length - 1];

  return (
    <div className="bg-[#1A1F29] border border-[#2A313C] rounded-lg p-3 flex flex-col relative select-none">
      {/* Chart Top Info Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2 pb-2 border-b border-[#2A313C] text-xs">
        <div className="flex items-center gap-3">
          <span className="font-bold text-[#F9FAFB] text-sm tracking-wide">{symbol}</span>
          <span className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-[#0E1116] border border-[#2A313C] text-[#9CA3AF]">
            1m Bars
          </span>
          {activeBar && (
            <div className="flex items-center gap-3 font-mono text-[11px]">
              <span className="text-[#9CA3AF]">O: <span className="text-[#F9FAFB]">{activeBar.open.toFixed(2)}</span></span>
              <span className="text-[#9CA3AF]">H: <span className="text-[#F9FAFB]">{activeBar.high.toFixed(2)}</span></span>
              <span className="text-[#9CA3AF]">L: <span className="text-[#F9FAFB]">{activeBar.low.toFixed(2)}</span></span>
              <span className="text-[#9CA3AF]">C: <span className={activeBar.close >= activeBar.open ? 'text-[#34D399]' : 'text-[#F87171]'}>{activeBar.close.toFixed(2)}</span></span>
            </div>
          )}
        </div>

        {activeBar && (
          <div className="text-[11px] font-mono text-[#9CA3AF]">
            {activeBar.timestamp.split(' ')[1] || activeBar.timestamp}
          </div>
        )}
      </div>

      {/* SVG Canvas */}
      <div className="relative w-full overflow-hidden">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full h-[320px] overflow-visible"
          onMouseLeave={() => setHoveredBar(null)}
        >
          {/* Horizontal Grid lines and Price Axis */}
          {gridTicks.map((price, i) => {
            const y = getY(price);
            return (
              <g key={`grid-${i}`}>
                <line
                  x1={margin.left}
                  y1={y}
                  x2={width - margin.right}
                  y2={y}
                  stroke="#2A313C"
                  strokeWidth="1"
                  strokeDasharray="3 3"
                />
                <text
                  x={width - margin.right + 8}
                  y={y + 3}
                  fill="#9CA3AF"
                  fontSize="10"
                  fontFamily="JetBrains Mono, monospace"
                  textAnchor="start"
                >
                  ₹{price.toFixed(2)}
                </text>
              </g>
            );
          })}

          {/* Candlesticks */}
          {visibleBars.map((bar, idx) => {
            const isBullish = bar.close >= bar.open;
            const color = isBullish ? '#34D399' : '#F87171';
            const cx = getX(idx);

            const yHigh = getY(bar.high);
            const yLow = getY(bar.low);
            const yOpen = getY(bar.open);
            const yClose = getY(bar.close);

            const bodyTop = Math.min(yOpen, yClose);
            const bodyHeight = Math.max(1.5, Math.abs(yOpen - yClose));

            return (
              <g
                key={`candle-${idx}`}
                className="cursor-crosshair group"
                onMouseEnter={() => setHoveredBar(bar)}
              >
                {/* Hit area */}
                <rect
                  x={cx - candleSlotWidth / 2}
                  y={margin.top}
                  width={candleSlotWidth}
                  height={chartHeight}
                  fill="transparent"
                />

                {/* Upper and lower wick */}
                <line
                  x1={cx}
                  y1={yHigh}
                  x2={cx}
                  y2={yLow}
                  stroke={color}
                  strokeWidth="1.2"
                />

                {/* Candle body */}
                <rect
                  x={cx - candleBodyWidth / 2}
                  y={bodyTop}
                  width={candleBodyWidth}
                  height={bodyHeight}
                  fill={color}
                  rx="0.5"
                />
              </g>
            );
          })}

          {/* Current Market Price horizontal line */}
          {currentPrice && (
            <g>
              <line
                x1={margin.left}
                y1={getY(currentPrice)}
                x2={width - margin.right}
                y2={getY(currentPrice)}
                stroke="#3B82F6"
                strokeWidth="1.2"
                strokeDasharray="4 2"
              />
              <rect
                x={width - margin.right + 2}
                y={getY(currentPrice) - 8}
                width={56}
                height={16}
                fill="#1E3A5F"
                stroke="#3B82F6"
                strokeWidth="0.8"
                rx="2"
              />
              <text
                x={width - margin.right + 5}
                y={getY(currentPrice) + 4}
                fill="#F9FAFB"
                fontSize="9.5"
                fontFamily="JetBrains Mono, monospace"
                fontWeight="600"
              >
                ₹{currentPrice.toFixed(2)}
              </text>
            </g>
          )}

          {/* Time axis ticks (every ~10 bars) */}
          {visibleBars.map((bar, idx) => {
            if (idx % Math.max(1, Math.floor(visibleBars.length / 6)) !== 0) return null;
            const x = getX(idx);
            const timeStr = bar.timestamp.split(' ')[1] || bar.timestamp;
            return (
              <text
                key={`time-${idx}`}
                x={x}
                y={height - margin.bottom + 18}
                fill="#9CA3AF"
                fontSize="9.5"
                fontFamily="JetBrains Mono, monospace"
                textAnchor="middle"
              >
                {timeStr.slice(0, 5)}
              </text>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
