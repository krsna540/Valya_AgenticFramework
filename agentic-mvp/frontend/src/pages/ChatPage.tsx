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
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [allAgents, setAllAgents] = useState<ModelInfo[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(searchParams.get("project"));
  const [projectAgents, setProjectAgents] = useState<ModelInfo[] | null>(null);
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
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

        <button type="button" className="rail-new-chat" onClick={handleNewChat}>
          <span style={{ fontSize: 18, lineHeight: 1 }}>+</span> New chat
        </button>

        <div className="rail-label rail-recent-label">Recent</div>
        <nav className="rail-recent">
          {conversations.map((c) => (
            <button type="button" key={c.id} className={conversation?.id === c.id ? "active" : ""} onClick={() => loadConversation(c.id)}>
              {c.title}
            </button>
          ))}
        </nav>

        <div className="rail-user">
          <div className="rail-avatar">{initials}</div>
          <div>
            <div className="u-name">{user?.full_name}</div>
            <div className="u-persona">role: {user?.role}</div>
          </div>
        </div>
      </aside>

      <main className="rail-main">
        <header className="rail-chat-header">
          <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
            <h2 style={{ fontFamily: "var(--font-disp)", fontSize: 15, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {conversation?.title ?? "New conversation"}
            </h2>
            <div className="chip-select">
              {agents.map((a) => (
                <div key={a.id} className={`chip ${activeAgentIds.includes(a.id) ? "selected" : ""}`} onClick={() => handleToggleAgent(a.id)}>
                  {a.name}
                </div>
              ))}
            </div>
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
          </div>
        </header>

        {error && <p className="error-text" style={{ margin: "8px 24px 0" }}>{error}</p>}

        <div className="chat-messages" style={{ flex: 1, padding: "24px", overflowY: "auto" }}>
          <div style={{ maxWidth: 680, margin: "0 auto", display: "flex", flexDirection: "column", gap: 24 }}>
            {turns.length === 0 && (
              <p className="empty-state">
                Say hello to get started. Type <code>@</code> to pick agents to compare, <code>/</code> for prompt
                templates.
              </p>
            )}
            {turns.map((turn) => (
              <div key={turn.user.id} className="turn">
                <MessageBubble
                  message={turn.user}
                  fileMeta={turn.user.file_ids.map((id) => fileMetaCache[id]).filter(Boolean) as UploadedFileMeta[]}
                  siblings={siblingsMap[turn.user.id]}
                  onSelectBranch={(sid) => handleSelectBranch(turn.user, sid)}
                  onCitationClick={setCitationOpen}
                  onEditSubmit={(newContent) => handleEdit(turn.user, newContent)}
                />
                <div
                  className={`response-grid ${turn.responses.length > 1 ? "split" : ""}`}
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
                    />
                  ))}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>

        <div className="composer">
          <div style={{ maxWidth: 680, margin: "0 auto" }}>
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

      <aside className="rail-context">
        <h3>Session context</h3>
        <div className="rail-context-body">
          <div>
            <div className="rail-layer-head" style={{ color: "var(--knw)" }}>Knowledge in scope</div>
            {topology && topology.datasources.length > 0 ? (
              <ul className="rail-src-list" style={{ listStyle: "none", padding: 0, fontSize: 13 }}>
                {topology.datasources.map((ds) => (
                  <li key={ds.datasource_id} style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                    <span>{ds.name}</span>
                    <span className="mono text-muted">{ds.sync_status}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p style={{ fontSize: 13, color: "var(--muted)" }}>
                {selectedProject ? "No datasources connected to this workspace." : "Select a workspace to see connected sources."}
              </p>
            )}
          </div>
          <div>
            <div className="rail-layer-head" style={{ color: "var(--exp)" }}>Expertise active</div>
            {topology && topology.intelligence.filter((c) => c.component_type === "skill").length > 0 ? (
              <div className="rail-skill-tags" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {topology.intelligence
                  .filter((c) => c.component_type === "skill")
                  .map((c) => (
                    <span key={c.component_id} className="tag tag-accent-2">
                      {c.name}
                    </span>
                  ))}
              </div>
            ) : (
              <p style={{ fontSize: 13, color: "var(--muted)" }}>
                {agents.find((a) => activeAgentIds.includes(a.id))?.description ?? "No skills bound in this workspace yet."}
              </p>
            )}
          </div>
          <div>
            <div className="rail-layer-head" style={{ color: "var(--nrm)" }}>Norms applied</div>
            <ul className="rail-norm-list" style={{ listStyle: "none", padding: 0, fontSize: 13, color: "rgba(18,22,27,0.75)" }}>
              <li style={{ marginBottom: 6 }}>PII redaction active</li>
              <li style={{ marginBottom: 6 }}>Rate limits enforced per tenant</li>
              <li>Chat scoped to your own conversations</li>
            </ul>
          </div>
        </div>
      </aside>

      <CitationDrawer citation={citationOpen} onClose={() => setCitationOpen(null)} />
    </div>
  );
}
