import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiError } from "../../api/client";
import { chatApi, streamMessage } from "../../api/chat";
import { runsApi, type RunSummary } from "../../api/runs";
import type { Conversation, Message } from "../../types";

// Matches user-app.html's "Workspace" screen (side list + thread + composer
// + right panel). A real, streaming chat surface — reuses the same
// chatApi/streamMessage the full ChatPage.tsx uses, just with the simpler
// bubble-thread UX the mockup actually shows (no branch nav, no citation
// drawer — those are real ChatPage features this screen deliberately
// doesn't need to replicate to match the mockup).
//
// "Plan"/"Goal"/"Done when" in the mockup are a fabricated per-project
// planning model this backend doesn't have a matching resource for (a
// Conversation has a title, not a goal+criteria+step list). Rather than
// invent that data, the right panel shows what's real instead: the
// conversation title as the goal line, and any of this tenant's runs that
// are genuinely waiting on a human decision, wired to the real
// runs.decide() endpoint — same approval flow as the Admin Overview page.
export default function WorkspacePage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const [approvals, setApprovals] = useState<RunSummary[]>([]);
  const threadEndRef = useRef<HTMLDivElement>(null);
  const autoSentRef = useRef<string | null>(null);

  useEffect(() => {
    chatApi.listConversations().then(setConversations).catch(() => undefined);
    runsApi
      .list({ awaitingHuman: true, limit: 5 })
      .then(setApprovals)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!conversationId) return;
    chatApi
      .getConversation(conversationId)
      .then((c) => {
        setConversation(c);
        setMessages(c.messages);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load this workspace"));
  }, [conversationId]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const lastAssistantId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") return messages[i].id;
    }
    return null;
  }, [messages]);

  async function send(content: string) {
    if (!conversationId || !content.trim() || sending) return;
    setSending(true);
    setError(null);
    const parentId = messages.length > 0 ? messages[messages.length - 1].id : null;
    const userMsg: Message = {
      id: `local-${Date.now()}`,
      conversation_id: conversationId,
      parent_message_id: parentId,
      agent_id: null,
      role: "user",
      content,
      is_active_branch: true,
      citations: [],
      file_ids: [],
      created_at: new Date().toISOString(),
    };
    const assistantMsg: Message = { ...userMsg, id: `local-a-${Date.now()}`, role: "assistant", content: "", streaming: true };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setDraft("");

    try {
      await streamMessage(
        { conversationId, content, parentMessageId: parentId },
        {
          onToken: (e) => {
            setMessages((prev) => prev.map((m) => (m.id === assistantMsg.id ? { ...m, content: m.content + e.text } : m)));
          },
          onComplete: () => {
            setMessages((prev) => prev.map((m) => (m.id === assistantMsg.id ? { ...m, streaming: false } : m)));
          },
          onError: () => {
            setError("The connection to the assistant dropped.");
            setMessages((prev) => prev.map((m) => (m.id === assistantMsg.id ? { ...m, streaming: false } : m)));
          },
        },
      );
    } catch {
      setError("Could not send that message.");
    } finally {
      setSending(false);
      chatApi.getConversation(conversationId).then(setConversation).catch(() => undefined);
    }
  }

  // Auto-send the goal text carried over from Home's "Start" composer.
  useEffect(() => {
    const draftParam = searchParams.get("draft");
    if (draftParam && conversationId && autoSentRef.current !== conversationId) {
      autoSentRef.current = conversationId;
      send(draftParam);
      searchParams.delete("draft");
      setSearchParams(searchParams, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, searchParams]);

  async function resolveApproval(runId: string, approved: boolean) {
    try {
      await runsApi.decide(runId, approved);
      setApprovals((prev) => prev.filter((r) => r.id !== runId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not resolve that approval");
    }
  }

  return (
    <section className="mds-screen on" style={{ flex: 1, minHeight: 0, display: "flex" }}>
      <div className="mds-ws">
        <aside className="mds-side">
          <div className="search">
            <input placeholder="Search workspaces" style={{ width: "100%", fontSize: 13.5, padding: "8px 12px" }} readOnly />
          </div>
          <div className="items">
            {conversations.map((c) => (
              <div
                key={c.id}
                className={`mds-ws-item ${c.id === conversationId ? "on" : ""}`}
                onClick={() => navigate(`/app/u/workspace/${c.id}`)}
              >
                <div className="nm">{c.title}</div>
                <div className="st">{new Date(c.created_at).toLocaleDateString()}</div>
              </div>
            ))}
          </div>
          <div className="foot">
            <button className="mds-btn mds-btn-block" style={{ fontSize: 13.5 }} onClick={() => navigate("/app/u/home")}>
              New workspace
            </button>
          </div>
        </aside>

        <div className="mds-main">
          <div className="head">
            <div style={{ flex: 1, minWidth: 0 }}>
              <h2 style={{ fontSize: 20 }}>{conversation?.title ?? "Select a workspace"}</h2>
              <div className="mds-muted" style={{ fontSize: 13, marginTop: 2 }}>
                {sending ? "Working…" : conversation ? "Ready" : ""}
              </div>
            </div>
            <button className="mds-icon-btn" title="Show or hide the workspace panel" onClick={() => setPanelOpen((v) => !v)}>
              ⟨⟩
            </button>
          </div>

          {error && <p style={{ color: "var(--mds-a800)", padding: "8px 32px 0" }}>{error}</p>}

          <div className="mds-thread">
            {messages.map((m) => (
              <div className={`mds-msg ${m.role === "user" ? "me" : ""}`} key={m.id}>
                <div className="mds-bubble">
                  {m.role === "assistant" && <div className="mds-who">Assistant</div>}
                  {m.content}
                  {m.streaming && m.id === lastAssistantId && <span className="mds-muted"> …</span>}
                </div>
              </div>
            ))}
            <div ref={threadEndRef} />
          </div>

          <div className="mds-composer">
            <textarea
              rows={2}
              placeholder="Add a detail, change the goal, or answer a question"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(draft);
                }
              }}
              disabled={!conversationId || sending}
            />
            <button className="mds-btn mds-btn-primary" style={{ padding: "13px 24px" }} disabled={!conversationId || sending} onClick={() => send(draft)}>
              Send
            </button>
          </div>
        </div>

        <aside className={`mds-panel ${panelOpen ? "" : "hide"}`}>
          {approvals.length > 0 && (
            <div className="mds-approval">
              <div className="mds-kicker" style={{ color: "var(--mds-a700)", marginBottom: 9 }}>Needs your approval</div>
              {approvals.map((a) => (
                <div key={a.id} style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 14.5, lineHeight: 1.55, marginBottom: 10 }}>{a.objective}</div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button className="mds-btn mds-btn-primary mds-btn-sm" style={{ flex: 1 }} onClick={() => resolveApproval(a.id, true)}>Approve</button>
                    <button className="mds-btn mds-btn-sm" style={{ flex: 1 }} onClick={() => resolveApproval(a.id, false)}>Skip it</button>
                  </div>
                </div>
              ))}
            </div>
          )}
          <div>
            <div className="mds-kicker" style={{ marginBottom: 10 }}>Goal</div>
            <div style={{ fontSize: 16, lineHeight: 1.55 }}>{conversation?.title ?? "—"}</div>
          </div>
        </aside>
      </div>
    </section>
  );
}
