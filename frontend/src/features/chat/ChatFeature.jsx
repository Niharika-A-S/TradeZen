import React, { useState } from 'react';
import { MessageSquare } from 'lucide-react';
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
        className="fixed bottom-6 right-6 z-40 p-3.5 rounded-full bg-[#2563EB] text-white shadow-xl hover:bg-[#1D4ED8] hover:scale-105 active:scale-95 transition-all duration-150 focus:outline-none focus:ring-4 focus:ring-[#3B82F6]/50 flex items-center justify-center"
      >
        <MessageSquare className="w-5 h-5" />

        {/* Unread Nudge Badge */}
        {unreadNudgesCount > 0 && !isOpen && (
          <span className="absolute -top-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full bg-[#EF4444] text-[10px] font-bold text-white shadow-md animate-pulse">
            {unreadNudgesCount > 9 ? '9+' : unreadNudgesCount}
          </span>
        )}
      </button>

      {/* Drawer / Sheet Panel */}
      <ChatPanel isOpen={isOpen} onClose={() => setIsOpen(false)} />
    </>
  );
}
