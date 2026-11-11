/**
 * TradeZen API Client
 * Connects to the FastAPI backend with comprehensive error handling.
 */

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function request(endpoint, options = {}) {
  const url = `${BASE_URL}${endpoint}`;
  const token = localStorage.getItem('tradezen_token');
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  try {
    const response = await fetch(url, { ...options, headers });
    if (!response.ok) {
      let errorDetail = `HTTP ${response.status}: ${response.statusText}`;
      try {
        const errorJson = await response.json();
        if (errorJson.detail) {
          errorDetail = typeof errorJson.detail === 'string'
            ? errorJson.detail
            : JSON.stringify(errorJson.detail);
        }
      } catch {
        // Fallback to response text
        const text = await response.text();
        if (text) errorDetail = text;
      }
      throw new Error(errorDetail);
    }
    return await response.json();
  } catch (error) {
    if (error.name === 'TypeError' && String(error.message || '').toLowerCase().includes('fetch')) {
      const connError = new Error(
        `Cannot connect to TradeZen backend at ${BASE_URL}. Please ensure the backend is running on port 8000 (e.g. run 'run.bat' or 'uvicorn app.api.main:app --reload') and PostgreSQL is active.`
      );
      console.error(`API Error on ${endpoint}:`, connError);
      throw connError;
    }
    console.error(`API Error on ${endpoint}:`, error);
    throw error;
  }
}

export const api = {
  // Authentication
  signup: (payload) => request('/auth/signup', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  login: (payload) => request('/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  getMe: () => request('/auth/me'),

  // Clock / Replay
  getClock: () => request('/clock'),
  tickClock: (minutes = 1) => request('/clock/tick', {
    method: 'POST',
    body: JSON.stringify({ minutes }),
  }),
  setClockMode: (payload) => request('/clock/mode', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),

  // Market Data
  getSymbols: () => request('/market/symbols'),
  getPrice: (symbol) => request(`/price?symbol=${encodeURIComponent(symbol)}`),
  getBars: (symbol, startTime, endTime, limit = 500) => {
    const params = new URLSearchParams({
      symbol,
      start_time: startTime,
      end_time: endTime,
      limit: limit.toString(),
    });
    return request(`/bars?${params.toString()}`);
  },

  // Paper Trading
  getAccount: (userId = 1) => request(`/paper/account?user_id=${userId}`),
  getPositions: (userId = 1, openOnly = true) =>
    request(`/paper/positions?user_id=${userId}&open_only=${openOnly}`),
  getTrades: (userId = 1, symbol = null) => {
    const url = symbol
      ? `/paper/trades?user_id=${userId}&symbol=${encodeURIComponent(symbol)}`
      : `/paper/trades?user_id=${userId}`;
    return request(url);
  },
  preCheckOrder: (orderPayload) => request('/paper/orders/pre-check', {
    method: 'POST',
    body: JSON.stringify(orderPayload),
  }),
  placeOrder: (orderPayload) => request('/paper/orders', {
    method: 'POST',
    body: JSON.stringify(orderPayload),
  }),
  cancelOrder: (orderId, userId = 1) => request(`/paper/orders/${orderId}?user_id=${userId}`, {
    method: 'DELETE',
  }),
  squareOff: (userId = 1) => request(`/paper/square-off?user_id=${userId}`, {
    method: 'POST',
  }),

  // Behavioral Rules & ML Coaching
  getRules: (userId = 1) => request(`/rules/${userId}`),
  getCurrentRules: (userId = 1) => request(`/rules/${userId}`),
  updateRules: (userId = 1, rules) => request(`/rules/${userId}`, {
    method: 'PUT',
    body: JSON.stringify(rules),
  }),
  setRules: (rules, userId = 1) => request(`/rules/${userId}`, {
    method: 'PUT',
    body: JSON.stringify(rules),
  }),
  getAlerts: (userId = 1, limit = 100) => request(`/alerts/${userId}?limit=${limit}`),
  predictRisk: (userId = 1) => request('/paper/risk/predict', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, create_alert: true }),
  }),

  // Scenario Simulation & Behavioral Practice
  getNextScenarios: (limit = 15) => request(`/api/v1/scenarios/next?limit=${limit}`),
  getReveal: (scenarioId) => request(`/api/v1/scenarios/${scenarioId}/reveal`),
  submitDecision: (data) => request('/api/v1/decisions', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  ratePrediction: (predictionId, feedbackCorrect) => request(`/api/v1/predictions/${predictionId}/feedback`, {
    method: 'POST',
    body: JSON.stringify({ feedback_correct: feedbackCorrect }),
  }),
  restartProgress: () => request('/api/v1/progress/restart', { method: 'POST' }),
  getDashboard: () => request('/api/v1/progress/dashboard'),
  getDataHealth: () => request('/api/v1/admin/data-health'),
};
