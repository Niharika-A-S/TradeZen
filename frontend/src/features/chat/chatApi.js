/**
 * Chatbot API client layer.
 * Reuses the application's base URL and token conventions.
 */

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function chatRequest(endpoint, options = {}) {
  const url = `${BASE_URL}${endpoint}`;
  const token = localStorage.getItem('tradezen_token');
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

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
      const text = await response.text();
      if (text) errorDetail = text;
    }
    const err = new Error(errorDetail);
    err.status = response.status;
    err.retryAfter = response.headers.get('Retry-After');
    throw err;
  }
  return await response.json();
}

export const chatApi = {
  sendMessage: (payload, signal) =>
    chatRequest('/api/chat', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    }),

  getHistory: (limit = 30) =>
    chatRequest(`/api/chat/history?limit=${limit}`),

  clearHistory: () =>
    chatRequest('/api/chat/history', {
      method: 'DELETE',
    }),

  saveNote: (text) =>
    chatRequest('/api/chat/notes', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),

  getNudges: (sinceIso) => {
    const query = sinceIso ? `?since=${encodeURIComponent(sinceIso)}` : '';
    return chatRequest(`/api/chat/nudges${query}`);
  },

  getHealth: () =>
    chatRequest('/api/chat/health'),
};
