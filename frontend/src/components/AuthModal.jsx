import React, { useState } from 'react';
import { X, Lock, User, Mail, AlertCircle, LogIn, UserPlus } from 'lucide-react';
import { api } from '../api';

export default function AuthModal({ isOpen, onClose, onAuthSuccess }) {
  const [isLogin, setIsLogin] = useState(true);
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      let data;
      if (isLogin) {
        data = await api.login({ username: username.trim(), password });
      } else {
        data = await api.signup({
          username: username.trim(),
          email: email.trim() || undefined,
          password
        });
      }

      // Store JWT token and user info
      if (data.access_token) {
        localStorage.setItem('tradezen_token', data.access_token);
        localStorage.setItem('tradezen_user', JSON.stringify(data.user));
        if (onAuthSuccess) {
          onAuthSuccess(data.user, data.account);
        }
        onClose();
      }
    } catch (err) {
      setError(err.message || 'Authentication failed. Please check your credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
      <div className="bg-[#11161F] border border-[#2A313C] rounded-xl w-full max-w-md overflow-hidden shadow-2xl">
        {/* Modal Header */}
        <div className="px-6 py-4 border-b border-[#2A313C] flex items-center justify-between bg-[#1A1F29]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#1E3A5F] flex items-center justify-center">
              {isLogin ? (
                <LogIn className="w-4 h-4 text-[#60A5FA]" />
              ) : (
                <UserPlus className="w-4 h-4 text-[#34D399]" />
              )}
            </div>
            <div>
              <h2 className="text-base font-bold text-[#F9FAFB]">
                {isLogin ? 'Sign In to TradeZen' : 'Create TradeZen Account'}
              </h2>
              <p className="text-xs text-[#9CA3AF]">
                {isLogin
                  ? 'Access your personal paper portfolio & coaching rules'
                  : 'Get ₹10 Lakhs fake cash & personal AI guardrails'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-[#9CA3AF] hover:text-[#F9FAFB] hover:bg-[#2A313C] transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="p-3 bg-[#EF4444]/10 border border-[#EF4444]/30 rounded-lg flex items-start gap-2 text-xs text-[#FCA5A5]">
              <AlertCircle className="w-4 h-4 text-[#EF4444] shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-[#D1D5DB] mb-1">Username</label>
            <div className="relative">
              <User className="w-4 h-4 text-[#9CA3AF] absolute left-3 top-2.5" />
              <input
                type="text"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="e.g. rahul_trader"
                className="w-full bg-[#0E1116] border border-[#2A313C] rounded-lg pl-9 pr-3 py-2 text-sm text-[#F9FAFB] focus:outline-none focus:border-[#3B82F6]"
              />
            </div>
          </div>

          {!isLogin && (
            <div>
              <label className="block text-xs font-medium text-[#D1D5DB] mb-1">Email (Optional)</label>
              <div className="relative">
                <Mail className="w-4 h-4 text-[#9CA3AF] absolute left-3 top-2.5" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@example.com"
                  className="w-full bg-[#0E1116] border border-[#2A313C] rounded-lg pl-9 pr-3 py-2 text-sm text-[#F9FAFB] focus:outline-none focus:border-[#3B82F6]"
                />
              </div>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-[#D1D5DB] mb-1">Password</label>
            <div className="relative">
              <Lock className="w-4 h-4 text-[#9CA3AF] absolute left-3 top-2.5" />
              <input
                type="password"
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 6 characters"
                className="w-full bg-[#0E1116] border border-[#2A313C] rounded-lg pl-9 pr-3 py-2 text-sm text-[#F9FAFB] focus:outline-none focus:border-[#3B82F6]"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 mt-2 bg-[#2563EB] hover:bg-[#1D4ED8] disabled:opacity-50 text-white font-medium text-sm rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            {loading ? (
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : isLogin ? (
              <>
                <LogIn className="w-4 h-4" />
                <span>Sign In</span>
              </>
            ) : (
              <>
                <UserPlus className="w-4 h-4" />
                <span>Create Account (₹10L Cash)</span>
              </>
            )}
          </button>

          <div className="text-center pt-2 border-t border-[#2A313C]">
            <button
              type="button"
              onClick={() => {
                setIsLogin(!isLogin);
                setError(null);
              }}
              className="text-xs text-[#60A5FA] hover:underline"
            >
              {isLogin
                ? "Don't have an account? Sign up with 10L cash"
                : 'Already have an account? Sign in'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
