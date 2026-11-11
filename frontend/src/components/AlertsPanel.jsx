import React from 'react';
import {
  AlertTriangle,
  AlertOctagon,
  Info,
  CheckCircle,
  Bell,
  Trash2,
  Brain,
  ShieldAlert,
  Flame,
  Clock
} from 'lucide-react';

export default function AlertsPanel({
  alerts = [],
  onClearAlerts,
  onDismissAlert,
}) {
  const getSeverityBadge = (severity) => {
    switch (severity?.toUpperCase()) {
      case 'CRITICAL':
        return {
          icon: AlertOctagon,
          bg: 'bg-[#EF4444]/15',
          border: 'border-[#EF4444]/40',
          text: 'text-[#EF4444]',
          badgeBg: 'bg-[#EF4444]',
          badgeText: 'text-[#0E1116]',
        };
      case 'WARNING':
        return {
          icon: AlertTriangle,
          bg: 'bg-[#3A2E0F]',
          border: 'border-[#FBBF24]/40',
          text: 'text-[#FBBF24]',
          badgeBg: 'bg-[#FBBF24]',
          badgeText: 'text-[#0E1116]',
        };
      case 'INFO':
      default:
        return {
          icon: Info,
          bg: 'bg-[#1E3A5F]',
          border: 'border-[#3B82F6]/40',
          text: 'text-[#60A5FA]',
          badgeBg: 'bg-[#3B82F6]',
          badgeText: 'text-[#F9FAFB]',
        };
    }
  };

  return (
    <div className="bg-[#1A1F29] border border-[#2A313C] rounded-lg flex flex-col h-full max-h-[620px]">
      {/* Alerts Header */}
      <div className="p-3.5 border-b border-[#2A313C] bg-[#11161F] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell className="w-4 h-4 text-[#FBBF24]" />
          <h2 className="text-xs font-bold text-[#F9FAFB] uppercase tracking-wider">
            Behavioral Guardrails & Alerts
          </h2>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-[#0E1116] text-[#D1D5DB] border border-[#2A313C]">
            {alerts.length}
          </span>
        </div>

        {alerts.length > 0 && (
          <button
            onClick={onClearAlerts}
            title="Clear all alerts"
            className="flex items-center gap-1 text-[11px] font-mono text-[#9CA3AF] hover:text-[#F87171] transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>Clear</span>
          </button>
        )}
      </div>

      {/* Alerts Feed */}
      <div className="p-3 overflow-y-auto flex-1 flex flex-col gap-2.5">
        {alerts.length === 0 ? (
          <div className="flex flex-col items-center justify-center p-8 text-center text-[#9CA3AF]">
            <ShieldAlert className="w-8 h-8 text-[#2A313C] mb-2" />
            <p className="text-xs font-mono">No active warnings or rule violations.</p>
            <p className="text-[11px] text-[#9CA3AF]/70 mt-1">
              Violations, coaching alerts, and risk detections will stream here in real time.
            </p>
          </div>
        ) : (
          alerts.map((alert, idx) => {
            const styling = getSeverityBadge(alert.severity);
            const ruleName = alert.alert_type || alert.rule_type || 'RULE_VIOLATION';
            const IconComponent = ruleName === 'MODEL_RISK' ? Brain : styling.icon;
            const reasons = alert.context_json?.reasons || alert.metadata_json?.reasons || [];
            const timeStr = alert.created_at
              ? alert.created_at.includes('T')
                ? alert.created_at.split('T')[1].slice(0, 8)
                : alert.created_at.split(' ')[1] || alert.created_at
              : '';

            return (
              <div
                key={alert.id || idx}
                className={`${styling.bg} border ${styling.border} rounded-lg p-3 flex flex-col gap-1.5 transition-all relative group`}
              >
                {/* Header row */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <IconComponent className={`w-3.5 h-3.5 ${styling.text} shrink-0`} />
                    <span
                      className={`text-[10px] font-bold font-mono px-1.5 py-0.2 rounded uppercase ${styling.badgeBg} ${styling.badgeText}`}
                    >
                      {alert.severity || 'WARNING'}
                    </span>
                    <span className="text-xs font-bold font-mono text-[#F9FAFB]">
                      {ruleName}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-[#9CA3AF] flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {timeStr}
                    </span>
                    <button
                      onClick={() => onDismissAlert(alert.id || idx)}
                      className="opacity-0 group-hover:opacity-100 text-[#9CA3AF] hover:text-[#F9FAFB] transition-opacity text-xs"
                      title="Dismiss"
                    >
                      ×
                    </button>
                  </div>
                </div>

                {/* Message Body */}
                <p className="text-xs text-[#D1D5DB] leading-relaxed">
                  {alert.message}
                </p>

                {/* Structured Metadata / Coaching Reasons if available */}
                {reasons.length > 0 && (
                  <div className="mt-1 pt-1.5 border-t border-[#2A313C]/60 flex flex-col gap-1">
                    <span className="text-[10px] uppercase font-mono tracking-wider text-[#60A5FA]">
                      AI Coaching Rationale:
                    </span>
                    <div className="flex flex-wrap gap-1">
                      {reasons.map((r, rIdx) => (
                        <span
                          key={rIdx}
                          className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#0E1116] border border-[#2A313C] text-[#D1D5DB]"
                        >
                          {r}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
