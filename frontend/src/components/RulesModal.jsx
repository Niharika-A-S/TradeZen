import React, { useState, useEffect } from 'react';
import { Sliders, CheckCircle2, AlertCircle, X, Shield, RefreshCw } from 'lucide-react';
import { api } from '../api';

export default function RulesModal({ isOpen, onClose, userRules, onRulesUpdated }) {
  const [formData, setFormData] = useState({
    max_trades_per_day: 5,
    max_risk_per_trade_pct: 2.0,
    max_daily_loss: 5000.0,
    max_consecutive_losses: 3,
    require_stop_loss: true,
    intraday_cutoff_time: '15:15',
  });

  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState(null);

  useEffect(() => {
    if (userRules) {
      setFormData((prev) => ({
        ...prev,
        ...userRules,
      }));
    }
  }, [userRules]);

  if (!isOpen) return null;

  const handleChange = (field, val) => {
    setFormData((prev) => ({
      ...prev,
      [field]: val,
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    try {
      const clampedTrades = Math.min(50, Math.max(1, parseInt(formData.max_trades_per_day, 10) || 5));
      const clampedRisk = Math.min(10.0, Math.max(0.1, parseFloat(formData.max_risk_per_trade_pct) || 2.0));
      const clampedConsLoss = Math.min(10, Math.max(1, parseInt(formData.max_consecutive_losses, 10) || 3));
      const updated = await api.updateRules(1, {
        max_trades_per_day: clampedTrades,
        max_risk_per_trade_pct: clampedRisk,
        max_daily_loss: parseFloat(formData.max_daily_loss),
        max_consecutive_losses: clampedConsLoss,
        require_stop_loss: Boolean(formData.require_stop_loss),
        intraday_cutoff_time: formData.intraday_cutoff_time || '15:15',
      });
      setSaveSuccess(true);
      if (onRulesUpdated) onRulesUpdated(updated);
      setTimeout(() => {
        setSaveSuccess(false);
        onClose();
      }, 1000);
    } catch (err) {
      setSaveError(err.message || 'Failed to save rules');
    } finally {
      setIsSaving(false);
    }
  };

  const handleResetDefaults = () => {
    setFormData({
      max_trades_per_day: 5,
      max_risk_per_trade_pct: 2.0,
      max_daily_loss: 5000.0,
      max_consecutive_losses: 3,
      require_stop_loss: true,
      intraday_cutoff_time: '15:15',
    });
  };

  return (
    <div className="fixed inset-0 z-50 bg-[#0E1116]/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-[#1A1F29] border border-[#2A313C] rounded-xl max-w-lg w-full p-6 shadow-2xl relative">
        {/* Header */}
        <div className="flex items-center justify-between pb-3 mb-4 border-b border-[#2A313C]">
          <div className="flex items-center gap-2 text-[#3B82F6]">
            <Sliders className="w-5 h-5 text-[#3B82F6]" />
            <h2 className="text-sm font-bold uppercase tracking-wider text-[#F9FAFB]">
              Personal Behavioral Guardrails
            </h2>
          </div>
          <button
            onClick={onClose}
            className="text-[#9CA3AF] hover:text-[#F9FAFB] transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <p className="text-xs text-[#9CA3AF]">
            Configure strict discipline rules. If an order or trading pattern violates these settings,
            TradeZen raises warnings and real-time coaching alerts.
          </p>

          <div className="grid grid-cols-2 gap-3">
            {/* Max Trades / Day */}
            <div>
              <label className="block text-[11px] font-mono text-[#9CA3AF] mb-1">
                Max Trades / Day
              </label>
              <input
                type="number"
                min="1"
                max="50"
                value={formData.max_trades_per_day}
                onChange={(e) => handleChange('max_trades_per_day', e.target.value)}
                className="w-full bg-[#0E1116] text-[#F9FAFB] border border-[#2A313C] rounded px-3 py-1.5 text-xs font-mono focus:border-[#3B82F6] focus:outline-none"
              />
            </div>

            {/* Max Risk % / Trade */}
            <div>
              <label className="block text-[11px] font-mono text-[#9CA3AF] mb-1">
                Max Risk % / Trade
              </label>
              <input
                type="number"
                step="0.1"
                min="0.1"
                max="10"
                value={formData.max_risk_per_trade_pct}
                onChange={(e) => handleChange('max_risk_per_trade_pct', e.target.value)}
                className="w-full bg-[#0E1116] text-[#F9FAFB] border border-[#2A313C] rounded px-3 py-1.5 text-xs font-mono focus:border-[#3B82F6] focus:outline-none"
              />
            </div>

            {/* Max Consecutive Losses */}
            <div>
              <label className="block text-[11px] font-mono text-[#9CA3AF] mb-1">
                Max Consecutive Losses
              </label>
              <input
                type="number"
                min="1"
                max="10"
                value={formData.max_consecutive_losses}
                onChange={(e) => handleChange('max_consecutive_losses', e.target.value)}
                className="w-full bg-[#0E1116] text-[#F9FAFB] border border-[#2A313C] rounded px-3 py-1.5 text-xs font-mono focus:border-[#3B82F6] focus:outline-none"
              />
            </div>

            {/* Max Daily Loss (₹) */}
            <div>
              <label className="block text-[11px] font-mono text-[#9CA3AF] mb-1">
                Max Daily Loss (₹)
              </label>
              <input
                type="number"
                step="500"
                min="500"
                value={formData.max_daily_loss}
                onChange={(e) => handleChange('max_daily_loss', e.target.value)}
                className="w-full bg-[#0E1116] text-[#F9FAFB] border border-[#2A313C] rounded px-3 py-1.5 text-xs font-mono focus:border-[#3B82F6] focus:outline-none"
              />
            </div>

            {/* Intraday Cutoff Time */}
            <div>
              <label className="block text-[11px] font-mono text-[#9CA3AF] mb-1">
                Intraday Cutoff Time
              </label>
              <input
                type="text"
                value={formData.intraday_cutoff_time}
                onChange={(e) => handleChange('intraday_cutoff_time', e.target.value)}
                className="w-full bg-[#0E1116] text-[#F9FAFB] border border-[#2A313C] rounded px-3 py-1.5 text-xs font-mono focus:border-[#3B82F6] focus:outline-none"
                placeholder="15:15"
              />
            </div>

            {/* Require Stop Loss Checkbox */}
            <div className="flex items-center gap-2 pt-5">
              <input
                type="checkbox"
                id="require_sl"
                checked={formData.require_stop_loss}
                onChange={(e) => handleChange('require_stop_loss', e.target.checked)}
                className="w-4 h-4 rounded bg-[#0E1116] border-[#2A313C] text-[#3B82F6] focus:ring-[#3B82F6]"
              />
              <label htmlFor="require_sl" className="text-xs font-mono text-[#D1D5DB] cursor-pointer">
                Strict Mandatory Stop-Loss
              </label>
            </div>
          </div>

          {/* Messages */}
          {saveSuccess && (
            <div className="p-2 rounded bg-[#064E3B] border border-[#34D399]/40 text-xs text-[#34D399] flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4" />
              <span>Rules updated successfully!</span>
            </div>
          )}

          {saveError && (
            <div className="p-2 rounded bg-[#3A2E0F] border border-[#FBBF24]/40 text-xs text-[#FBBF24] flex items-center gap-2">
              <AlertCircle className="w-4 h-4" />
              <span>{saveError}</span>
            </div>
          )}

          {/* Footer actions */}
          <div className="flex items-center justify-between pt-3 border-t border-[#2A313C]">
            <button
              type="button"
              onClick={handleResetDefaults}
              className="flex items-center gap-1.5 text-xs text-[#9CA3AF] hover:text-[#F9FAFB] font-mono transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Reset Defaults</span>
            </button>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-3.5 py-1.5 rounded text-xs text-[#D1D5DB] bg-[#0E1116] border border-[#2A313C] hover:text-[#F9FAFB]"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSaving}
                className="px-4 py-1.5 rounded text-xs font-bold bg-[#3B82F6] hover:bg-[#60A5FA] text-[#F9FAFB] transition-all disabled:opacity-50"
              >
                {isSaving ? 'Saving...' : 'Save Rules'}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
