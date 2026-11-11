import React from 'react';

/**
 * Parses assistant text and renders:
 * - Gain amounts (e.g. +₹500, +₹1,800) in gain color (#34D399)
 * - Loss amounts (e.g. -₹1,800, -₹900) in loss color (#F87171)
 * - Bold text (**text**)
 * - Bullet list items
 * - Newlines
 * NEVER uses dangerouslySetInnerHTML.
 */
export function renderFormattedMessage(text) {
  if (!text) return null;

  // Split into lines first
  const lines = text.split('\n');

  return lines.map((line, lineIdx) => {
    const isBullet = line.trim().startsWith('• ') || line.trim().startsWith('- ');
    const cleanedLine = isBullet ? line.trim().substring(2) : line;

    // Parse spans for pnl numbers and bold markup
    // P&L pattern matches +₹500, -₹1,800, +500, -1800, etc.
    const pnlPattern = /([+-]₹?\d+(?:,\d+)*(?:\.\d+)?)/g;
    const parts = [];
    let lastIndex = 0;
    let match;

    while ((match = pnlPattern.exec(cleanedLine)) !== null) {
      if (match.index > lastIndex) {
        parts.push(cleanedLine.substring(lastIndex, match.index));
      }
      const val = match[1];
      const isPositive = val.startsWith('+');
      parts.push(
        <span
          key={`pnl-${lineIdx}-${match.index}`}
          className={`font-semibold ${isPositive ? 'text-[#34D399]' : 'text-[#F87171]'}`}
        >
          {val}
        </span>
      );
      lastIndex = match.index + val.length;
    }
    if (lastIndex < cleanedLine.length) {
      parts.push(cleanedLine.substring(lastIndex));
    }

    // Now process parts for bold formatting (**bold**)
    const renderedSpans = parts.map((part, partIdx) => {
      if (typeof part !== 'string') return part;

      const boldParts = part.split(/(\*\*[^*]+\*\*)/g);
      return boldParts.map((bPart, bIdx) => {
        if (bPart.startsWith('**') && bPart.endsWith('**')) {
          return (
            <strong key={`b-${lineIdx}-${partIdx}-${bIdx}`} className="font-semibold text-[#F9FAFB]">
              {bPart.slice(2, -2)}
            </strong>
          );
        }
        return bPart;
      });
    });

    if (isBullet) {
      return (
        <div key={`line-${lineIdx}`} className="flex items-start gap-2 my-1">
          <span className="text-[#3B82F6] select-none">•</span>
          <span className="flex-1">{renderedSpans}</span>
        </div>
      );
    }

    return (
      <p key={`line-${lineIdx}`} className={lineIdx > 0 ? 'mt-1.5' : ''}>
        {renderedSpans.length > 0 ? renderedSpans : <br />}
      </p>
    );
  });
}
