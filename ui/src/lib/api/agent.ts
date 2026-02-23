import type {
  AgentSession,
  CreateSessionRequest,
  SendMessageRequest,
  SessionsListResponse,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const agentApi = {
  async createSession(
    request: CreateSessionRequest
  ): Promise<{ session_id: string }> {
    const response = await fetch(`${API_BASE}/api/v1/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`Failed to create session: ${response.statusText}`);
    }

    return response.json();
  },

  async listSessions(dbConnectionId?: string): Promise<SessionsListResponse> {
    const url = dbConnectionId
      ? `${API_BASE}/api/v1/sessions?db_connection_id=${encodeURIComponent(dbConnectionId)}`
      : `${API_BASE}/api/v1/sessions`;

    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch sessions: ${response.statusText}`);
    }

    return response.json();
  },

  async getSession(sessionId: string): Promise<AgentSession> {
    const response = await fetch(`${API_BASE}/api/v1/sessions/${sessionId}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch session: ${response.statusText}`);
    }

    return response.json();
  },

  async deleteSession(sessionId: string): Promise<void> {
    const response = await fetch(`${API_BASE}/api/v1/sessions/${sessionId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to delete session: ${response.statusText}`);
    }
  },

  async sendMessageStream(
    request: SendMessageRequest,
    onChunk: (chunk: string) => void
  ): Promise<void> {
    const response = await fetch(
      `${API_BASE}/api/v1/sessions/${request.session_id}/query/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify({ query: request.query }),
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to send message: ${response.statusText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body');
    }

    const decoder = new TextDecoder();

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        onChunk(chunk);
      }
    } finally {
      reader.releaseLock();
    }
  },

  streamTask(
    sessionId: string,
    query: string,
    onEvent: (event: import('./types').AgentEvent) => void,
    onError: (error: Error) => void,
    onComplete: () => void
  ): () => void {
    const controller = new AbortController();
    const streamUrl = `${API_BASE}/api/v1/sessions/${sessionId}/query/stream`;

    fetch(streamUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
      },
      body: JSON.stringify({ query }),
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Failed to stream task: ${response.statusText}`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error('No response body');
        }

        const decoder = new TextDecoder();
        let buffer = '';
        let currentEvent: { type?: string; data?: string } = {};

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) {
              onComplete();
              break;
            }

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
              const trimmedLine = line.trim();

              if (!trimmedLine) {
                // Empty line signals end of event
                if (currentEvent.type && currentEvent.data) {
                  try {
                    const eventData = JSON.parse(currentEvent.data);
                    // IMPORTANT: the SSE event name (currentEvent.type, e.g. "chunk") must
                    // always take precedence over any "type" field inside the JSON payload.
                    // Previously spreading eventData last let the payload's "type" field
                    // (e.g. "text", "sql") silently overwrite the SSE event name.
                    // We move the SSE type AFTER the spread so it wins, and we also
                    // expose the inner type as "chunk_type" for consumers that need it.
                    const innerType = eventData.type; // e.g. "text", "sql", "summary"
                    const agentEvent: import('./types').AgentEvent = {
                      ...eventData,
                      // Inner "type" (if present) becomes chunk_type; SSE event name is authoritative
                      ...(innerType ? { chunk_type: innerType } : {}),
                      type: currentEvent.type as import('./types').AgentEvent['type'],
                    };
                    onEvent(agentEvent);
                  } catch {
                    // Skip malformed event data
                  }
                }
                currentEvent = {};
                continue;
              }

              if (trimmedLine.startsWith('event:')) {
                currentEvent.type = trimmedLine.substring(6).trim();
              } else if (trimmedLine.startsWith('data:')) {
                currentEvent.data = trimmedLine.substring(5).trim();
              }
            }
          }
        } finally {
          reader.releaseLock();
        }
      })
      .catch((error) => {
        if (error.name !== 'AbortError') {
          onError(error);
        }
      });

    return () => controller.abort();
  },
};
