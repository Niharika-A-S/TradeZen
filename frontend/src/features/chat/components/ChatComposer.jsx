import React, { useState, useRef, useEffect } from 'react';
import { Send } from 'lucide-react';

export default function ChatComposer({ onSend, disabled, maxLength = 1000 }) {
  const [text, setText] = useState('');
  const textareaRef = useRef(null);

  // Auto-grow textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`;
    }
  }, [text]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSubmit = () => {
    if (disabled || !text.trim()) return;
    onSend(text.trim());
    setText('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const charCount = text.length;
  const isOverLimit = charCount > maxLength;

  return (
    <div className="p-3 border-t border-[#2A313C] bg-[#1A1F29]">
      <div className="relative flex items-end gap-2 bg-[#0E1116] border border-[#2A313C] focus-within:border-[#374151] focus-within:ring-1 focus-within:ring-[#3B82F6] rounded-xl p-2 transition-all">
        <textarea
          ref={textareaRef}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder="Ask Coach about trading rules, concepts, or recent P&L..."
          className="flex-1 bg-transparent text-[#F9FAFB] placeholder-[#9CA3AF] text-sm resize-none outline-none max-h-28 pr-16 disabled:opacity-50"
          aria-label="Message coach"
        />

        <div className="absolute right-2 bottom-2 flex items-center gap-2">
          <span
            className={`text-[11px] ${
              isOverLimit ? 'text-[#F87171] font-semibold' : 'text-[#9CA3AF]'
            }`}
          >
            {charCount}/{maxLength}
          </span>

          <button
            onClick={handleSubmit}
            disabled={disabled || !text.trim() || isOverLimit}
            aria-label="Send message"
            className="p-1.5 rounded-lg bg-[#2563EB] text-white hover:bg-[#1D4ED8] disabled:opacity-40 disabled:hover:bg-[#2563EB] transition-colors focus:outline-none focus:ring-2 focus:ring-[#3B82F6]"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
