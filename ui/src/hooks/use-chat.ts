import { useCallback, useRef, useEffect } from 'react';
import { useChatStore } from '@/stores/chat-store';
import { agentApi } from '@/lib/api/agent';
import type { AgentSession, SessionMessage } from '@/lib/api/types';


export function useChat() {
  const abortRef = useRef<(() => void) | null>(null);

  const {
    sessionId,
    connectionId,
    messages,
    currentTodos,
    isStreaming,
    setSession,
    addUserMessage,
    startAssistantMessage,
    appendToAssistantMessage,
    appendStructuredContent,
    updateProcessStatus,

    finishAssistantMessage,
    setStreaming,
    clearMessages,
    setMessages,
  } = useChatStore();

  useEffect(() => {
    if (!sessionId) {
      clearMessages();
      return;
    }

    let isMounted = true;
    agentApi.getSession(sessionId).then((session: AgentSession) => {
      if (!isMounted) return;

      const hydratedMessages = (session.messages || []).map((m: SessionMessage) => {
        if (m.role === 'human') {
          return {
            id: m.id,
            role: 'user' as const,
            content: m.query,
            timestamp: new Date(m.timestamp)
          };
        } else {
          return {
            id: m.id,
            role: 'assistant' as const,
            content: '',
            timestamp: new Date(m.timestamp),
            structured: {
              sql: m.sql || undefined,
              summary: m.analysis || undefined,
              insights: m.results_summary || undefined
            }
          };
        }
      });
      setMessages(hydratedMessages);
    }).catch(err => console.error("Failed to load session history", err));

    return () => { isMounted = false; };
  }, [sessionId, clearMessages, setMessages]);

  const sendMessage = useCallback(
    async (content: string) => {
      // Get current state directly from store to avoid stale closure
      const storeState = useChatStore.getState();
      const { isStreaming: currentlyStreaming, connectionId: currentConnectionId } = storeState;

      // We need a DB connection AND a Session to perform comprehensive analysis and save history.
      const currentSessionId = storeState.sessionId;
      if (!currentConnectionId || !currentSessionId || currentlyStreaming) {
        return;
      }

      addUserMessage(content);
      const assistantId = `assistant-${Date.now()}`;
      startAssistantMessage(assistantId);

      const controller = new AbortController();
      abortRef.current = () => controller.abort();

      try {
        updateProcessStatus(assistantId, "Analyzing your prompt and generating SQL...");

        const result = await agentApi.sessionComprehensiveAnalysis(
          currentSessionId,
          content,
          controller.signal
        );

        updateProcessStatus(assistantId, "Processing comprehensive analysis results...");

        // Process the result JSON into the structured content parts the UI expects
        if (result.sql) {
          appendStructuredContent(assistantId, 'sql', result.sql + '\n');
        }

        if (result.summary) {
          appendStructuredContent(assistantId, 'summary', result.summary + '\n');
        }

        if (result.insights && result.insights.length > 0) {
          const insightTexts = result.insights.map((i: { title: string; description: string; significance: string }) =>
            `**${i.title}**\n${i.description}\n*Significance: ${i.significance}*`
          ).join('\n\n');
          appendStructuredContent(assistantId, 'insights', insightTexts + '\n');
        }

        if (result.error) {
          appendToAssistantMessage(assistantId, `\n\nError: ${result.error}`);
        }

      } catch (error) {
        const err = error as Error;
        if (err.name !== 'AbortError') {
          appendToAssistantMessage(assistantId, `\n\nConnection error: ${err.message}`);
        }
      } finally {
        updateProcessStatus(assistantId, "Complete.");
        finishAssistantMessage(assistantId);
        abortRef.current = null;
      }
    },
    [
      addUserMessage,
      startAssistantMessage,
      appendToAssistantMessage,
      appendStructuredContent,
      updateProcessStatus,
      finishAssistantMessage,
    ]
  );

  const stopStreaming = useCallback(() => {
    if (abortRef.current) {
      abortRef.current();
      abortRef.current = null;
      setStreaming(false);
    }
  }, [setStreaming]);

  return {
    sessionId,
    connectionId,
    messages,
    currentTodos,
    isStreaming,
    setSession,
    sendMessage,
    stopStreaming,
    clearMessages,
  };
}
