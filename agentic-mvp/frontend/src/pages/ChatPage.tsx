import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { Citation, Conversation, Message, ModelInfo, Project, ProjectTopology, Prompt, SiblingGroup, UploadedFileMeta } from "../types";
import { modelsApi } from "../api/models";
import { promptsApi } from "../api/prompts";
import { chatApi, streamMessage } from "../api/chat";
import { projectsApi } from "../api/projects";
import { uploadFile } from "../api/files";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";
import ChatComposer from "../components/chat/ChatComposer";
import MessageBubble from "../components/chat/MessageBubble";
import CitationDrawer from "../components/chat/CitationDrawer";

interface Turn {
  user: Message;
  responses: Message[];
}

function groupIntoTurns(msgs: Message[]): Turn[] {
  const turns: Turn[] = [];
  let current: Turn | null = null;
  for (const m of msgs) {
    if (m.role === "user") {
      current = { user: m, responses: [] };
      turns.push(current);
    } else if (m.role === "assistant" && current) {
      current.responses.push(m);
    }
  }
  return turns;
}

export default function ChatPage() {
  const { user, logout } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [allAgents, setAllAgents] = useState<ModelInfo[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(searchParams.get("project"));
  const [projectAgents, setProjectAgents] = useState<ModelInfo[] | null>(null);
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationSearch, setConversationSearch] = useState("");
  const [newChatDraft, setNewChatDraft] = useState("");
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [siblingsMap, setSiblingsMap] = useState<Record<string, SiblingGroup>>({});
  const [activeAgentIds, setActiveAgentIds] = useState<string[]>([]);

  // Scoped chat: when a Project is selected, only agents bound to it (via
  // the Intelligence-to-Project association matrix) are selectable — see
  // GET /projects/{id}/available-agents. Unscoped (no project) keeps the
  // original behavior of picking from every agent this user can see.
  const agents = projectAgents ?? allAgents;

  const [composerValue, setComposerValue] = useState("");
  const [attachedFiles, setAttachedFiles] = useState<UploadedFileMeta[]>([]);
  const [fileMetaCache, setFileMetaCache] = useState<Record<string, UploadedFileMeta>>({});
  const [uploading, setUploading] = useState(false);

  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [citationOpen, setCitationOpen] = useState<Citation | null>(null);
  const [rightPanelOpen, setRightPanelOpen] = useState(true);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [topology, setTopology] = useState<ProjectTopology | null>(null);

  useEffect(() => {
    if (!selectedProjectId) {
      setTopology(null);
      return;
    }
    projectsApi
      .topology(selectedProjectId)
      .then(setTopology)
      .catch(() => setTopology(null));
  }, [selectedProjectId]);

  useEffect(() => {
    Promise.all([modelsApi.list(), promptsApi.list(), chatApi.listConversations(), projectsApi.list()])
      .then(([modelList, promptList, convoList, projectList]) => {
        setAllAgents(modelList);
        setPrompts(promptList);
        setConversations(convoList);
        setProjects(projectList);
        if (!selectedProjectId && modelList.length > 0) setActiveAgentIds([modelList[0].id]);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load chat setup"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedProjectId) {
      setProjectAgents(null);
      return;
    }
    projectsApi
      .availableAgents(selectedProjectId)
      .then((list) => {
        const scoped = list.map((a) => ({ id: a.id, name: a.name, model_name: a.name, description: null }));
        setProjectAgents(scoped);
        setActiveAgentIds(scoped.length > 0 ? [scoped[0].id] : []);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load project agents"));
  }, [selectedProjectId]);

  function handleSelectProject(projectId: string) {
    const value = projectId || null;
    setSelectedProjectId(value);
    setSearchParams(value ? { project: value } : {});
    handleNewChat();
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const agentLookup = useMemo(() => {
    const map: Record<string, ModelInfo> = {};
    agents.forEach((a) => (map[a.id] = a));
    return map;
  }, [agents]);

  const turns = useMemo(() => groupIntoTurns(messages), [messages]);

  async function refreshSiblings(msgs: Message[]) {
    const userMsgs = msgs.filter((m) => m.role === "user" && !m.id.startsWith("temp-"));
    const entries = await Promise.all(
      userMsgs.map(async (m) => {
        try {
          return [m.id, await chatApi.getSiblings(m.id)] as const;
        } catch {
          return null;
        }
      }),
    );
    const map: Record<string, SiblingGroup> = {};
    entries.forEach((e) => {
      if (e) map[e[0]] = e[1];
    });
    setSiblingsMap(map);
  }

  async function loadConversation(id: string) {
    setError(null);
    try {
      const full = await chatApi.getConversation(id);
      setConversation(full);
      setMessages(full.messages);
      setActiveAgentIds([full.agent_id, ...full.secondary_agent_ids]);
      if (full.project_id !== selectedProjectId) {
        setSelectedProjectId(full.project_id ?? null);
        setSearchParams(full.project_id ? { project: full.project_id } : {});
      }
      refreshSiblings(full.messages);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load conversation");
    }
  }

  function handleNewChat() {
    setConversation(null);
    setMessages([]);
    setSiblingsMap({});
    setComposerValue("");
    setAttachedFiles([]);
    setError(null);
  }

  // Sidebar quick-start: typing a message and hitting "New chat" both
  // starts a fresh conversation AND sends that message as its first turn
  // in one step, instead of requiring an empty chat + a second message.
  function handleQuickStart() {
    const draft = newChatDraft.trim();
    handleNewChat();
    if (draft) {
      setNewChatDraft("");
      sendTurn(draft);
    }
  }

  const filteredConversations = useMemo(() => {
    const q = conversationSearch.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter((c) => c.title.toLowerCase().includes(q));
  }, [conversations, conversationSearch]);

  function handleToggleAgent(agentId: string) {
    setActiveAgentIds((prev) =>
      prev.includes(agentId) ? (prev.length > 1 ? prev.filter((id) => id !== agentId) : prev) : [...prev, agentId],
    );
  }

  async function handleAttachFile(file: File) {
    setUploading(true);
    setError(null);
    try {
      const meta = await uploadFile(file);
      setAttachedFiles((prev) => [...prev, meta]);
      setFileMetaCache((prev) => ({ ...prev, [meta.id]: meta }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "File upload failed");
    } finally {
      setUploading(false);
    }
  }

  function handleRemoveAttachment(fileId: string) {
    setAttachedFiles((prev) => prev.filter((f) => f.id !== fileId));
  }

  async function sendTurn(content: string, opts?: { parentMessageId?: string | null; truncateFromIndex?: number }) {
    if (!content.trim() || activeAgentIds.length === 0) return;
    setError(null);

    let convo = conversation;
    const fileIds = attachedFiles.map((f) => f.id);
    const wasEmpty = messages.length === 0 && opts?.truncateFromIndex === undefined;

    if (!convo) {
      try {
        convo = await chatApi.createConversation(activeAgentIds[0], activeAgentIds.slice(1), undefined, selectedProjectId);
        setConversation(convo);
        setConversations((prev) => [convo as Conversation, ...prev]);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to start conversation");
        return;
      }
    }

    if (opts?.truncateFromIndex !== undefined) {
      setMessages((prev) => prev.slice(0, opts.truncateFromIndex));
    }
    setAttachedFiles([]);
    setComposerValue("");

    const tempUserId = `temp-user-${Date.now()}`;
    const userMsg: Message = {
      id: tempUserId,
      conversation_id: convo.id,
      parent_message_id: opts?.parentMessageId ?? null,
      agent_id: null,
      role: "user",
      content,
      is_active_branch: true,
      citations: [],
      file_ids: fileIds,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setSending(true);

    const placeholders: Record<string, string> = {};
    activeAgentIds.forEach((id) => {
      placeholders[id] = `temp-agent-${id}-${Date.now()}`;
    });

    try {
      await streamMessage(
        {
          conversationId: convo.id,
          content,
          fileIds,
          parentMessageId: opts?.parentMessageId ?? null,
          agentIds: activeAgentIds,
        },
        {
          onStatus: (e) => {
            setMessages((prev) => prev.map((m) => (m.id === tempUserId ? { ...m, id: e.user_message_id } : m)));
          },
          onStreamStart: (e) => {
            const tempId = placeholders[e.agent_id];
            setMessages((prev) => [
              ...prev,
              {
                id: tempId,
                conversation_id: convo!.id,
                parent_message_id: null,
                agent_id: e.agent_id,
                role: "assistant",
                content: "",
                is_active_branch: true,
                citations: [],
                file_ids: [],
                created_at: new Date().toISOString(),
                streaming: true,
              },
            ]);
          },
          onToolCall: (e) => {
            const tempId = placeholders[e.agent_id];
            setMessages((prev) => prev.map((m) => (m.id === tempId ? { ...m, toolCall: e.tool_name } : m)));
          },
          onSkillCall: (e) => {
            const tempId = placeholders[e.agent_id];
            setMessages((prev) => prev.map((m) => (m.id === tempId ? { ...m, skillCall: e.skill_name } : m)));
          },
          onToken: (e) => {
            const tempId = placeholders[e.agent_id];
            setMessages((prev) => prev.map((m) => (m.id === tempId ? { ...m, content: m.content + e.text } : m)));
          },
          onStreamEnd: (e) => {
            const tempId = placeholders[e.agent_id];
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
                      ...m,
                      id: e.message_id,
                      content: e.content,
                      citations: e.citations,
                      streaming: false,
                      toolCall: null,
                      skillCall: null,
                      blocked: e.blocked ?? false,
                    }
                  : m,
              ),
            );
          },
          onAgentError: (e) => {
            const tempId = placeholders[e.agent_id];
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tempId ? { ...m, content: e.message, streaming: false, toolCall: null } : m,
              ),
            );
            setError(`${agentLookup[e.agent_id]?.name ?? "An agent"} failed to respond`);
          },
          onError: () => setError("Stream interrupted — see console for details"),
        },
      );
    } catch {
      setError("Stream failed");
    } finally {
      setSending(false);
      try {
        if (wasEmpty) {
          await chatApi.generateTitle(convo.id);
        }
        const fresh = await chatApi.getConversation(convo.id);
        setConversation(fresh);
        setMessages(fresh.messages);
        refreshSiblings(fresh.messages);
        setConversations((prev) => prev.map((c) => (c.id === fresh.id ? { ...c, title: fresh.title } : c)));
      } catch {
        // Non-fatal: local optimistic state remains as the fallback view.
      }
    }
  }

  function handleEdit(message: Message, newContent: string) {
    const idx = messages.findIndex((m) => m.id === message.id);
    if (idx === -1) return;
    sendTurn(newContent, { parentMessageId: message.parent_message_id, truncateFromIndex: idx });
  }

  async function handleSelectBranch(message: Message, targetId: string) {
    if (!conversation) return;
    try {
      await chatApi.selectBranch(message.id, targetId);
      const fresh = await chatApi.getConversation(conversation.id);
      setConversation(fresh);
      setMessages(fresh.messages);
      refreshSiblings(fresh.messages);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to switch branch");
    }
  }

  if (loading) {
    return <p className="empty-state">Loading chat...</p>;
  }

  if (agents.length === 0) {
    return (
      <div>
        <div className="page-header">
          <div>
            <h1>Chat</h1>
            <p>Select agents and start asking questions.</p>
          </div>
        </div>
        {projects.length > 0 && (
          <div className="field" style={{ maxWidth: 320, marginBottom: 16 }}>
            <label>Project</label>
            <select className="input" value={selectedProjectId ?? ""} onChange={(e) => handleSelectProject(e.target.value)}>
              <option value="">Unscoped chat</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.status})
                </option>
              ))}
            </select>
          </div>
        )}
        <p className="empty-state">
          {selectedProjectId
            ? "No agents bound to this project yet. Bind one from the Projects screen's Intelligence tab."
            : "No active agents yet. Create one in the Agents screen first."}
        </p>
      </div>
    );
  }

  const selectedProject = projects.find((p) => p.id === selectedProjectId) ?? null;
  const initials = (user?.full_name ?? "U")
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  const statusTagClass: Record<Project["status"], string> = {
    draft: "tag-neutral",
    frozen: "tag-outline",
    deployed: "tag-accent",
    archived: "tag-neutral",
  };

  function formatConvoMeta(c: Conversation): string {
    const p = c.project_id ? projects.find((pr) => pr.id === c.project_id) : null;
    const base = p ? p.name : new Date(c.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    const agentCount = 1 + c.secondary_agent_ids.length;
    return `${base} · ${agentCount} agent${agentCount === 1 ? "" : "s"}`;
  }

  return (
    <div className="rail-shell">
      <aside className="rail">
        <div className="rail-brand">
          <div className="layerbar" />
          <div>
            <h1>Knowledge Nexus</h1>
            <span>workspace console</span>
          </div>
        </div>

        {projects.length > 0 && (
          <div className="rail-ws-block">
            <label className="rail-label">Workspace</label>
            <select className="rail-ws-select" style={{ appearance: "none" }} value={selectedProjectId ?? ""} onChange={(e) => handleSelectProject(e.target.value)}>
              <option value="">Unscoped chat</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.status})
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="rail-quickstart">
          <label className="rail-label">New goal or task</label>
          <div className="rail-quickstart-box">
            <textarea
              className="rail-quickstart-input"
              rows={2}
              placeholder='Describe a goal — e.g. "Summarize ingestion errors from last week"'
              value={newChatDraft}
              onChange={(e) => setNewChatDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleQuickStart();
                }
              }}
            />
          </div>
          <button type="button" className="rail-new-chat" onClick={handleQuickStart}>
            <span style={{ fontSize: 18, lineHeight: 1 }}>+</span> New chat
          </button>
        </div>

        <div className="rail-search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            className="rail-search-input"
            placeholder="Search chats"
            value={conversationSearch}
            onChange={(e) => setConversationSearch(e.target.value)}
          />
        </div>

        <div className="rail-label rail-recent-label">Recent</div>
        <nav className="rail-recent">
          {filteredConversations.map((c) => (
            <button type="button" key={c.id} className={conversation?.id === c.id ? "active" : ""} onClick={() => loadConversation(c.id)}>
              <span className="r-title">{c.title}</span>
              <span className="r-meta">{formatConvoMeta(c)}</span>
            </button>
          ))}
          {filteredConversations.length === 0 && conversationSearch.trim() && (
            <div className="rail-empty">No chats match &quot;{conversationSearch}&quot;</div>
          )}
        </nav>

        <div className="rail-user">
          <div className="rail-avatar">{initials}</div>
          <div className="rail-user-info">
            <div className="u-name">{user?.full_name}</div>
            <div className="u-persona">role: {user?.role}</div>
          </div>
          <button type="button" className="rail-logout-btn" title="Log out" onClick={logout}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
          </button>
        </div>
      </aside>

      <main className="rail-main">
        <header className="rail-chat-header">
          <div className="rail-chat-title-block">
            <div className="rail-chat-title-row">
              <h2 style={{ fontFamily: "var(--font-disp)", fontSize: 15, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {conversation?.title ?? "New conversation"}
              </h2>
              {selectedProject && <span className={`tag ${statusTagClass[selectedProject.status]}`}>{selectedProject.status}</span>}
              <div className="chip-select">
                {agents.map((a) => (
                  <div key={a.id} className={`chip ${activeAgentIds.includes(a.id) ? "selected" : ""}`} onClick={() => handleToggleAgent(a.id)}>
                    {a.name}
                  </div>
                ))}
              </div>
            </div>
            {selectedProject && <div className="rail-chat-subtitle">{selectedProject.description || selectedProject.name}</div>}
          </div>
          <div className="rail-status-chips">
            <span className="rail-chip knw">
              <span className="dot" />
              {topology ? `${topology.datasources.length} sources connected` : `${agents.length} agent${agents.length === 1 ? "" : "s"} active`}
            </span>
            <span className="rail-chip nrm">
              <span className="dot" />
              Guardrails on
            </span>
            <button
              type="button"
              className="btn btn-ghost btn-icon"
              title={rightPanelOpen ? "Hide session panel" : "Show session panel"}
              onClick={() => setRightPanelOpen((v) => !v)}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ transform: rightPanelOpen ? "rotate(0deg)" : "rotate(180deg)" }}>
                <path d="m9 18 6-6-6-6" />
              </svg>
            </button>
          </div>
        </header>

        {error && <p className="error-text" style={{ margin: "8px 24px 0" }}>{error}</p>}

        <div className="qa-thread">
          <div className="qa-thread-inner">
            {turns.length === 0 && (
              <div className="qa-welcome">
                <h3>Ask anything about this workspace</h3>
                <p>
                  Type <code>@</code> to pick agents to compare side by side, or <code>/</code> to insert a prompt
                  template. Answers cite the sources they came from.
                </p>
              </div>
            )}
            {turns.map((turn) => (
              <div key={turn.user.id} className="qa-turn">
                <MessageBubble
                  message={turn.user}
                  fileMeta={turn.user.file_ids.map((id) => fileMetaCache[id]).filter(Boolean) as UploadedFileMeta[]}
                  siblings={siblingsMap[turn.user.id]}
                  onSelectBranch={(sid) => handleSelectBranch(turn.user, sid)}
                  onCitationClick={setCitationOpen}
                  onEditSubmit={(newContent) => handleEdit(turn.user, newContent)}
                />
                <div
                  className={`qa-grid ${turn.responses.length > 1 ? "split" : ""}`}
                  style={
                    turn.responses.length > 1
                      ? { gridTemplateColumns: `repeat(${turn.responses.length}, 1fr)` }
                      : undefined
                  }
                >
                  {turn.responses.map((r) => (
                    <MessageBubble
                      key={r.id}
                      message={r}
                      agent={r.agent_id ? agentLookup[r.agent_id] : undefined}
                      onCitationClick={setCitationOpen}
                      split={turn.responses.length > 1}
                    />
                  ))}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>

        <div className="composer">
          <div style={{ margin: "0 auto" }}>
            <ChatComposer
              value={composerValue}
              onChange={setComposerValue}
              onSend={() => sendTurn(composerValue)}
              disabled={sending}
              agents={agents}
              activeAgentIds={activeAgentIds}
              onToggleAgent={handleToggleAgent}
              prompts={prompts}
              attachedFiles={attachedFiles}
              uploading={uploading}
              onAttachFile={handleAttachFile}
              onRemoveAttachment={handleRemoveAttachment}
            />
          </div>
        </div>
      </main>

      <aside className="rail-context" style={{ display: rightPanelOpen ? undefined : "none" }}>
        <h3>Workspace panel</h3>
        <div className="rail-context-body">
          {selectedProject ? (
            <div className="card context-card">
              <div className="context-card-head">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--ink)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="3" width="7" height="7" rx="1" />
                  <rect x="14" y="3" width="7" height="7" rx="1" />
                  <rect x="3" y="14" width="7" height="7" rx="1" />
                  <rect x="14" y="14" width="7" height="7" rx="1" />
                </svg>
                <span className="card-kicker" style={{ color: "var(--ink)" }}>Workspace</span>
              </div>
              <div className="card-title" style={{ fontSize: 15, marginBottom: 4 }}>{selectedProject.name}</div>
              {selectedProject.description && (
                <p className="card-body" style={{ margin: 0 }}>{selectedProject.description}</p>
              )}
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                <span className={`tag ${statusTagClass[selectedProject.status]}`}>{selectedProject.status}</span>
                <span className="text-muted" style={{ fontSize: 11 }}>
                  since {new Date(selectedProject.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                </span>
              </div>
            </div>
          ) : (
            <div className="card context-card">
              <p className="card-body" style={{ margin: 0 }}>
                This chat isn&rsquo;t tied to a workspace. Pick one from the dropdown in the sidebar to scope agents,
                sources, and guardrails to a project.
              </p>
            </div>
          )}

          <div className="card context-card">
            <div className="context-card-head">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--knw)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <ellipse cx="12" cy="5" rx="8" ry="3" />
                <path d="M4 5v6a8 3 0 0 0 16 0V5" />
                <path d="M4 11v6a8 3 0 0 0 16 0v-6" />
              </svg>
              <span className="card-kicker" style={{ color: "var(--knw)" }}>Knowledge in scope</span>
            </div>
            {topology && topology.datasources.length > 0 ? (
              <ul className="rail-src-list">
                {topology.datasources.map((ds) => (
                  <li key={ds.datasource_id}>
                    <span>{ds.name}</span>
                    <span className="count text-muted">{ds.sync_status}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="card-body" style={{ margin: 0 }}>
                {selectedProject ? "No datasources connected to this workspace." : "Select a workspace to see connected sources."}
              </p>
            )}
          </div>

          <div className="card context-card">
            <div className="context-card-head">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--exp)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
                <circle cx="12" cy="12" r="4" />
              </svg>
              <span className="card-kicker" style={{ color: "var(--exp)" }}>Expertise active</span>
            </div>
            {topology && topology.intelligence.filter((c) => c.component_type === "skill").length > 0 ? (
              <div className="rail-skill-tags">
                {topology.intelligence
                  .filter((c) => c.component_type === "skill")
                  .map((c) => (
                    <span key={c.component_id} className="tag tag-accent-2">
                      {c.name}
                    </span>
                  ))}
              </div>
            ) : (
              <p className="card-body" style={{ margin: 0 }}>
                {agents.find((a) => activeAgentIds.includes(a.id))?.description ?? "No skills bound in this workspace yet."}
              </p>
            )}
          </div>

          <div className="card context-card">
            <div className="context-card-head">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--nrm)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2 4 6v6c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V6Z" />
              </svg>
              <span className="card-kicker" style={{ color: "var(--nrm)" }}>Norms applied</span>
            </div>
            <ul className="rail-norm-list">
              <li>PII redaction active</li>
              <li>Rate limits enforced per tenant</li>
              <li>Chat scoped to your own conversations</li>
            </ul>
          </div>
        </div>
      </aside>

      <CitationDrawer citation={citationOpen} onClose={() => setCitationOpen(null)} />
    </div>
  );
}
