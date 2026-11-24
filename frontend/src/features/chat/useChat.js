import React, { useState, useEffect, useRef, useCallback } from 'react';
import { chatApi } from './chatApi';

export function useChat() {
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [errorBanner, setErrorBanner] = useState(null); // { message, isRateLimit, retryAfter }
  const [unreadNudgesCount, setUnreadNudgesCount] = useState(0);
  const [rateLimitTimeLeft, setRateLimitTimeLeft] = useState(0);
  const [lastMessageSent, setLastMessageSent] = useState(null);

  const abortControllerRef = useRef(null);
  const seenNudgeIdsRef = useRef(new Set());
  const failureCountRef = useRef(0);

  // Load chat history
  const loadHistory = useCallback(async () => {
    try {
      const history = await chatApi.getHistory(30);
      setMessages(history);
    } catch (err) {
      console.warn('Could not load chat history:', err.message);
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  // Rate-limit countdown ticker
  useEffect(() => {
    if (rateLimitTimeLeft <= 0) return;
    const interval = setInterval(() => {
      setRateLimitTimeLeft((prev) => {
        if (prev <= 1) {
          setErrorBanner(null);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [rateLimitTimeLeft]);

  // Nudges polling every 20 seconds while visible
  useEffect(() => {
    let timerId = null;

    const pollNudges = async () => {
      if (document.hidden || failureCountRef.current >= 5) return;

      try {
        const sinceIso = new Date(Date.now() - 15 * 60 * 1000).toISOString();
        const nudges = await chatApi.getNudges(sinceIso);
        failureCountRef.current = 0;

        if (Array.isArray(nudges) && nudges.length > 0) {
          const newNudges = [];
          for (const n of nudges) {
            if (!seenNudgeIdsRef.current.has(n.id)) {
              seenNudgeIdsRef.current.add(n.id);
              newNudges.push({
                id: n.id,
                role: 'assistant',
                content: n.message,
                created_at: n.created_at,
                isNudge: true,
              });
            }
          }
          if (newNudges.length > 0) {
            setMessages((prev) => [...prev, ...newNudges]);
            setUnreadNudgesCount((prev) => prev + newNudges.length);
          }
        }
      } catch (e) {
        failureCountRef.current += 1;
        console.warn(`Nudge poll error (${failureCountRef.current}/5):`, e.message);
      }
    };

    const scheduleNext = () => {
      const delay = Math.min(20000 * Math.pow(1.5, failureCountRef.current), 120000);
      timerId = setTimeout(async () => {
        await pollNudges();
        if (failureCountRef.current < 5) scheduleNext();
      }, delay);
    };

    scheduleNext();

    return () => {
      if (timerId) clearTimeout(timerId);
    };
  }, []);

  const sendMessage = useCallback(
    async (text) => {
      if (!text || rateLimitTimeLeft > 0 || isLoading) return;

      if (!navigator.onLine) {
        setErrorBanner({ message: 'You are currently offline. Check your internet connection.' });
        return;
      }

      setErrorBanner(null);
      setIsLoading(true);
      setLastMessageSent(text);

      const clientMsgId = `cmsg_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
      const userMsg = {
        role: 'user',
        content: text,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);

      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      abortControllerRef.current = new AbortController();
      const timeoutId = setTimeout(() => {
        if (abortControllerRef.current) abortControllerRef.current.abort();
      }, 30000);

      try {
        const res = await chatApi.sendMessage(
          {
            message: text,
            client_message_id: clientMsgId,
          },
          abortControllerRef.current.signal
        );
        clearTimeout(timeoutId);

        const botMsg = {
          role: 'assistant',
          content: res.reply,
          route: res.route,
          sources: res.sources,
          used_data: res.used_data,
          degraded: res.degraded,
          degraded_reason: res.degraded_reason,
          no_data: res.no_data,
          created_at: res.created_at || new Date().toISOString(),
        };
        setMessages((prev) => [...prev, botMsg]);
      } catch (err) {
        clearTimeout(timeoutId);
        if (err.name === 'AbortError') {
          setErrorBanner({ message: 'Request timed out. Please try again.' });
          return;
        }

        if (err.status === 429) {
          const retrySec = parseInt(err.retryAfter || '10', 10);
          setRateLimitTimeLeft(retrySec);
          setErrorBanner({
            message: `Slow down a little. You can send again in ${retrySec}s.`,
            isRateLimit: true,
          });
        } else if (err.status === 401) {
          localStorage.removeItem('tradezen_token');
          localStorage.removeItem('tradezen_user');
          window.location.reload();
        } else {
          setErrorBanner({ message: err.message || 'Error communicating with Coach.' });
        }
      } finally {
        setIsLoading(false);
      }
    },
    [isLoading, rateLimitTimeLeft]
  );

  const clearHistory = useCallback(async () => {
    try {
      await chatApi.clearHistory();
      setMessages([]);
    } catch (err) {
      console.warn('Failed to clear history:', err.message);
    }
  }, []);

  const saveNote = useCallback(async (noteText) => {
    if (!noteText.trim()) return false;
    try {
      await chatApi.saveNote(noteText.trim());
      return true;
    } catch (err) {
      console.warn('Failed to save note:', err.message);
      return false;
    }
  }, []);

  const resetUnreadNudges = useCallback(() => {
    setUnreadNudgesCount(0);
  }, []);

  return {
    messages,
    isLoading,
    errorBanner,
    unreadNudgesCount,
    rateLimitTimeLeft,
    lastMessageSent,
    sendMessage,
    clearHistory,
    saveNote,
    resetUnreadNudges,
    retryLastMessage: () => lastMessageSent && sendMessage(lastMessageSent),
  };
}
