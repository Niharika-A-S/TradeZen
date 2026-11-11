import React, { useState, useEffect } from 'react';
import { api } from '../../api';
import CandleChart from './CandleChart';
import FeedbackCard from './FeedbackCard';
import RevealPanel from './RevealPanel';
import Dashboard from './Dashboard';
import {
  Shield,
  TrendingUp,
  AlertTriangle,
  CheckCircle,
  RefreshCw,
  BarChart2,
  History,
  ArrowUpRight,
  ArrowDownRight,
  Sliders,
  Play,
  RotateCcw
} from 'lucide-react';

export default function ScenarioPracticeView({ currentUser }) {
  const [subTab, setSubTab] = useState('trainer'); // 'trainer' | 'dashboard' | 'history' | 'rules'
  const [scenarios, setScenarios] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedAction, setSelectedAction] = useState('buy'); // 'buy' | 'sell' | 'hold'
  const [decisionSize, setDecisionSize] = useState(10000);
  const [decisionReason, setDecisionReason] = useState('Followed my rule');
  const [decisionNote, setDecisionNote] = useState('');
  const [decisionSeconds, setDecisionSeconds] = useState(5.0);
  const [scenarioStartTime, setScenarioStartTime] = useState(Date.now());

  const [feedback, setFeedback] = useState(null);
  const [revealData, setRevealData] = useState(null);
  const [isRevisionMode, setIsRevisionMode] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);

  // History & Dashboard State
  const [pastAttempts, setPastAttempts] = useState([]);
  const [dashboardData, setDashboardData] = useState(null);

  // Rules state
  const [stopLoss, setStopLoss] = useState(2.0);
  const [maxTrades, setMaxTrades] = useState(5);
  const [noAveraging, setNoAveraging] = useState(true);
  const [maxPosition, setMaxPosition] = useState(20.0);
  const [practiceCapital, setPracticeCapital] = useState(100000.0);
  const [rulesSuccessMessage, setRulesSuccessMessage] = useState('');

  const loadScenarios = async () => {
    try {
      setLoading(true);
      setLoadError(null);
      const data = await api.getNextScenarios(15);
      if (Array.isArray(data) && data.length > 0) {
        setScenarios(data);
        setCurrentIndex(0);
      } else {
        setScenarios([]);
      }
      setFeedback(null);
      setRevealData(null);
      setIsRevisionMode(false);
      setDecisionNote('');
      setScenarioStartTime(Date.now());
    } catch (err) {
      console.warn('Failed to load scenarios', err);
      setLoadError(err.message || 'Could not load practice scenarios.');
    } finally {
      setLoading(false);
    }
  };

  const loadRules = async () => {
    try {
      const activeRule = await api.getCurrentRules?.();
      if (activeRule) {
        setStopLoss(activeRule.stop_loss_pct ?? 2.0);
        setMaxTrades(activeRule.max_trades_per_day ?? 5);
        setNoAveraging(activeRule.no_averaging_down ?? true);
        setMaxPosition(activeRule.max_position_pct ?? 20.0);
        setPracticeCapital(activeRule.practice_capital ?? 100000.0);
      }
    } catch (e) {
      console.warn('Could not load scenario rules:', e);
    }
  };

  const loadDashboard = async () => {
    try {
      const data = await api.getDashboard();
      setDashboardData(data);
    } catch (err) {
      console.warn('Could not load dashboard data:', err);
    }
  };

  useEffect(() => {
    loadScenarios();
    loadRules();
  }, [currentUser]);

  useEffect(() => {
    if (subTab === 'dashboard') {
      loadDashboard();
    }
  }, [subTab]);

  const handleSubmitDecision = async () => {
    const currentScenario = scenarios[currentIndex];
    if (!currentScenario) return;

    const seconds = Math.max(1.0, Math.round((Date.now() - scenarioStartTime) / 100) / 10);
    setDecisionSeconds(seconds);

    const fullReason = decisionNote.trim() ? `${decisionReason} - ${decisionNote.trim()}` : decisionReason;

    try {
      setLoading(true);
      const res = await api.submitDecision({
        scenario_id: currentScenario.id,
        action: selectedAction,
        size: parseFloat(decisionSize),
        reason: fullReason,
        decision_seconds: seconds,
        chart_viewed: true,
        after_reveal: Boolean(revealData || isRevisionMode),
      });

      setFeedback(res);
      setPastAttempts((prev) => [
        {
          scenario_id: currentScenario.id,
          attempt_no: res.attempt_no,
          action: selectedAction,
          size: decisionSize,
          reason: fullReason,
          label: res.pattern_feedback?.label,
          passed: res.rules_feedback?.passed,
          timestamp: new Date().toLocaleTimeString(),
          scenario: currentScenario,
        },
        ...prev,
      ]);
    } catch (err) {
      alert(`Error submitting decision: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleReveal = async () => {
    const currentScenario = scenarios[currentIndex];
    if (!currentScenario) return;
    try {
      const data = await api.getReveal(currentScenario.id);
      setRevealData(data);
    } catch (err) {
      alert(`Could not reveal outcome: ${err.message}`);
    }
  };

  const handleChangeAnswer = () => {
    setFeedback(null);
    setIsRevisionMode(true);
  };

  const handleNextScenario = () => {
    setFeedback(null);
    setRevealData(null);
    setIsRevisionMode(false);
    setDecisionNote('');
    if (currentIndex + 1 < scenarios.length) {
      setCurrentIndex(currentIndex + 1);
    } else {
      loadScenarios();
    }
  };

  const handleSaveRules = async (e) => {
    e.preventDefault();
    setRulesSuccessMessage('');
    try {
      const saved = await api.setRules({
        stop_loss_pct: parseFloat(stopLoss),
        max_trades_per_day: parseInt(maxTrades, 10),
        no_averaging_down: Boolean(noAveraging),
        max_position_pct: parseFloat(maxPosition),
        practice_capital: parseFloat(practiceCapital),
      });
      setRulesSuccessMessage(`Rule Version ${saved?.version || 1} saved!`);
    } catch (err) {
      alert(`Error saving scenario rules: ${err.message}`);
    }
  };

  const currentScenario = scenarios[currentIndex];
  const pnlPercent = currentScenario ? -currentScenario.drop_pct : 0.0;
  const isLoss = pnlPercent < 0;

  return (
    <div className="flex flex-col gap-5">
      {/* Sub-Navigation Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-[#11161F] border border-[#2A313C] p-2.5 rounded-xl shadow-sm">
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setSubTab('trainer')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors ${
              subTab === 'trainer'
                ? 'bg-[#1E3A5F] text-[#60A5FA] border border-[#3B82F6]/40'
                : 'text-[#9CA3AF] hover:text-[#F9FAFB] hover:bg-[#1A1F29]'
            }`}
          >
            <Play className="w-3.5 h-3.5" />
            <span>Practice Trainer</span>
          </button>

          <button
            onClick={() => setSubTab('dashboard')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors ${
              subTab === 'dashboard'
                ? 'bg-[#1E3A5F] text-[#60A5FA] border border-[#3B82F6]/40'
                : 'text-[#9CA3AF] hover:text-[#F9FAFB] hover:bg-[#1A1F29]'
            }`}
          >
            <BarChart2 className="w-3.5 h-3.5" />
            <span>Discipline Dashboard</span>
          </button>

          <button
            onClick={() => setSubTab('history')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors ${
              subTab === 'history'
                ? 'bg-[#1E3A5F] text-[#60A5FA] border border-[#3B82F6]/40'
                : 'text-[#9CA3AF] hover:text-[#F9FAFB] hover:bg-[#1A1F29]'
            }`}
          >
            <History className="w-3.5 h-3.5" />
            <span>Decisions History ({pastAttempts.length})</span>
          </button>

          <button
            onClick={() => setSubTab('rules')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors ${
              subTab === 'rules'
                ? 'bg-[#1E3A5F] text-[#60A5FA] border border-[#3B82F6]/40'
                : 'text-[#9CA3AF] hover:text-[#F9FAFB] hover:bg-[#1A1F29]'
            }`}
          >
            <Sliders className="w-3.5 h-3.5" />
            <span>Scenario Guardrails</span>
          </button>
        </div>

        {subTab === 'trainer' && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-[#9CA3AF] font-mono">
              Scenario {scenarios.length > 0 ? currentIndex + 1 : 0} of {scenarios.length}
            </span>
            <button
              onClick={loadScenarios}
              disabled={loading}
              title="Refresh Scenario Pool"
              className="p-1.5 rounded bg-[#1A1F29] border border-[#2A313C] text-[#D1D5DB] hover:text-white"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        )}
      </div>

      {/* Main Tab Content */}
      {subTab === 'trainer' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Chart & Market Situation (8 cols) */}
          <div className="lg:col-span-8 space-y-4">
            <div className="bg-[#11161F] border border-[#2A313C] rounded-xl p-4 shadow-md space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#2A313C] pb-3">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-[#1E3A5F] flex items-center justify-center text-[#60A5FA]">
                    <Shield className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-[#F9FAFB] flex items-center gap-2">
                      <span>Live Behavioral Scenario</span>
                      {isRevisionMode && (
                        <span className="text-[10px] uppercase font-semibold bg-[#3B82F6]/20 text-[#60A5FA] px-2 py-0.5 rounded border border-[#3B82F6]/30">
                          Revision Mode
                        </span>
                      )}
                    </h3>
                    <p className="text-xs text-[#9CA3AF]">
                      Blind replay test — Symbol & timestamp masked to neutralize hindsight bias
                    </p>
                  </div>
                </div>

                {currentScenario && (
                  <div className="flex items-center gap-3">
                    <div className="text-right">
                      <div className="text-xs text-[#9CA3AF]">Drawdown from Entry</div>
                      <div
                        className={`text-sm font-bold font-mono flex items-center justify-end gap-1 ${
                          isLoss ? 'text-[#F87171]' : 'text-[#34D399]'
                        }`}
                      >
                        {isLoss ? (
                          <ArrowDownRight className="w-4 h-4 text-[#F87171]" />
                        ) : (
                          <ArrowUpRight className="w-4 h-4 text-[#34D399]" />
                        )}
                        <span>{pnlPercent.toFixed(2)}%</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Chart Component */}
              {currentScenario ? (
                <div className="h-[340px] w-full rounded-lg overflow-hidden border border-[#2A313C] bg-[#1A1F29]">
                  <CandleChart
                    candles={currentScenario.candles || []}
                    outcomeCandles={revealData?.outcome_candles || null}
                    decisionPrice={currentScenario.current_price}
                    isRevealed={Boolean(revealData)}
                    height={340}
                  />
                </div>
              ) : (
                <div className="h-[340px] flex flex-col items-center justify-center text-[#9CA3AF] border border-[#2A313C] rounded-lg p-6 space-y-3">
                  {loading ? (
                    <div className="flex items-center space-x-2 text-sm text-[#60A5FA]">
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Loading scenario simulation data...</span>
                    </div>
                  ) : loadError ? (
                    <div className="text-center space-y-2">
                      <p className="text-xs text-[#F87171]">{loadError}</p>
                      <button
                        type="button"
                        onClick={loadScenarios}
                        className="px-3 py-1.5 rounded bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-xs font-semibold"
                      >
                        Retry Loading
                      </button>
                    </div>
                  ) : (
                    <div className="text-center space-y-2">
                      <p className="text-xs text-[#9CA3AF]">No unseen scenarios available in your practice pool.</p>
                      <button
                        type="button"
                        onClick={loadScenarios}
                        className="px-3 py-1.5 rounded bg-[#1A1F29] hover:bg-[#2A313C] text-[#F9FAFB] text-xs font-semibold border border-[#2A313C]"
                      >
                        Reset / Refresh Scenarios
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Outcome Reveal Panel (Appears after submission or button click) */}
            {revealData && (
              <RevealPanel
                revealData={revealData}
                onNextScenario={handleNextScenario}
                onChangeAnswer={handleChangeAnswer}
              />
            )}
          </div>

          {/* Decision Panel & Behavioral Feedback (4 cols) */}
          <div className="lg:col-span-4 space-y-4">
            {/* Action Box */}
            <div className="bg-[#11161F] border border-[#2A313C] rounded-xl p-4 shadow-md space-y-4">
              <h4 className="text-xs font-bold text-[#F9FAFB] uppercase tracking-wider">
                What is your trading decision?
              </h4>

              {/* Action Buttons */}
              <div className="grid grid-cols-3 gap-2">
                <button
                  type="button"
                  onClick={() => setSelectedAction('buy')}
                  disabled={Boolean(feedback && !isRevisionMode)}
                  className={`py-2 rounded-lg text-xs font-bold tracking-wide uppercase transition-all ${
                    selectedAction === 'buy'
                      ? 'bg-[#34D399] text-[#064E3B] ring-2 ring-[#34D399]/50 shadow-md'
                      : 'bg-[#1A1F29] text-[#D1D5DB] border border-[#2A313C] hover:border-[#374151]'
                  }`}
                >
                  Buy More
                </button>

                <button
                  type="button"
                  onClick={() => setSelectedAction('hold')}
                  disabled={Boolean(feedback && !isRevisionMode)}
                  className={`py-2 rounded-lg text-xs font-bold tracking-wide uppercase transition-all ${
                    selectedAction === 'hold'
                      ? 'bg-[#3B82F6] text-white ring-2 ring-[#3B82F6]/50 shadow-md'
                      : 'bg-[#1A1F29] text-[#D1D5DB] border border-[#2A313C] hover:border-[#374151]'
                  }`}
                >
                  Hold Position
                </button>

                <button
                  type="button"
                  onClick={() => setSelectedAction('sell')}
                  disabled={Boolean(feedback && !isRevisionMode)}
                  className={`py-2 rounded-lg text-xs font-bold tracking-wide uppercase transition-all ${
                    selectedAction === 'sell'
                      ? 'bg-[#EF4444] text-white ring-2 ring-[#EF4444]/50 shadow-md'
                      : 'bg-[#1A1F29] text-[#D1D5DB] border border-[#2A313C] hover:border-[#374151]'
                  }`}
                >
                  Cut / Exit
                </button>
              </div>

              {/* Allocation Size */}
              <div className="space-y-1.5">
                <label className="text-xs text-[#9CA3AF] flex justify-between">
                  <span>Allocation Size</span>
                  <span className="font-mono text-[#F9FAFB]">₹{Number(decisionSize).toLocaleString('en-IN')}</span>
                </label>
                <input
                  type="number"
                  min="1000"
                  max="100000"
                  step="1000"
                  value={decisionSize}
                  onChange={(e) => setDecisionSize(e.target.value)}
                  disabled={Boolean(feedback && !isRevisionMode)}
                  className="w-full bg-[#1A1F29] border border-[#2A313C] rounded-lg px-3 py-1.5 text-xs text-[#F9FAFB] focus:border-[#3B82F6] outline-none"
                />
              </div>

              {/* Mental State / Reason */}
              <div className="space-y-1.5">
                <label className="text-xs text-[#9CA3AF]">Psychological Trigger / Reason</label>
                <select
                  value={decisionReason}
                  onChange={(e) => setDecisionReason(e.target.value)}
                  disabled={Boolean(feedback && !isRevisionMode)}
                  className="w-full bg-[#1A1F29] border border-[#2A313C] rounded-lg px-3 py-1.5 text-xs text-[#F9FAFB] focus:border-[#3B82F6] outline-none"
                >
                  <option value="Followed my rule">Followed my defined rule</option>
                  <option value="Fear of further loss">Fear of further drawdown</option>
                  <option value="FOMO / Rebound hope">FOMO / Hoping for quick rebound</option>
                  <option value="Averaging down discount">Averaging down for lower cost</option>
                  <option value="Recover yesterday loss">Attempting to recover earlier loss</option>
                  <option value="Gut instinct">Gut instinct</option>
                </select>
              </div>

              {/* Submit Decision */}
              {!feedback || isRevisionMode ? (
                <button
                  type="button"
                  onClick={handleSubmitDecision}
                  disabled={loading || !currentScenario}
                  className="w-full py-2.5 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-xs font-bold transition-all shadow-md disabled:opacity-50"
                >
                  {loading ? 'Evaluating Model...' : 'Lock In Decision & Get Feedback'}
                </button>
              ) : (
                <div className="flex gap-2">
                  {!revealData && (
                    <button
                      type="button"
                      onClick={handleReveal}
                      className="flex-1 py-2 rounded-lg bg-[#1E3A5F] hover:bg-[#3B82F6] text-[#60A5FA] hover:text-white text-xs font-bold transition-all border border-[#3B82F6]/30"
                    >
                      Reveal Market Outcome
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={handleNextScenario}
                    className="flex-1 py-2 rounded-lg bg-[#34D399] hover:bg-[#10B981] text-[#064E3B] text-xs font-bold transition-all shadow-md"
                  >
                    Next Scenario →
                  </button>
                </div>
              )}
            </div>

            {/* Three-part Behavioral Feedback Card */}
            {feedback && (
              <FeedbackCard
                feedback={feedback}
                attemptId={feedback.attempt_id}
              />
            )}
          </div>
        </div>
      )}

      {/* Dashboard Sub-Tab */}
      {subTab === 'dashboard' && (
        <div className="bg-[#11161F] border border-[#2A313C] rounded-xl p-6 shadow-md">
          <Dashboard
            data={dashboardData}
            onRestartSeason={() => {
              api.restartProgress().then(() => loadDashboard());
            }}
            onStartPracticing={() => setSubTab('trainer')}
          />
        </div>
      )}

      {/* History Sub-Tab */}
      {subTab === 'history' && (
        <div className="bg-[#11161F] border border-[#2A313C] rounded-xl p-5 shadow-md space-y-4">
          <div className="flex items-center justify-between border-b border-[#2A313C] pb-3">
            <h3 className="text-sm font-bold text-[#F9FAFB]">Scenario Decision Log</h3>
            <span className="text-xs text-[#9CA3AF] font-mono">{pastAttempts.length} decisions recorded</span>
          </div>

          {pastAttempts.length === 0 ? (
            <div className="text-center py-10 text-xs text-[#9CA3AF]">
              No attempts recorded in this session yet. Complete scenarios in the trainer to track your decisions.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[#2A313C] text-[#9CA3AF]">
                    <th className="py-2 px-3">Time</th>
                    <th className="py-2 px-3">Action</th>
                    <th className="py-2 px-3">Size</th>
                    <th className="py-2 px-3">Reason</th>
                    <th className="py-2 px-3">AI Pattern</th>
                    <th className="py-2 px-3">Rule Result</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#2A313C]">
                  {pastAttempts.map((item, idx) => (
                    <tr key={idx} className="hover:bg-[#1A1F29]/50 transition-colors">
                      <td className="py-2.5 px-3 font-mono text-[#9CA3AF]">{item.timestamp}</td>
                      <td className="py-2.5 px-3 uppercase font-bold text-[#F9FAFB]">{item.action}</td>
                      <td className="py-2.5 px-3 font-mono">₹{Number(item.size).toLocaleString('en-IN')}</td>
                      <td className="py-2.5 px-3 text-[#D1D5DB]">{item.reason}</td>
                      <td className="py-2.5 px-3">
                        <span className="px-2 py-0.5 rounded text-[11px] font-semibold uppercase bg-[#1E3A5F] text-[#60A5FA]">
                          {item.label || 'disciplined'}
                        </span>
                      </td>
                      <td className="py-2.5 px-3">
                        <span className={`font-semibold ${item.passed ? 'text-[#34D399]' : 'text-[#F87171]'}`}>
                          {item.passed ? 'Passed' : 'Violated'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Rules Sub-Tab */}
      {subTab === 'rules' && (
        <div className="bg-[#11161F] border border-[#2A313C] rounded-xl p-6 shadow-md max-w-2xl mx-auto space-y-4">
          <div className="flex items-center gap-3 border-b border-[#2A313C] pb-3">
            <Sliders className="w-5 h-5 text-[#60A5FA]" />
            <div>
              <h3 className="text-sm font-bold text-[#F9FAFB]">Simulation Guardrails & Risk Settings</h3>
              <p className="text-xs text-[#9CA3AF]">Personal behavioral rules tested during practice scenarios</p>
            </div>
          </div>

          {rulesSuccessMessage && (
            <div className="p-3 rounded-lg bg-[#064E3B]/40 border border-[#059669]/50 text-xs text-[#34D399] flex items-center gap-2">
              <CheckCircle className="w-4 h-4 shrink-0" />
              <span>{rulesSuccessMessage}</span>
            </div>
          )}

          <form onSubmit={handleSaveRules} className="space-y-4 text-xs">
            <div className="space-y-1">
              <label className="text-[#9CA3AF]">Hard Stop-Loss Cutoff (% per trade)</label>
              <input
                type="number"
                step="0.5"
                min="0.5"
                max="10"
                value={stopLoss}
                onChange={(e) => setStopLoss(e.target.value)}
                className="w-full bg-[#1A1F29] border border-[#2A313C] rounded-lg px-3 py-2 text-[#F9FAFB] outline-none focus:border-[#3B82F6]"
              />
            </div>

            <div className="space-y-1">
              <label className="text-[#9CA3AF]">Max Trades Per Day Limit</label>
              <input
                type="number"
                min="1"
                max="20"
                value={maxTrades}
                onChange={(e) => setMaxTrades(e.target.value)}
                className="w-full bg-[#1A1F29] border border-[#2A313C] rounded-lg px-3 py-2 text-[#F9FAFB] outline-none focus:border-[#3B82F6]"
              />
            </div>

            <div className="space-y-1">
              <label className="text-[#9CA3AF]">Max Position Exposure (% of capital)</label>
              <input
                type="number"
                step="5"
                min="5"
                max="100"
                value={maxPosition}
                onChange={(e) => setMaxPosition(e.target.value)}
                className="w-full bg-[#1A1F29] border border-[#2A313C] rounded-lg px-3 py-2 text-[#F9FAFB] outline-none focus:border-[#3B82F6]"
              />
            </div>

            <div className="flex items-center gap-2 pt-2">
              <input
                type="checkbox"
                id="noAveraging"
                checked={noAveraging}
                onChange={(e) => setNoAveraging(e.target.checked)}
                className="rounded border-[#2A313C] bg-[#1A1F29] text-[#3B82F6] focus:ring-0"
              />
              <label htmlFor="noAveraging" className="text-[#D1D5DB]">
                Enforce Strict Rule: No averaging down into losing positions
              </label>
            </div>

            <button
              type="submit"
              className="w-full py-2.5 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white font-bold transition-all shadow-md"
            >
              Save Simulation Guardrails
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
