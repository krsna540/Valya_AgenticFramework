import { fetchEventSource } from "@microsoft/fetch-event-source";
import { API_BASE_URL, api, getToken } from "./client";
import type {
  Conversation,
  ConversationWithMessages,
  SiblingGroup,
  SseErrorEvent,
  SseSkillCallEvent,
  SseStreamCompleteEvent,
  SseStreamEndEvent,
  SseStreamStartEvent,
  SseTokenEvent,
  SseToolCallEvent,
} from "../types";

const API_PREFIX = "/api/v1";

export const chatApi = {
  listConversations: () => api.get<Conversation[]>("/chat/conversations"),
  createConversation: (agentId: string, secondaryAgentIds: string[] = [], title?: string, projectId?: string | null) =>
    api.post<Conversation>("/chat/conversations", {
      agent_id: agentId,
      secondary_agent_ids: secondaryAgentIds,
      title,
      project_id: projectId ?? null,
    }),
  getConversation: (id: string) => api.get<ConversationWithMessages>(`/chat/conversations/${id}`),
  getSiblings: (messageId: string) => api.get<SiblingGroup>(`/chat/messages/${messageId}/siblings`),
  selectBranch: (messageId: string, targetMessageId: string) =>
    api.patch<SiblingGroup>(`/chat/messages/${messageId}/select-branch`, { message_id: targetMessageId }),
  generateTitle: (conversationId: string) => api.post<{ title: string }>(`/chat/conversations/${conversationId}/title`),
};

export interface StreamMessageArgs {
  conversationId: string;
  content: string;
  fileIds?: string[];
  parentMessageId?: string | null;
  agentIds?: string[];
  /** Task-specific hook scope: extra hooks for just this one request. Not
   * currently surfaced in the UI — see README "What's intentionally simple". */
  hookIds?: string[];
}

export interface StreamHandlers {
  onStreamStart?: (e: SseStreamStartEvent) => void;
  onToken?: (e: SseTokenEvent) => void;
  onToolCall?: (e: SseToolCallEvent) => void;
  onSkillCall?: (e: SseSkillCallEvent) => void;
  onStreamEnd?: (e: SseStreamEndEvent) => void;
  onComplete?: (e: SseStreamCompleteEvent) => void;
  onStatus?: (e: { status: string; user_message_id: string }) => void;
  /** One agent's execution failed (caught server-side; other agents in a
   * split-screen turn are unaffected — see chat.py's per-agent isolation). */
  onAgentError?: (e: SseErrorEvent) => void;
  /** Network/transport-level failure of the SSE connection itself. */
  onError?: (err: unknown) => void;
}

/**
 * Streams a chat turn over SSE using fetch (not the native EventSource API)
 * because EventSource can't attach an Authorization header — see the
 * '@microsoft/fetch-event-source' dependency note in package.json.
 */
export async function streamMessage(args: StreamMessageArgs, handlers: StreamHandlers, signal?: AbortSignal): Promise<void> {
  const token = getToken();

  await fetchEventSource(
    `${API_BASE_URL}${API_PREFIX}/chat/conversations/${args.conversationId}/messages/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        content: args.content,
        file_ids: args.fileIds ?? [],
        parent_message_id: args.parentMessageId ?? null,
        agent_ids: args.agentIds ?? null,
        hook_ids: args.hookIds ?? [],
      }),
      signal,
      openWhenHidden: true,
      async onopen(response) {
        if (!response.ok) {
          throw new Error(`Stream failed to open: ${response.status}`);
        }
      },
      onmessage(ev) {
        if (!ev.data) return;
        const payload = JSON.parse(ev.data);
        switch (ev.event) {
          case "status":
            handlers.onStatus?.(payload);
            break;
          case "stream_start":
            handlers.onStreamStart?.(payload);
            break;
          case "token":
            handlers.onToken?.(payload);
            break;
          case "tool_call":
            handlers.onToolCall?.(payload);
            break;
          case "skill_call":
            handlers.onSkillCall?.(payload);
            break;
          case "stream_end":
            handlers.onStreamEnd?.(payload);
            break;
          case "stream_complete":
            handlers.onComplete?.(payload);
            break;
          case "error":
            handlers.onAgentError?.(payload);
            break;
          default:
            break;
        }
      },
      onerror(err) {
        handlers.onError?.(err);
        // Re-throwing stops fetch-event-source's automatic retry — a chat
        // stream shouldn't silently reconnect and duplicate tokens.
        throw err;
      },
    },
  );
}
