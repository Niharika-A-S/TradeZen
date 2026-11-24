import React, { useState } from 'react';
import coachIcon from './assets/coach-icon.jpg';
import ChatPanel from './components/ChatPanel';
import { useChat } from './useChat';

export default function ChatFeature() {
  const [isOpen, setIsOpen] = useState(false);
  const { unreadNudgesCount, resetUnreadNudges } = useChat();

  const handleToggle = () => {
    if (!isOpen) {
      resetUnreadNudges();
    }
    setIsOpen(!isOpen);
  };

  return (
    <>
      {/* Floating Button (Bottom Right) */}
      <button
        onClick={handleToggle}
        aria-label="Open TradeZen Coach"
        className="fixed bottom-6 right-6 z-40 w-14 h-14 rounded-full bg-[#0D1117] border-2 border-amber-500/60 text-white shadow-[0_4px_20px_rgba(245,158,11,0.25)] hover:shadow-[0_4px_25px_rgba(245,158,11,0.45)] hover:scale-105 active:scale-95 transition-all duration-150 focus:outline-none focus:ring-4 focus:ring-amber-500/40 flex items-center justify-center overflow-hidden p-0"
      >
        <img
          src={coachIcon}
          alt="TradeZen Coach"
          className="w-full h-full object-cover object-center"
        />

        {/* Unread Nudge Badge */}
        {unreadNudgesCount > 0 && !isOpen && (
          <span className="absolute -top-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full bg-[#EF4444] text-[10px] font-bold text-white shadow-md animate-pulse z-10">
            {unreadNudgesCount > 9 ? '9+' : unreadNudgesCount}
          </span>
        )}
      </button>

      {/* Drawer / Sheet Panel */}
      <ChatPanel isOpen={isOpen} onClose={() => setIsOpen(false)} />
    </>
  );
}
