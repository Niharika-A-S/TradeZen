import React, { useState } from 'react';
import {
  Clock,
  Play,
  FastForward,
  ShieldAlert,
  Sliders,
  Brain,
  Wifi,
  WifiOff,
  AlertTriangle,
  RotateCcw,
  User,
  LogOut
} from 'lucide-react';

export default function Header({
  clockStatus,
  wsStatus,
  onTickClock,
  onSwitchDate,
  onOpenRules,
  onRunAiPrediction,
  isLoadingClock,
  currentUser,
  onOpenAuth,
  onLogout,
  onSwitchMode,
  activeMainTab = 'paper',
  onSelectMainTab,
}) {
  const [selectedDate, setSelectedDate] = useState('2022-03-10');
  const [isAdvancing, setIsAdvancing] = useState(false);

  const handleTick = async (minutes) => {
    setIsAdvancing(true);
    try {
      await onTickClock(minutes);
    } finally {
      setIsAdvancing(false);
    }
  };

  const handleDateChange = (e) => {
    const newDate = e.target.value;
    setSelectedDate(newDate);
    onSwitchDate(newDate);
  };

  return (
    <header className="border-b border-[#2A313C] bg-[#11161F]">
      {/* SEBI Compliance Disclaimer Banner */}
      <div className="bg-[#1A1F29] border-b border-[#2A313C] px-4 py-1.5 text-xs text-[#9CA3AF] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-3.5 h-3.5 text-[#FBBF24] shrink-0" />
          <span>
            <strong className="text-[#D1D5DB]">Disclaimer:</strong> TradeZen is behavioral coaching, not SEBI-registered investment advice. Simulation & paper-trading only.
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-xs">
            {wsStatus === 'connected' ? (
              <>
                <span className="w-2 h-2 rounded-full bg-[#34D399] animate-pulse"></span>
                <span className="text-[#34D399] font-medium">Alerts Live</span>
              </>
            ) : wsStatus === 'reconnecting' ? (
              <>
                <span className="w-2 h-2 rounded-full bg-[#FBBF24]"></span>
                <span className="text-[#FBBF24]">Reconnecting</span>
              </>
            ) : (
              <>
                <span className="w-2 h-2 rounded-full bg-[#EF4444]"></span>
                <span className="text-[#9CA3AF]" title="FastAPI backend not running on port 8000. Run .\start_servers.ps1 in VS Code.">
                  Offline (Backend stopped)
                </span>
              </>
            )}
          </span>
        </div>
      </div>

      {/* Main Header Navigation */}
      <div className="px-5 py-3 flex flex-wrap items-center justify-between gap-4">
        {/* Brand */}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-[#1E3A5F] border border-[#3B82F6]/40 flex items-center justify-center shadow-inner">
            <span className="text-[#3B82F6] font-bold text-lg tracking-wider">TZ</span>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold text-[#F9FAFB] tracking-tight">TradeZen</h1>
              <span className="px-2 py-0.5 text-[10px] font-semibold tracking-wider uppercase rounded bg-[#1E3A5F] text-[#60A5FA] border border-[#3B82F6]/30">
                AI Coach
              </span>
            </div>
            <p className="text-[11px] text-[#9CA3AF]">Behavioral Guardrails, Execution & Scenarios</p>
          </div>
        </div>

        {/* Feature Navigation Tabs */}
        {onSelectMainTab && (
          <div className="flex items-center bg-[#1A1F29] border border-[#2A313C] rounded-lg p-1 gap-1">
            <button
              onClick={() => onSelectMainTab('paper')}
              className={`px-3 py-1.5 text-xs font-semibold rounded-md flex items-center gap-1.5 transition-all ${
                activeMainTab === 'paper'
                  ? 'bg-[#1E3A5F] text-[#60A5FA] shadow-sm border border-[#3B82F6]/30'
                  : 'text-[#9CA3AF] hover:text-[#D1D5DB] hover:bg-[#11161F]'
              }`}
            >
              <FastForward className="w-3.5 h-3.5 text-[#60A5FA]" />
              <span>Paper Trading</span>
            </button>
            <button
              onClick={() => onSelectMainTab('scenarios')}
              className={`px-3 py-1.5 text-xs font-semibold rounded-md flex items-center gap-1.5 transition-all ${
                activeMainTab === 'scenarios'
                  ? 'bg-[#1E3A5F] text-[#60A5FA] shadow-sm border border-[#3B82F6]/30'
                  : 'text-[#9CA3AF] hover:text-[#D1D5DB] hover:bg-[#11161F]'
              }`}
            >
              <Brain className="w-3.5 h-3.5 text-[#34D399]" />
              <span>Scenario Simulation</span>
            </button>
          </div>
        )}

        {/* Mode Selector & Clock Center Panel */}
        <div className="flex flex-wrap items-center bg-[#1A1F29] border border-[#2A313C] rounded-lg p-1.5 gap-2.5 shadow-sm">
          {/* Mode Switcher Toggle: REPLAY vs LIVE */}
          <div className="flex items-center bg-[#0E1116] rounded-md p-0.5 border border-[#2A313C]">
            <button
              onClick={() => onSwitchMode && onSwitchMode('REPLAY')}
              className={`px-2.5 py-1 text-xs font-semibold rounded transition-all ${
                clockStatus?.mode === 'REPLAY' || !clockStatus?.mode
                  ? 'bg-[#1E3A5F] text-[#60A5FA] shadow-sm'
                  : 'text-[#9CA3AF] hover:text-[#D1D5DB]'
              }`}
              title="Trade with historical database market bars"
            >
              Historical Replay
            </button>
            <button
              onClick={() => onSwitchMode && onSwitchMode('LIVE')}
              className={`px-2.5 py-1 text-xs font-semibold rounded flex items-center gap-1.5 transition-all ${
                clockStatus?.mode === 'LIVE'
                  ? 'bg-[#064E3B] text-[#34D399] shadow-sm'
                  : 'text-[#9CA3AF] hover:text-[#D1D5DB]'
              }`}
              title="Trade with Upstox Real-Time Market Feed"
            >
              <span className={`w-2 h-2 rounded-full ${clockStatus?.mode === 'LIVE' ? 'bg-[#34D399] animate-pulse' : 'bg-[#9CA3AF]'}`} />
              Live Market
            </button>
          </div>

          {/* Clock Display */}
          <div className="flex items-center gap-2 px-2.5 py-1 bg-[#0E1116] rounded border border-[#2A313C]">
            <Clock className="w-4 h-4 text-[#3B82F6]" />
            <div className="flex flex-col">
              <span className="text-[10px] text-[#9CA3AF] uppercase font-mono tracking-wider">
                {clockStatus?.mode === 'LIVE' ? 'Live Clock' : 'Replay Clock'} {clockStatus?.is_market_open ? '• Market Open' : '• Market Closed'}
              </span>
              <span className="text-sm font-semibold font-mono text-[#F9FAFB]">
                {clockStatus?.current_time || '2022-03-10 09:15:00'}
              </span>
            </div>
            <span
              className={`w-2 h-2 rounded-full ml-1 ${
                clockStatus?.is_market_open ? 'bg-[#34D399]' : 'bg-[#EF4444]'
              }`}
              title={clockStatus?.is_market_open ? 'Market is open (09:15 - 15:30)' : 'Market is closed'}
            />
          </div>

          {/* Controls specific to REPLAY mode */}
          {clockStatus?.mode !== 'LIVE' && (
            <>
              {/* Quick Tick Controls */}
              <div className="flex items-center gap-1">
                <button
                  onClick={() => handleTick(1)}
                  disabled={isAdvancing || isLoadingClock}
                  title="Advance replay by 1 minute"
                  className="px-2.5 py-1 text-xs font-mono font-medium rounded bg-[#0E1116] text-[#D1D5DB] border border-[#2A313C] hover:border-[#3B82F6] hover:text-[#F9FAFB] disabled:opacity-50 transition-colors"
                >
                  +1m
                </button>
                <button
                  onClick={() => handleTick(5)}
                  disabled={isAdvancing || isLoadingClock}
                  title="Advance replay by 5 minutes"
                  className="px-2.5 py-1 text-xs font-mono font-medium rounded bg-[#0E1116] text-[#D1D5DB] border border-[#2A313C] hover:border-[#3B82F6] hover:text-[#F9FAFB] disabled:opacity-50 transition-colors"
                >
                  +5m
                </button>
                <button
                  onClick={() => handleTick(15)}
                  disabled={isAdvancing || isLoadingClock}
                  title="Advance replay by 15 minutes"
                  className="px-2.5 py-1 text-xs font-mono font-medium rounded bg-[#0E1116] text-[#D1D5DB] border border-[#2A313C] hover:border-[#3B82F6] hover:text-[#F9FAFB] disabled:opacity-50 transition-colors"
                >
                  +15m
                </button>
                <button
                  onClick={() => handleTick(30)}
                  disabled={isAdvancing || isLoadingClock}
                  title="Advance replay by 30 minutes"
                  className="px-2.5 py-1 text-xs font-mono font-medium rounded bg-[#0E1116] text-[#D1D5DB] border border-[#2A313C] hover:border-[#3B82F6] hover:text-[#F9FAFB] disabled:opacity-50 transition-colors"
                >
                  +30m
                </button>
              </div>

              {/* Date Selector */}
              <div className="hidden sm:flex items-center pl-1 border-l border-[#2A313C]">
                <input
                  type="date"
                  value={selectedDate}
                  onChange={handleDateChange}
                  className="bg-[#0E1116] text-[#D1D5DB] border border-[#2A313C] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[#3B82F6]"
                />
              </div>
            </>
          )}

          {/* Live Mode Notice */}
          {clockStatus?.mode === 'LIVE' && (
            <div className="text-xs text-[#34D399] font-mono px-2 py-1 bg-[#064E3B]/40 rounded border border-[#059669]/50">
              Streaming Upstox V3 Feed
            </div>
          )}
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          {/* AI Risk Predict Trigger */}
          <button
            onClick={onRunAiPrediction}
            title="Scan current behavioral profile with XGBoost model"
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-[#1E3A5F] text-[#60A5FA] border border-[#3B82F6]/30 hover:bg-[#3B82F6] hover:text-[#F9FAFB] transition-all"
          >
            <Brain className="w-3.5 h-3.5 text-[#60A5FA]" />
            <span>AI Risk Scan</span>
          </button>

          {/* Rules Configuration Modal Trigger */}
          <button
            onClick={onOpenRules}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-[#1A1F29] text-[#D1D5DB] border border-[#2A313C] hover:border-[#374151] hover:text-[#F9FAFB] transition-all"
          >
            <Sliders className="w-3.5 h-3.5 text-[#9CA3AF]" />
            <span>Rules Setup</span>
          </button>

          {/* User Authentication Control */}
          {currentUser ? (
            <div className="flex items-center gap-2 pl-2 border-l border-[#2A313C]">
              <div className="flex items-center gap-1.5 px-2.5 py-1 bg-[#1A1F29] border border-[#2A313C] rounded-lg">
                <span className="w-2 h-2 rounded-full bg-[#34D399]"></span>
                <span className="text-xs font-semibold text-[#F9FAFB]">{currentUser.username}</span>
              </div>
              <button
                onClick={onLogout}
                title="Sign out of TradeZen"
                className="flex items-center gap-1 px-2 py-1 text-xs text-[#9CA3AF] hover:text-[#EF4444] transition-colors"
              >
                <LogOut className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Sign Out</span>
              </button>
            </div>
          ) : (
            <button
              onClick={onOpenAuth}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-[#2563EB] text-white hover:bg-[#1D4ED8] transition-all shadow-sm"
            >
              <User className="w-3.5 h-3.5" />
              <span>Sign In / Sign Up</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
