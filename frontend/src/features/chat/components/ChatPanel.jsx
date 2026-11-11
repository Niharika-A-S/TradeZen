import React, { useState, useEffect, useRef } from 'react';
import {
  MessageSquare,
  X,
  Trash2,
  BookmarkPlus,
  AlertTriangle,
  RotateCcw,
  Check,
  ShieldAlert,
  Loader2,
} from 'lucide-react';
import { useChat } from '../useChat';
import ChatMessageItem from './ChatMessageItem';
import ChatComposer from './ChatComposer';

const SUGGESTIONS = [
  'Explain my last session',
  'Why am I losing?',
  'What is a stop-loss?',
  'Show my rules',
];

export default function ChatPanel({ isOpen, onClose }) {
  const {
    messages,
    isLoading,
    errorBanner,
    rateLimitTimeLeft,
    sendMessage,
    clearHistory,
    saveNote,
    retryLastMessage,
  } = useChat();

  const [showPrivacyNotice, setShowPrivacyNotice] = useState(false);
  const [showNoteInput, setShowNoteInput] = useState(false);
  const [noteText, setNoteText] = useState('');
  const [noteSuccess, setNoteSuccess] = useState(false);

  const messagesEndRef = useRef(null);
  const panelRef = useRef(null);

  // Check privacy notice in localStorage
  useEffect(() => {
    try {
      const dismissed = localStorage.getItem('tradezen_chat_privacy_dismissed');
      if (!dismissed) {
        setShowPrivacyNotice(true);
      }
    } catch {
      // ignore localStorage block
    }
  }, []);

  const handleDismissPrivacy = () => {
    setShowPrivacyNotice(false);
    try {
      localStorage.setItem('tradezen_chat_privacy_dismissed', 'true');
    } catch {
      // ignore
    }
  };

  // Auto-scroll on new messages
  useEffect(() => {
    if (isOpen) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isLoading, isOpen]);

  // Keyboard accessibility: Escape to close & focus trapping
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  const handleClearChat = () => {
    if (window.confirm('Are you sure you want to clear your chat history?')) {
      clearHistory();
    }
  };

  const handleSaveNoteSubmit = async (e) => {
    e.preventDefault();
    if (!noteText.trim()) return;
    const ok = await saveNote(noteText.trim());
    if (ok) {
      setNoteSuccess(true);
      setNoteText('');
      setTimeout(() => {
        setNoteSuccess(false);
        setShowNoteInput(false);
      }, 1500);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="TradeZen Coach Chat"
      ref={panelRef}
      className="fixed inset-y-0 right-0 z-50 w-full sm:w-[420px] md:w-[460px] bg-[#1A1F29] border-l border-[#2A313C] shadow-2xl flex flex-col transition-all duration-200"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#2A313C] bg-[#0E1116]/80 backdrop-blur-sm">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-[#2563EB]/20 border border-[#2563EB]/40 flex items-center justify-center text-[#3B82F6]">
            <MessageSquare className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-[#F9FAFB]">TradeZen Coach</h2>
            <p className="text-[11px] text-[#9CA3AF]">AI Trading Discipline Assistant</p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setShowNoteInput(!showNoteInput)}
            title="Save a note"
            aria-label="Save a reflection note"
            className="p-1.5 rounded-lg text-[#9CA3AF] hover:text-[#F9FAFB] hover:bg-[#11161F] transition-colors focus:outline-none focus:ring-1 focus:ring-[#3B82F6]"
          >
            <BookmarkPlus className="w-4 h-4" />
          </button>

          <button
            onClick={handleClearChat}
            title="Clear Chat History"
            aria-label="Clear chat history"
            className="p-1.5 rounded-lg text-[#9CA3AF] hover:text-[#F87171] hover:bg-[#11161F] transition-colors focus:outline-none focus:ring-1 focus:ring-[#3B82F6]"
          >
            <Trash2 className="w-4 h-4" />
          </button>

          <button
            onClick={onClose}
            aria-label="Close Chat Panel"
            className="p-1.5 rounded-lg text-[#9CA3AF] hover:text-[#F9FAFB] hover:bg-[#11161F] transition-colors focus:outline-none focus:ring-1 focus:ring-[#3B82F6]"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Note input bar */}
      {showNoteInput && (
        <form
          onSubmit={handleSaveNoteSubmit}
          className="flex items-center gap-2 px-3 py-2 border-b border-[#2A313C] bg-[#11161F]"
        >
          <input
            type="text"
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            placeholder="Save a quick reflection (e.g. 'Paused after 2 losses')..."
            className="flex-1 bg-[#1A1F29] border border-[#2A313C] rounded-md px-2.5 py-1 text-xs text-[#F9FAFB] placeholder-[#9CA3AF] outline-none focus:border-[#3B82F6]"
          />
          <button
            type="submit"
            disabled={!noteText.trim()}
            className="px-2.5 py-1 rounded bg-[#2563EB] text-white text-xs font-medium hover:bg-[#1D4ED8] disabled:opacity-40"
          >
            {noteSuccess ? <Check className="w-3.5 h-3.5 text-[#34D399]" /> : 'Save'}
          </button>
        </form>
      )}

      {/* Dismissible Privacy Notice */}
      {showPrivacyNotice && (
        <div className="flex items-start justify-between gap-2 px-3.5 py-2.5 border-b border-[#2A313C] bg-[#1E3A5F]/40 text-xs text-[#D1D5DB]">
          <span>Replies are written with Google Gemini. Please do not share personal details.</span>
          <button
            onClick={handleDismissPrivacy}
            className="text-[#9CA3AF] hover:text-[#F9FAFB] p-0.5"
            aria-label="Dismiss notice"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Error / Rate limit banner */}
      {errorBanner && (
        <div className="flex items-center justify-between gap-2 px-3.5 py-2 border-b border-[#FBBF24]/30 bg-[#3A2E0F] text-xs text-[#FBBF24]">
          <div className="flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
            <span>{errorBanner.message}</span>
          </div>
          {!errorBanner.isRateLimit && (
            <button
              onClick={retryLastMessage}
              className="flex items-center gap-1 font-semibold text-[#FBBF24] underline hover:opacity-80"
            >
              <RotateCcw className="w-3 h-3" />
              Retry
            </button>
          )}
        </div>
      )}

      {/* Message List */}
      <div
        className="flex-1 overflow-y-auto p-4 space-y-1"
        aria-live="polite"
        role="log"
      >
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-4">
            <div className="w-12 h-12 rounded-2xl bg-[#11161F] border border-[#2A313C] flex items-center justify-center text-[#3B82F6] mb-3">
              <MessageSquare className="w-6 h-6" />
            </div>
            <h3 className="text-sm font-semibold text-[#F9FAFB] mb-1">Welcome to TradeZen Coach</h3>
            <p className="text-xs text-[#9CA3AF] max-w-xs mb-6">
              Ask questions about trading terminology, review your discipline limits, or analyze recent session results.
            </p>

            <div className="w-full flex flex-col gap-2">
              <span className="text-[11px] font-medium text-[#9CA3AF] self-start">Quick Questions</span>
              {SUGGESTIONS.map((chip, idx) => (
                <button
                  key={`chip-${idx}`}
                  onClick={() => sendMessage(chip)}
                  disabled={isLoading || rateLimitTimeLeft > 0}
                  className="text-left px-3 py-2 rounded-lg bg-[#1E3A5F]/60 border border-[#2A313C] hover:border-[#3B82F6] text-xs font-medium text-[#3B82F6] hover:bg-[#1E3A5F] transition-all"
                >
                  {chip}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg, index) => (
              <ChatMessageItem key={`msg-${index}-${msg.created_at || index}`} message={msg} />
            ))}

            {isLoading && (
              <div className="flex items-center gap-2 text-xs text-[#9CA3AF] py-2 px-1">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-[#3B82F6]" />
                <span>Coach is thinking...</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Composer */}
      <ChatComposer
        onSend={sendMessage}
        disabled={isLoading || rateLimitTimeLeft > 0}
      />
    </div>
  );
}
