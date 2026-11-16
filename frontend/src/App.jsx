import React, { useState, useEffect, useCallback } from 'react';
import Header from './components/Header';
import TradingView from './components/TradingView';
import PortfolioView from './components/PortfolioView';
import AlertsPanel from './components/AlertsPanel';
import RulesModal from './components/RulesModal';
import AuthModal from './components/AuthModal';
import DynamicAuthPage from './components/DynamicAuthPage';
import ErrorBoundary from './components/ErrorBoundary';
import { ChatFeature } from './features/chat';
import { ScenarioPracticeView } from './features/scenarios';
import { useAlerts } from './useAlerts';
import { api } from './api';

export default function App() {
  const [currentUser, setCurrentUser] = useState(null);
  const [isAuthChecking, setIsAuthChecking] = useState(true);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [activeMainTab, setActiveMainTab] = useState('paper'); // 'paper' | 'scenarios'

  const [symbols, setSymbols] = useState(['INFY', 'RELIANCE', 'TCS', 'HDFCBANK', 'SBIN']);
  const [selectedSymbol, setSelectedSymbol] = useState('INFY');
  const [clockStatus, setClockStatus] = useState(null);
  const [isLoadingClock, setIsLoadingClock] = useState(false);
  const [currentPrice, setCurrentPrice] = useState(null);
  const [bars, setBars] = useState([]);
  const [livePrices, setLivePrices] = useState({});

  const [account, setAccount] = useState(null);
  const [positions, setPositions] = useState([]);
  const [trades, setTrades] = useState([]);
  const [userRules, setUserRules] = useState(null);

  const [isRulesModalOpen, setIsRulesModalOpen] = useState(false);
  const [aiScanning, setAiScanning] = useState(false);

  // Active user ID (dynamic based on logged in user or default 1)
  const activeUserId = currentUser ? currentUser.id : 1;

  // WebSocket hook for live alerts
  const { alerts, status: wsStatus, clearAlerts, dismissAlert } = useAlerts(activeUserId);

  // Check saved authentication session on mount
  useEffect(() => {
    const savedUserStr = localStorage.getItem('tradezen_user');
    const token = localStorage.getItem('tradezen_token');
    if (savedUserStr && token) {
      try {
        const parsed = JSON.parse(savedUserStr);
        setCurrentUser(parsed);
        // Verify with /auth/me
        api.getMe()
          .then((res) => {
            if (res.user) setCurrentUser(res.user);
            if (res.account) setAccount(res.account);
            if (res.rules) setUserRules(res.rules);
          })
          .catch(() => {
            // Token expired or invalid
            localStorage.removeItem('tradezen_token');
            localStorage.removeItem('tradezen_user');
            setCurrentUser(null);
          })
          .finally(() => {
            setIsAuthChecking(false);
          });
      } catch (e) {
        console.warn('Error reading saved user session:', e);
        setIsAuthChecking(false);
      }
    } else {
      setIsAuthChecking(false);
    }
  }, []);

  // Fetch tradable symbols
  useEffect(() => {
    api.getSymbols()
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) setSymbols(data);
      })
      .catch((err) => console.warn('Could not fetch symbols:', err));
  }, []);

  // Fetch initial user rules
  useEffect(() => {
    api.getRules(1)
      .then((rules) => setUserRules(rules))
      .catch((err) => console.warn('Could not fetch rules:', err));
  }, []);

  // Refresh clock state
  const refreshClock = useCallback(async () => {
    try {
      const clockData = await api.getClock();
      setClockStatus(clockData);
      return clockData;
    } catch (err) {
      console.warn('Clock fetch error:', err);
      return null;
    }
  }, []);

  // Refresh market data for selected symbol & time
  const refreshMarketData = useCallback(async (sym = selectedSymbol, clock = clockStatus) => {
    try {
      if (clock?.mode === 'LIVE') {
        // In LIVE mode: candles come from GET /live/candles
        try {
          const candleData = await api.getLiveCandles(sym, 300);
          if (candleData?.candles) {
            const mappedBars = candleData.candles.map((c) => ({
              ...c,
              timestamp: c.time ? c.time.replace('T', ' ').slice(0, 19) : '',
            }));
            setBars(mappedBars);
          } else {
            setBars([]);
          }
        } catch (candleErr) {
          console.warn('Live candles fetch error:', candleErr);
          setBars([]);
        }

        try {
          const livePriceData = await api.getLivePrice(sym);
          if (livePriceData?.ok && livePriceData?.ltp) {
            setCurrentPrice({
              symbol: sym,
              close: livePriceData.ltp,
              open: livePriceData.open || livePriceData.ltp,
              high: livePriceData.high || livePriceData.ltp,
              low: livePriceData.low || livePriceData.ltp,
              volume: livePriceData.volume || 0,
              timestamp: livePriceData.last_trade_time || livePriceData.ltt,
            });
          } else {
            setCurrentPrice(null);
          }
        } catch {
          setCurrentPrice(null);
        }
        return;
      }

      // In REPLAY mode: fetch historical price and bars
      const priceQuote = await api.getPrice(sym);
      setCurrentPrice(priceQuote);

      const currentTimeStr = clock?.current_time || '2022-03-10 15:30:00';
      const replayDate = clock?.replay_date || currentTimeStr.split(' ')[0] || '2022-03-10';
      const startTime = `${replayDate} 09:15`;
      const endTime = currentTimeStr.slice(0, 16);

      const barList = await api.getBars(sym, startTime, endTime, 500);
      setBars(barList);
    } catch (err) {
      console.warn('Market data fetch error:', err);
    }
  }, [selectedSymbol, clockStatus]);

  // LIVE mode only: poll GET /live/prices every 2 seconds
  useEffect(() => {
    if (clockStatus?.mode !== 'LIVE') return;

    let isMounted = true;
    const pollLivePrices = async () => {
      try {
        const prices = await api.getLivePrices();
        if (!isMounted) return;
        setLivePrices(prices || {});

        const selectedLive = prices?.[selectedSymbol];
        if (selectedLive?.ok && selectedLive?.ltp) {
          setCurrentPrice({
            symbol: selectedSymbol,
            close: selectedLive.ltp,
            open: selectedLive.open || selectedLive.ltp,
            high: selectedLive.high || selectedLive.ltp,
            low: selectedLive.low || selectedLive.ltp,
            volume: selectedLive.volume || 0,
            timestamp: selectedLive.last_trade_time || selectedLive.ltt || new Date().toISOString(),
          });
        } else if (selectedLive && !selectedLive.ok) {
          setCurrentPrice(null);
        }
      } catch (err) {
        console.warn('Live prices poll error:', err);
      }
    };

    pollLivePrices();
    const interval = setInterval(pollLivePrices, 2000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [clockStatus?.mode, selectedSymbol]);

  // Refresh portfolio & trades
  const refreshPortfolio = useCallback(async () => {
    try {
      const [acc, pos, tr] = await Promise.all([
        api.getAccount(activeUserId),
        api.getPositions(activeUserId, true),
        api.getTrades(activeUserId),
      ]);
      setAccount(acc);
      setPositions(pos);
      setTrades(tr);
    } catch (err) {
      console.warn('Portfolio refresh error:', err);
    }
  }, [activeUserId]);

  // Auth event handlers
  const handleAuthSuccess = (user, acc) => {
    setCurrentUser(user);
    if (acc) setAccount(acc);
    api.getRules(user.id).then(setUserRules).catch(console.warn);
    refreshPortfolio();
  };

  const handleLogout = () => {
    localStorage.removeItem('tradezen_token');
    localStorage.removeItem('tradezen_user');
    setCurrentUser(null);
    api.getRules(1).then(setUserRules).catch(console.warn);
    refreshPortfolio();
  };

  // Initial load
  useEffect(() => {
    refreshClock().then((clock) => {
      refreshMarketData('INFY', clock);
    });
    refreshPortfolio();
  }, [activeUserId]);

  // When selected symbol changes
  useEffect(() => {
    refreshMarketData(selectedSymbol, clockStatus);
  }, [selectedSymbol]);

  // Tick clock action
  const handleTickClock = async (minutes) => {
    setIsLoadingClock(true);
    try {
      const newClock = await api.tickClock(minutes);
      setClockStatus(newClock);
      await Promise.all([
        refreshMarketData(selectedSymbol, newClock),
        refreshPortfolio(),
      ]);
    } catch (err) {
      alert(`Clock error: ${err.message}`);
    } finally {
      setIsLoadingClock(false);
    }
  };

  // Switch market clock mode (REPLAY vs LIVE)
  const handleSwitchMode = async (mode) => {
    setIsLoadingClock(true);
    try {
      const payload = { mode };
      if (mode === 'REPLAY') {
        payload.replay_date = clockStatus?.replay_date || '2022-03-10';
        payload.start_time = '09:15';
        payload.end_time = '15:30';
      }
      const newClock = await api.setClockMode(payload);
      setClockStatus(newClock);
      await Promise.all([
        refreshMarketData(selectedSymbol, newClock),
        refreshPortfolio(),
      ]);
    } catch (err) {
      alert(`Failed to switch mode: ${err.message}`);
    } finally {
      setIsLoadingClock(false);
    }
  };

  // Switch replay date action
  const handleSwitchDate = async (newDate) => {
    setIsLoadingClock(true);
    try {
      const newClock = await api.setClockMode({
        mode: 'REPLAY',
        replay_date: newDate,
        start_time: '09:15',
        end_time: '15:30',
      });
      setClockStatus(newClock);
      await Promise.all([
        refreshMarketData(selectedSymbol, newClock),
        refreshPortfolio(),
      ]);
    } catch (err) {
      alert(`Failed to set replay date: ${err.message}`);
    } finally {
      setIsLoadingClock(false);
    }
  };

  // Run AI Risk Scan with XGBoost
  const handleRunAiPrediction = async () => {
    setAiScanning(true);
    try {
      const result = await api.predictRisk(activeUserId);
      const score = result.risk_score ?? result.violation_risk ?? 0;
      const riskPct = (score * 100).toFixed(1);
      if (result.is_high_risk || result.alert) {
        // High risk alert created and streamed over WebSocket
      } else {
        alert(`AI Risk Evaluation: ${riskPct}% risk (Under alert threshold of 50%). Behavioral pattern is disciplined.`);
      }
    } catch (err) {
      alert(`AI Model scan error: ${err.message}`);
    } finally {
      setAiScanning(false);
    }
  };

  // When order is successfully placed
  const handleOrderPlaced = () => {
    refreshPortfolio();
    refreshMarketData(selectedSymbol, clockStatus);
  };

  // Loading Splash Screen while verifying existing auth token
  if (isAuthChecking) {
    return (
      <div className="min-h-screen bg-[#0E1116] flex items-center justify-center font-sans">
        <div className="flex flex-col items-center gap-3">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-[#1E3A5F] to-[#0E1116] border border-[#3B82F6]/40 flex items-center justify-center shadow-lg shadow-[#3B82F6]/20 animate-pulse">
            <span className="text-[#3B82F6] font-extrabold text-xl">TZ</span>
          </div>
          <span className="text-xs text-[#9CA3AF] tracking-wider uppercase font-semibold">Loading TradeZen Platform...</span>
        </div>
      </div>
    );
  }

  // If user is not authenticated, display the Dynamic Signup / Login page
  if (!currentUser) {
    return <DynamicAuthPage onAuthSuccess={handleAuthSuccess} />;
  }

  return (
    <div className="min-h-screen bg-[#0E1116] text-[#F9FAFB] flex flex-col font-sans">
      {/* Top Header */}
      <Header
        clockStatus={clockStatus}
        wsStatus={wsStatus}
        onTickClock={handleTickClock}
        onSwitchDate={handleSwitchDate}
        onSwitchMode={handleSwitchMode}
        onOpenRules={() => setIsRulesModalOpen(true)}
        onRunAiPrediction={handleRunAiPrediction}
        isLoadingClock={isLoadingClock || aiScanning}
        currentUser={currentUser}
        onOpenAuth={() => setIsAuthModalOpen(true)}
        onLogout={handleLogout}
        activeMainTab={activeMainTab}
        onSelectMainTab={setActiveMainTab}
      />

      {/* Main Container */}
      {activeMainTab === 'paper' ? (
        <main className="flex-1 p-4 lg:p-6 max-w-[1600px] w-full mx-auto grid grid-cols-1 xl:grid-cols-12 gap-6">
          {/* Left Column (8 cols): Trading Chart, Order Entry, and Portfolio */}
          <section className="xl:col-span-8 flex flex-col gap-6">
            {/* Trading View */}
            <TradingView
              symbols={symbols}
              selectedSymbol={selectedSymbol}
              onSelectSymbol={setSelectedSymbol}
              currentPrice={currentPrice}
              bars={bars}
              onOrderPlaced={handleOrderPlaced}
              userRules={userRules}
              userId={activeUserId}
              isLiveMode={clockStatus?.mode === 'LIVE'}
              livePrices={livePrices}
            />

            {/* Portfolio & Trades */}
            <PortfolioView
              account={account}
              positions={positions}
              trades={trades}
              onRefreshPortfolio={refreshPortfolio}
            />
          </section>

          {/* Right Column (4 cols): Live Behavioral Alerts & Coaching Feed */}
          <aside className="xl:col-span-4 flex flex-col gap-4">
            <AlertsPanel
              alerts={alerts}
              onClearAlerts={clearAlerts}
              onDismissAlert={dismissAlert}
            />
          </aside>
        </main>
      ) : (
        <main className="flex-1 p-4 lg:p-6 max-w-[1600px] w-full mx-auto">
          <ErrorBoundary fallbackTitle="Scenario Simulation Unavailable">
            <ScenarioPracticeView currentUser={currentUser} />
          </ErrorBoundary>
        </main>
      )}

      {/* Rules Setup Modal */}
      <RulesModal
        isOpen={isRulesModalOpen}
        onClose={() => setIsRulesModalOpen(false)}
        userRules={userRules}
        onRulesUpdated={(updated) => setUserRules(updated)}
      />

      {/* Authentication Modal */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
        onAuthSuccess={handleAuthSuccess}
      />

      {/* TradeZen Coach Floating Assistant */}
      <ChatFeature />
    </div>
  );
}
