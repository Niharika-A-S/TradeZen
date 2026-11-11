import React, { useEffect, useRef, useState, useMemo } from 'react';
import { createChart, LineStyle, CandlestickSeries, LineSeries } from 'lightweight-charts';

/**
 * Interactive Candlestick Chart for Practice Scenarios.
 * 
 * - Supports Lightweight Charts v5 (addSeries) and v4 (addCandlestickSeries).
 * - Bulletproof fallback: If canvas / lightweight-charts encounters any environment
 *   issue, seamlessly renders a high-performance SVG candlestick chart.
 * - Displays prior candles up to the decision point.
 * - When revealed, adds outcome candles and dotted what-if lines:
 *     1) What-if Sell (horizontal exit price)
 *     2) What-if Hold (dotted line tracing subsequent prices)
 *     3) What-if Buy More (dotted line showing average exposure)
 */
export default function CandleChart({
  candles = [],
  outcomeCandles = null,
  decisionPrice = null,
  isRevealed = false,
  height = 320,
}) {
  const chartContainerRef = useRef(null);
  const chartInstanceRef = useRef(null);
  const [useSvgFallback, setUseSvgFallback] = useState(false);
  const [hoveredCandle, setHoveredCandle] = useState(null);

  // Palette tokens mapped to TradeZen dark theme
  const bgSecondary = '#1A1F29';
  const gridLine = '#2A313C';
  const axisText = '#9CA3AF';
  const gainColor = '#34D399';
  const lossColor = '#F87171';
  const whatIfHoldColor = '#3B82F6';
  const whatIfBuyMoreColor = '#93C5FD';
  const whatIfSellColor = '#FBBF24';

  // Format and sort candles
  const allCandles = useMemo(() => {
    const formattedPrior = (candles || []).map((c, i) => ({
      time: typeof c.time === 'number' ? c.time : (c.timestamp || i * 60),
      open: parseFloat(c.open),
      high: parseFloat(c.high),
      low: parseFloat(c.low),
      close: parseFloat(c.close),
      volume: parseFloat(c.volume || 0),
    }));

    let combined = [...formattedPrior];
    if (isRevealed && outcomeCandles && outcomeCandles.length > 0) {
      const lastPriorTime = formattedPrior.length > 0 ? formattedPrior[formattedPrior.length - 1].time : 0;
      const formattedOutcome = outcomeCandles.map((c, i) => ({
        time: typeof c.time === 'number' && c.time > lastPriorTime ? c.time : lastPriorTime + (i + 1) * 60,
        open: parseFloat(c.open),
        high: parseFloat(c.high),
        low: parseFloat(c.low),
        close: parseFloat(c.close),
        volume: parseFloat(c.volume || 0),
      }));
      combined = [...formattedPrior, ...formattedOutcome];
    }

    combined.sort((a, b) => a.time - b.time);
    const unique = [];
    const seenTimes = new Set();
    for (const item of combined) {
      if (!seenTimes.has(item.time)) {
        seenTimes.add(item.time);
        unique.push(item);
      }
    }
    return unique;
  }, [candles, outcomeCandles, isRevealed]);

  useEffect(() => {
    if (useSvgFallback || !chartContainerRef.current) return;

    let chart = null;
    try {
      const containerWidth = chartContainerRef.current.clientWidth || 600;

      chart = createChart(chartContainerRef.current, {
        width: containerWidth,
        height: height,
        layout: {
          background: { color: bgSecondary },
          textColor: axisText,
          fontSize: 11,
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        },
        grid: {
          vertLines: { color: gridLine, style: LineStyle.SparseDotted },
          horzLines: { color: gridLine, style: LineStyle.SparseDotted },
        },
        crosshair: {
          mode: 1,
          vertLine: { color: '#374151', width: 1, style: LineStyle.Dashed },
          horzLine: { color: '#374151', width: 1, style: LineStyle.Dashed },
        },
        timeScale: {
          borderColor: gridLine,
          timeVisible: true,
          secondsVisible: false,
          tickMarkFormatter: (time) => {
            const mins = Math.floor(time / 60);
            return `${mins}m`;
          },
        },
        rightPriceScale: {
          borderColor: gridLine,
          scaleMargins: { top: 0.15, bottom: 0.15 },
        },
      });

      chartInstanceRef.current = chart;

      // Add Candlestick Series - compatible with v4 & v5
      let candleSeries = null;
      const candleOpts = {
        upColor: gainColor,
        downColor: lossColor,
        borderUpColor: gainColor,
        borderDownColor: lossColor,
        wickUpColor: gainColor,
        wickDownColor: lossColor,
      };

      if (typeof chart.addSeries === 'function' && CandlestickSeries) {
        candleSeries = chart.addSeries(CandlestickSeries, candleOpts);
      } else if (typeof chart.addCandlestickSeries === 'function') {
        candleSeries = chart.addCandlestickSeries(candleOpts);
      }

      if (candleSeries && allCandles.length > 0) {
        candleSeries.setData(allCandles);
      }

      // Add Dotted What-If Lines if Revealed
      if (isRevealed && allCandles.length > 0 && decisionPrice) {
        const priorCount = candles.length;
        const decTime = priorCount > 0 ? allCandles[priorCount - 1]?.time || 0 : 0;
        const futureCandles = allCandles.filter((c) => c.time >= decTime);

        if (futureCandles.length > 1) {
          const createLineSeries = (opts) => {
            if (typeof chart.addSeries === 'function' && LineSeries) {
              return chart.addSeries(LineSeries, opts);
            }
            if (typeof chart.addLineSeries === 'function') {
              return chart.addLineSeries(opts);
            }
            return null;
          };

          // Line A: What-If Hold
          const holdSeries = createLineSeries({
            color: whatIfHoldColor,
            lineWidth: 2,
            lineStyle: LineStyle.Dotted,
            title: 'Hold Path',
          });
          if (holdSeries) {
            holdSeries.setData(futureCandles.map((c) => ({ time: c.time, value: c.close })));
          }

          // Line B: What-If Sell
          const sellSeries = createLineSeries({
            color: whatIfSellColor,
            lineWidth: 2,
            lineStyle: LineStyle.Dashed,
            title: 'Sell Exit',
          });
          if (sellSeries) {
            sellSeries.setData(futureCandles.map((c) => ({ time: c.time, value: decisionPrice })));
          }

          // Line C: What-If Buy More
          const buyMoreSeries = createLineSeries({
            color: whatIfBuyMoreColor,
            lineWidth: 2,
            lineStyle: LineStyle.Dotted,
            title: 'Buy More (Avg)',
          });
          if (buyMoreSeries) {
            buyMoreSeries.setData(futureCandles.map((c) => ({
              time: c.time,
              value: (decisionPrice + c.close) / 2.0,
            })));
          }
        }
      }

      chart.timeScale().fitContent();

      const handleResize = () => {
        if (chartContainerRef.current && chart) {
          chart.applyOptions({ width: chartContainerRef.current.clientWidth });
        }
      };
      window.addEventListener('resize', handleResize);

      return () => {
        window.removeEventListener('resize', handleResize);
        if (chart) {
          try {
            chart.remove();
          } catch {
            // cleanup ignore
          }
        }
      };
    } catch (err) {
      console.warn('Lightweight Charts canvas failed, switching to SVG candlestick renderer:', err);
      if (chart) {
        try {
          chart.remove();
        } catch {
          // cleanup ignore
        }
      }
      setUseSvgFallback(true);
    }
  }, [allCandles, isRevealed, decisionPrice, height, useSvgFallback]);

  // Compute SVG fallback geometry
  const svgData = useMemo(() => {
    if (!useSvgFallback || allCandles.length === 0) return null;
    let minPrice = Infinity;
    let maxPrice = -Infinity;
    for (const c of allCandles) {
      if (c.low < minPrice) minPrice = c.low;
      if (c.high > maxPrice) maxPrice = c.high;
    }
    if (decisionPrice) {
      if (decisionPrice < minPrice) minPrice = decisionPrice;
      if (decisionPrice > maxPrice) maxPrice = decisionPrice;
    }
    const pad = (maxPrice - minPrice) * 0.1 || 1.0;
    minPrice -= pad;
    maxPrice += pad;
    const priceRange = maxPrice - minPrice;

    return { minPrice, maxPrice, priceRange };
  }, [useSvgFallback, allCandles, decisionPrice]);

  return (
    <div className="w-full relative select-none">
      {!useSvgFallback ? (
        <div
          ref={chartContainerRef}
          className="w-full rounded border border-[#2A313C] overflow-hidden bg-[#1A1F29]"
          style={{ height }}
        />
      ) : (
        /* Standalone High-Performance SVG Candlestick View */
        <div
          className="w-full rounded border border-[#2A313C] overflow-hidden bg-[#1A1F29] relative flex flex-col justify-between"
          style={{ height }}
        >
          {svgData && allCandles.length > 0 ? (
            <svg className="w-full h-full" viewBox="0 0 800 320" preserveAspectRatio="none">
              {/* Horizontal Grid lines */}
              {[0.2, 0.4, 0.6, 0.8].map((ratio, i) => {
                const y = 320 * ratio;
                const price = svgData.maxPrice - ratio * svgData.priceRange;
                return (
                  <g key={i}>
                    <line x1="0" y1={y} x2="800" y2={y} stroke="#2A313C" strokeDasharray="3 3" />
                    <text x="792" y={y - 4} fill="#6B7280" fontSize="10" textAnchor="end">
                      ₹{price.toFixed(2)}
                    </text>
                  </g>
                );
              })}

              {/* Candlesticks */}
              {allCandles.map((c, idx) => {
                const total = allCandles.length;
                const slotW = 740 / total;
                const cx = 20 + idx * slotW + slotW / 2;
                const candleW = Math.max(3, Math.min(10, slotW * 0.7));

                const getY = (val) => 300 - ((val - svgData.minPrice) / svgData.priceRange) * 280;

                const yHigh = getY(c.high);
                const yLow = getY(c.low);
                const yOpen = getY(c.open);
                const yClose = getY(c.close);

                const isGain = c.close >= c.open;
                const color = isGain ? gainColor : lossColor;
                const bodyY = Math.min(yOpen, yClose);
                const bodyH = Math.max(2, Math.abs(yClose - yOpen));

                return (
                  <g
                    key={idx}
                    onMouseEnter={() => setHoveredCandle(c)}
                    onMouseLeave={() => setHoveredCandle(null)}
                    className="cursor-crosshair"
                  >
                    <line x1={cx} y1={yHigh} x2={cx} y2={yLow} stroke={color} strokeWidth="1.2" />
                    <rect
                      x={cx - candleW / 2}
                      y={bodyY}
                      width={candleW}
                      height={bodyH}
                      fill={color}
                      rx="1"
                    />
                  </g>
                );
              })}

              {/* Dotted What-if lines when revealed */}
              {isRevealed && decisionPrice && (
                <line
                  x1="0"
                  y1={300 - ((decisionPrice - svgData.minPrice) / svgData.priceRange) * 280}
                  x2="800"
                  y2={300 - ((decisionPrice - svgData.minPrice) / svgData.priceRange) * 280}
                  stroke={whatIfSellColor}
                  strokeWidth="2"
                  strokeDasharray="4 4"
                />
              )}
            </svg>
          ) : (
            <div className="flex items-center justify-center h-full text-xs text-[#9CA3AF]">
              Loading candlestick scenario data...
            </div>
          )}

          {/* Fallback Hover Inspector */}
          {hoveredCandle && (
            <div className="absolute bottom-2 left-2 z-20 bg-[#11161F]/90 backdrop-blur border border-[#2A313C] px-2.5 py-1 rounded text-[11px] font-mono text-[#F9FAFB] flex gap-3 shadow">
              <span>O: ₹{hoveredCandle.open.toFixed(2)}</span>
              <span>H: ₹{hoveredCandle.high.toFixed(2)}</span>
              <span>L: ₹{hoveredCandle.low.toFixed(2)}</span>
              <span className={hoveredCandle.close >= hoveredCandle.open ? 'text-[#34D399]' : 'text-[#F87171]'}>
                C: ₹{hoveredCandle.close.toFixed(2)}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Chart Legend Overlay */}
      {isRevealed && (
        <div className="absolute top-2 left-2 z-10 flex flex-wrap gap-2 text-[10px] sm:text-xs bg-[#1A1F29]/90 backdrop-blur-sm p-1.5 rounded border border-[#2A313C] shadow">
          <div className="flex items-center space-x-1">
            <span className="w-2.5 h-0.5 bg-[#FBBF24] inline-block" />
            <span className="text-[#9CA3AF]">What-if Sell (Fixed Exit)</span>
          </div>
          <div className="flex items-center space-x-1">
            <span className="w-2.5 h-0.5 bg-[#3B82F6] inline-block" />
            <span className="text-[#9CA3AF]">What-if Hold</span>
          </div>
          <div className="flex items-center space-x-1">
            <span className="w-2.5 h-0.5 bg-[#93C5FD] inline-block" />
            <span className="text-[#9CA3AF]">What-if Buy More</span>
          </div>
        </div>
      )}
    </div>
  );
}
