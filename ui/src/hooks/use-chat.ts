import { useCallback, useRef } from 'react';
import { useChatStore } from '@/stores/chat-store';
import { agentApi } from '@/lib/api/agent';


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
  } = useChatStore();

  const sendMessage = useCallback(
    async (content: string) => {
      // Get current state directly from store to avoid stale closure
      const storeState = useChatStore.getState();
      const { isStreaming: currentlyStreaming, connectionId: currentConnectionId } = storeState;

      // We only need a DB connection to perform comprehensive analysis, not a session.
      // But we still require one to be selected in the sidebar.
      if (!currentConnectionId || currentlyStreaming) {
        return;
      }

      addUserMessage(content);
      const assistantId = `assistant-${Date.now()}`;
      startAssistantMessage(assistantId);

      const controller = new AbortController();
      abortRef.current = () => controller.abort();

      try {
        updateProcessStatus(assistantId, "Analyzing your prompt and generating SQL...");

        const result = await agentApi.comprehensiveAnalysis(
          currentConnectionId,
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
