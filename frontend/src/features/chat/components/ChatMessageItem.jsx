import React from 'react';
import { ExternalLink } from 'lucide-react';
import { renderFormattedMessage } from './MessageRenderer';

export default function ChatMessageItem({ message }) {
  const isUser = message.role === 'user';
  const isNudge = Boolean(message.isNudge);

  const formattedTime = (() => {
    if (!message.created_at) return '';
    try {
      let iso = typeof message.created_at === 'string' ? message.created_at.trim() : message.created_at;
      if (typeof iso === 'string') {
        iso = iso.replace(' ', 'T');
        if (!iso.endsWith('Z') && !/[+-]\d{2}(:\d{2})?$/.test(iso)) {
          iso += 'Z';
        }
      }
      const d = new Date(iso);
      if (isNaN(d.getTime())) return '';
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '';
    }
  })();

  return (
    <div
      className={`flex flex-col mb-3 ${isUser ? 'items-end' : 'items-start'} ${
        isNudge ? 'pl-2 border-l-4 border-[#FBBF24] bg-[#3A2E0F]/20 rounded-r-lg p-2' : ''
      }`}
    >
      <div
        className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm transition-colors ${
          isUser
            ? 'bg-[#2563EB] text-white hover:bg-[#1D4ED8] rounded-br-none'
            : 'bg-[#11161F] text-[#F9FAFB] border border-[#2A313C] rounded-bl-none'
        }`}
      >
        {renderFormattedMessage(message.content)}
      </div>

      {/* Meta tags for bot replies */}
      {!isUser && (
        <div className="flex flex-wrap items-center gap-2 mt-1 px-1 text-xs text-[#9CA3AF]">
          {/* Source Chips — de-duplicated by id */}
          {message.sources && message.sources.length > 0 && (() => {
            const seen = new Set();
            const unique = message.sources.filter(src => {
              const key = src.id ?? src.title;
              if (seen.has(key)) return false;
              seen.add(key);
              return true;
            });
            return unique.length > 0 ? (
              <div className="flex flex-wrap items-center gap-1.5 mt-0.5">
                <span className="text-[11px] text-[#9CA3AF]">Sources:</span>
                {unique.map((src) => {
                  const hasUrl = src.source_url && (src.source_url.startsWith('http://') || src.source_url.startsWith('https://'));
                  return hasUrl ? (
                    <a
                      key={src.id ?? src.title}
                      href={src.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-[#2A313C] bg-[#1A1F29] text-[#3B82F6] hover:text-[#60A5FA] text-[11px]"
                    >
                      <span>{src.title}</span>
                      <ExternalLink className="w-2.5 h-2.5" />
                    </a>
                  ) : (
                    <span
                      key={src.id ?? src.title}
                      className="px-2 py-0.5 rounded border border-[#2A313C] bg-[#1A1F29] text-[#D1D5DB] text-[11px]"
                    >
                      {src.title}
                    </span>
                  );
                })}
              </div>
            ) : null;
          })()}

          {/* Debug line — only when localStorage tz_chat_debug === '1' */}
          {(() => {
            try {
              if (localStorage.getItem('tz_chat_debug') === '1') {
                const parts = [message.generated_by, message.degraded_reason].filter(Boolean).join(' ');
                return parts ? (
                  <span className="text-[10px] text-[#6B7280] mt-0.5 px-1">
                    {`debug: ${parts}`}
                  </span>
                ) : null;
              }
            } catch (e) {}
            return null;
          })()}

          {formattedTime && <span className="ml-auto text-[10px] text-[#9CA3AF]">{formattedTime}</span>}
        </div>
      )}

      {isUser && formattedTime && (
        <span className="text-[10px] text-[#9CA3AF] mt-0.5 px-1">{formattedTime}</span>
      )}
    </div>
  );
}
