import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from './api';

const WS_BASE_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000';

export function useAlerts(userId = 1) {
  const [alerts, setAlerts] = useState([]);
  const [status, setStatus] = useState('disconnected'); // 'connected' | 'disconnected' | 'reconnecting'
  const [latestAlert, setLatestAlert] = useState(null);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const backoffDelayRef = useRef(2000);

  // Load existing alerts from REST API on mount or user change
  useEffect(() => {
    let isMounted = true;
    api.getAlerts(userId, 50)
      .then((data) => {
        if (isMounted && Array.isArray(data)) {
          setAlerts(data);
        }
      })
      .catch((err) => console.warn('Failed to fetch initial alerts:', err));

    return () => {
      isMounted = false;
    };
  }, [userId]);

  const connect = useCallback(() => {
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const wsUrl = `${WS_BASE_URL}/ws/alerts/${userId}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus('connected');
      backoffDelayRef.current = 2000;
    };

    ws.onmessage = (event) => {
      // Ignore heartbeat pong messages
      if (typeof event.data === 'string' && event.data.trim() === 'pong') {
        return;
      }

      try {
        const data = JSON.parse(event.data);
        setAlerts((prev) => {
          // Avoid duplicate alerts if received
          if (prev.some((a) => a.id && data.id && a.id === data.id)) {
            return prev;
          }
          return [data, ...prev];
        });
        setLatestAlert(data);
      } catch (e) {
        console.warn('Could not parse WebSocket message:', event.data, e);
      }
    };

    ws.onclose = () => {
      setStatus('disconnected');
      wsRef.current = null;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      const delay = backoffDelayRef.current;
      backoffDelayRef.current = Math.min(Math.round(delay * 1.5), 10000);
      reconnectTimeoutRef.current = setTimeout(() => {
        setStatus('reconnecting');
        connect();
      }, delay);
    };

    ws.onerror = () => {
      // Browser triggers onclose automatically upon connection errors.
      // If socket is still open, close cleanly.
      try {
        if (ws.readyState === WebSocket.OPEN) {
          ws.close();
        }
      } catch {
        // safe ignore
      }
    };
  }, [userId]);

  useEffect(() => {
    connect();

    // Heartbeat ping every 25 seconds
    const pingInterval = setInterval(() => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping');
      }
    }, 25000);

    return () => {
      clearInterval(pingInterval);
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  const clearAlerts = () => setAlerts([]);
  const dismissAlert = (indexOrId) => {
    setAlerts((prev) => prev.filter((a, idx) => a.id !== indexOrId && idx !== indexOrId));
  };

  return {
    alerts,
    status,
    latestAlert,
    clearAlerts,
    dismissAlert,
  };
}
