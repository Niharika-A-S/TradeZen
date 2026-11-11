import React, { useState } from 'react';
import {
  Shield,
  Brain,
  TrendingUp,
  Sparkles,
  Lock,
  User,
  Mail,
  Eye,
  EyeOff,
  AlertCircle,
  CheckCircle2,
  ArrowRight,
  LogIn,
  UserPlus,
  PlayCircle,
  Zap,
  BarChart3
} from 'lucide-react';
import { api } from '../api';

export default function DynamicAuthPage({ onAuthSuccess }) {
  const [isLogin, setIsLogin] = useState(true);
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);

    const cleanUser = username.trim();
    if (!cleanUser) {
      setError('Please enter a username.');
      return;
    }

    if (!isLogin && password !== confirmPassword) {
      setError('Passwords do not match. Please verify your password.');
      return;
    }

    if (password.length < 6) {
      setError('Password must be at least 6 characters.');
      return;
    }

    setLoading(true);
    try {
      let data;
      if (isLogin) {
        data = await api.login({ username: cleanUser, password });
      } else {
        data = await api.signup({
          username: cleanUser,
          email: email.trim() || undefined,
          password
        });
      }

      if (data.access_token) {
        localStorage.setItem('tradezen_token', data.access_token);
        localStorage.setItem('tradezen_user', JSON.stringify(data.user));
        if (onAuthSuccess) {
          onAuthSuccess(data.user, data.account);
        }
      }
    } catch (err) {
      setError(err.message || 'Authentication failed. Please verify credentials.');
    } finally {
      setLoading(false);
    }
  };

  // Instant 1-click Demo Trader login
  const handleQuickDemo = async () => {
    setError(null);
    setLoading(true);
    try {
      // Login with default demo user or create a temporary guest
      const data = await api.login({ username: 'default_trader', password: 'Password123!' });
      if (data.access_token) {
        localStorage.setItem('tradezen_token', data.access_token);
        localStorage.setItem('tradezen_user', JSON.stringify(data.user));
        if (onAuthSuccess) {
          onAuthSuccess(data.user, data.account);
        }
      }
    } catch {
      // If default demo password differs, signup a quick trader session
      try {
        const guestName = `trader_${Math.floor(1000 + Math.random() * 9000)}`;
        const data = await api.signup({
          username: guestName,
          email: `${guestName}@tradezen.local`,
          password: 'Password123!'
        });
        if (data.access_token) {
          localStorage.setItem('tradezen_token', data.access_token);
          localStorage.setItem('tradezen_user', JSON.stringify(data.user));
          if (onAuthSuccess) {
            onAuthSuccess(data.user, data.account);
          }
        }
      } catch (err2) {
        setError(err2.message || 'Unable to start instant demo.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen bg-[#0E1116] text-[#F9FAFB] flex flex-col justify-between overflow-hidden selection:bg-[#3B82F6] selection:text-white font-sans">
      {/* Background Animated Gradient Aura */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        {/* Blue Top-Left Glow */}
        <div className="absolute -top-32 -left-32 w-96 h-96 bg-[#3B82F6]/15 rounded-full blur-3xl animate-pulse" />
        {/* Emerald Bottom-Right Glow */}
        <div className="absolute -bottom-32 -right-32 w-96 h-96 bg-[#34D399]/10 rounded-full blur-3xl animate-pulse" style={{ animationDuration: '6s' }} />
        {/* Navy Center Aura */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[700px] h-[700px] bg-[#1E3A5F]/20 rounded-full blur-[140px] pointer-events-none" />
        {/* Subtle dynamic grid pattern */}
        <div
          className="absolute inset-0 opacity-[0.035]"
          style={{
            backgroundImage: `radial-gradient(#F9FAFB 1px, transparent 1px)`,
            backgroundSize: '24px 24px',
          }}
        />
      </div>

      {/* Top Header / Brand Bar */}
      <header className="relative z-10 px-6 py-4 flex items-center justify-between border-b border-[#2A313C]/60 bg-[#11161F]/60 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#1E3A5F] to-[#0E1116] border border-[#3B82F6]/40 flex items-center justify-center shadow-lg shadow-[#3B82F6]/10">
            <span className="text-[#3B82F6] font-extrabold text-xl tracking-wider">TZ</span>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xl font-extrabold tracking-tight text-[#F9FAFB]">TradeZen</span>
              <span className="px-2 py-0.5 text-[10px] font-bold tracking-wider uppercase rounded-full bg-[#1E3A5F] text-[#60A5FA] border border-[#3B82F6]/30">
                v1.0
              </span>
            </div>
            <p className="text-[11px] text-[#9CA3AF]">AI Behavioral Guardrails & Simulation</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="hidden sm:flex items-center gap-2 px-3 py-1 rounded-full bg-[#1A1F29]/80 border border-[#2A313C] text-xs text-[#9CA3AF]">
            <span className="w-2 h-2 rounded-full bg-[#34D399] animate-ping" />
            <span className="text-[#34D399] font-medium">Platform Ready</span>
          </div>
          <button
            onClick={handleQuickDemo}
            disabled={loading}
            className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-[#1E3A5F] text-[#60A5FA] border border-[#3B82F6]/40 hover:bg-[#3B82F6] hover:text-white transition-all shadow-sm"
          >
            <Zap className="w-3.5 h-3.5 text-[#FBBF24]" />
            <span>Instant Demo</span>
          </button>
        </div>
      </header>

      {/* Main Hero & Auth Container */}
      <main className="relative z-10 flex-1 max-w-6xl w-full mx-auto px-4 py-8 lg:py-12 flex flex-col lg:flex-row items-center justify-center gap-10 lg:gap-14">
        {/* Left Column: Dynamic Value Proposition & Feature Badges */}
        <div className="flex-1 space-y-6 text-center lg:text-left max-w-xl">
          <div className="inline-flex items-center gap-2 px-3.5 py-1 rounded-full bg-[#1E3A5F]/70 border border-[#3B82F6]/30 text-xs font-medium text-[#60A5FA]">
            <Sparkles className="w-3.5 h-3.5 text-[#34D399]" />
            <span>Integrated 3-in-1 Trader Psychology System</span>
          </div>

          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight text-[#F9FAFB] leading-tight">
            Trade with <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#60A5FA] via-[#3B82F6] to-[#34D399]">Discipline</span>, Not Emotion.
          </h2>

          <p className="text-sm sm:text-base text-[#9CA3AF] leading-relaxed">
            TradeZen combines real-time paper execution, AI behavioral coaching, and historical scenario training to eliminate revenge trading, FOMO, and undisciplined risk.
          </p>

          {/* Interactive Feature Pills */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
            <div className="p-3.5 rounded-xl bg-[#11161F]/80 border border-[#2A313C] flex items-start gap-3 hover:border-[#3B82F6]/40 transition-colors group">
              <div className="p-2 rounded-lg bg-[#1E3A5F] text-[#60A5FA] group-hover:scale-105 transition-transform">
                <TrendingUp className="w-4 h-4" />
              </div>
              <div className="text-left">
                <h4 className="text-xs font-bold text-[#F9FAFB]">₹10 Lakhs Virtual Capital</h4>
                <p className="text-[11px] text-[#9CA3AF]">Zero-risk live market paper orders with realistic slippage.</p>
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-[#11161F]/80 border border-[#2A313C] flex items-start gap-3 hover:border-[#3B82F6]/40 transition-colors group">
              <div className="p-2 rounded-lg bg-[#064E3B] text-[#34D399] group-hover:scale-105 transition-transform">
                <Brain className="w-4 h-4" />
              </div>
              <div className="text-left">
                <h4 className="text-xs font-bold text-[#F9FAFB]">XGBoost Risk Scanner</h4>
                <p className="text-[11px] text-[#9CA3AF]">Detects revenge trading and oversize sizing before execution.</p>
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-[#11161F]/80 border border-[#2A313C] flex items-start gap-3 hover:border-[#3B82F6]/40 transition-colors group">
              <div className="p-2 rounded-lg bg-[#3A2E0F] text-[#FBBF24] group-hover:scale-105 transition-transform">
                <BarChart3 className="w-4 h-4" />
              </div>
              <div className="text-left">
                <h4 className="text-xs font-bold text-[#F9FAFB]">Scenario Simulation</h4>
                <p className="text-[11px] text-[#9CA3AF]">Blind replay practice on crash and breakout chart patterns.</p>
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-[#11161F]/80 border border-[#2A313C] flex items-start gap-3 hover:border-[#3B82F6]/40 transition-colors group">
              <div className="p-2 rounded-lg bg-[#1E3A5F] text-[#60A5FA] group-hover:scale-105 transition-transform">
                <Shield className="w-4 h-4" />
              </div>
              <div className="text-left">
                <h4 className="text-xs font-bold text-[#F9FAFB]">RAG-Engine Coach</h4>
                <p className="text-[11px] text-[#9CA3AF]">SEBI investor education & instant behavioral guidance.</p>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Dynamic Login / Signup Card */}
        <div className="w-full max-w-md">
          <div className="relative rounded-2xl p-[1px] bg-gradient-to-b from-[#3B82F6]/40 via-[#2A313C] to-[#1E3A5F]/40 shadow-2xl shadow-black/80">
            <div className="rounded-2xl bg-[#11161F]/95 backdrop-blur-xl p-6 sm:p-8 space-y-6">
              {/* Card Header & Tab Switcher */}
              <div className="space-y-4">
                <div className="flex rounded-xl bg-[#0E1116] p-1 border border-[#2A313C]">
                  <button
                    type="button"
                    onClick={() => {
                      setIsLogin(true);
                      setError(null);
                    }}
                    className={`flex-1 py-2 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1.5 ${
                      isLogin
                        ? 'bg-[#1E3A5F] text-[#60A5FA] shadow-sm border border-[#3B82F6]/30'
                        : 'text-[#9CA3AF] hover:text-[#F9FAFB]'
                    }`}
                  >
                    <LogIn className="w-3.5 h-3.5" />
                    <span>Sign In</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setIsLogin(false);
                      setError(null);
                    }}
                    className={`flex-1 py-2 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1.5 ${
                      !isLogin
                        ? 'bg-[#1E3A5F] text-[#34D399] shadow-sm border border-[#34D399]/30'
                        : 'text-[#9CA3AF] hover:text-[#F9FAFB]'
                    }`}
                  >
                    <UserPlus className="w-3.5 h-3.5" />
                    <span>Create Account</span>
                  </button>
                </div>

                <div className="text-center">
                  <h3 className="text-lg font-bold text-[#F9FAFB]">
                    {isLogin ? 'Welcome Back to TradeZen' : 'Start Your Trading Journey'}
                  </h3>
                  <p className="text-xs text-[#9CA3AF]">
                    {isLogin
                      ? 'Sign in to access your portfolio, history & coach'
                      : 'Create your account to unlock ₹10L simulated capital'}
                  </p>
                </div>
              </div>

              {/* Error Banner */}
              {error && (
                <div className="p-3 bg-[#EF4444]/15 border border-[#EF4444]/30 rounded-xl flex items-start gap-2.5 text-xs text-[#FCA5A5] animate-shake">
                  <AlertCircle className="w-4 h-4 text-[#EF4444] shrink-0 mt-0.5" />
                  <span>{error}</span>
                </div>
              )}

              {/* Auth Form */}
              <form onSubmit={handleSubmit} className="space-y-4 text-left">
                {/* Username */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-[#D1D5DB]">Username</label>
                  <div className="relative">
                    <User className="w-4 h-4 text-[#9CA3AF] absolute left-3.5 top-3" />
                    <input
                      type="text"
                      required
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder="e.g. rahul_trader"
                      className="w-full bg-[#0E1116] border border-[#2A313C] rounded-xl pl-10 pr-3.5 py-2.5 text-xs text-[#F9FAFB] placeholder-[#6B7280] focus:outline-none focus:border-[#3B82F6] focus:ring-1 focus:ring-[#3B82F6] transition-all"
                    />
                  </div>
                </div>

                {/* Email (Optional for Signup) */}
                {!isLogin && (
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-[#D1D5DB]">
                      Email Address <span className="text-[#6B7280] font-normal">(optional)</span>
                    </label>
                    <div className="relative">
                      <Mail className="w-4 h-4 text-[#9CA3AF] absolute left-3.5 top-3" />
                      <input
                        type="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="trader@example.com"
                        className="w-full bg-[#0E1116] border border-[#2A313C] rounded-xl pl-10 pr-3.5 py-2.5 text-xs text-[#F9FAFB] placeholder-[#6B7280] focus:outline-none focus:border-[#3B82F6] focus:ring-1 focus:ring-[#3B82F6] transition-all"
                      />
                    </div>
                  </div>
                )}

                {/* Password */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-[#D1D5DB]">Password</label>
                  <div className="relative">
                    <Lock className="w-4 h-4 text-[#9CA3AF] absolute left-3.5 top-3" />
                    <input
                      type={showPassword ? 'text' : 'password'}
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••"
                      className="w-full bg-[#0E1116] border border-[#2A313C] rounded-xl pl-10 pr-10 py-2.5 text-xs text-[#F9FAFB] placeholder-[#6B7280] focus:outline-none focus:border-[#3B82F6] focus:ring-1 focus:ring-[#3B82F6] transition-all"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-2.5 text-[#9CA3AF] hover:text-[#F9FAFB] transition-colors"
                    >
                      {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                {/* Confirm Password for Signup */}
                {!isLogin && (
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-[#D1D5DB]">Confirm Password</label>
                    <div className="relative">
                      <Lock className="w-4 h-4 text-[#9CA3AF] absolute left-3.5 top-3" />
                      <input
                        type={showPassword ? 'text' : 'password'}
                        required
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        placeholder="••••••••"
                        className="w-full bg-[#0E1116] border border-[#2A313C] rounded-xl pl-10 pr-3.5 py-2.5 text-xs text-[#F9FAFB] placeholder-[#6B7280] focus:outline-none focus:border-[#3B82F6] focus:ring-1 focus:ring-[#3B82F6] transition-all"
                      />
                    </div>
                  </div>
                )}

                {/* Submit Action */}
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full py-3 rounded-xl bg-gradient-to-r from-[#2563EB] to-[#1D4ED8] hover:from-[#3B82F6] hover:to-[#2563EB] text-white text-xs font-bold tracking-wide transition-all shadow-lg shadow-[#2563EB]/25 flex items-center justify-center gap-2 disabled:opacity-50 mt-2"
                >
                  {loading ? (
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  ) : (
                    <>
                      <span>{isLogin ? 'Sign In to Workspace' : 'Create Account & Claim ₹10L'}</span>
                      <ArrowRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              </form>

              {/* Divider & One-Click Demo Option */}
              <div className="relative flex items-center justify-center pt-2">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-[#2A313C]" />
                </div>
                <span className="relative bg-[#11161F] px-3 text-[11px] text-[#9CA3AF] uppercase tracking-wider">
                  Or Test Instantly
                </span>
              </div>

              <button
                type="button"
                onClick={handleQuickDemo}
                disabled={loading}
                className="w-full py-2.5 rounded-xl bg-[#1A1F29] border border-[#2A313C] hover:border-[#3B82F6]/40 text-[#D1D5DB] hover:text-white text-xs font-semibold flex items-center justify-center gap-2 transition-all"
              >
                <PlayCircle className="w-4 h-4 text-[#34D399]" />
                <span>Launch Instant Demo Session</span>
              </button>
            </div>
          </div>
        </div>
      </main>

      {/* Footer Disclaimer */}
      <footer className="relative z-10 px-6 py-3 border-t border-[#2A313C]/60 bg-[#11161F]/40 backdrop-blur-sm text-center text-xs text-[#9CA3AF]">
        <span>
          <strong className="text-[#D1D5DB]">SEBI Compliance Notice:</strong> TradeZen is an educational & behavioral coaching simulation platform. Virtual simulated paper capital only. No real money or investment advice.
        </span>
      </footer>
    </div>
  );
}
