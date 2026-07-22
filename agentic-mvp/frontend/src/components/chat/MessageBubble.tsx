import { useState } from "react";
import type { Citation, Message, ModelInfo, SiblingGroup, UploadedFileMeta } from "../../types";
import MarkdownRenderer from "./MarkdownRenderer";
import BranchNav from "./BranchNav";

interface Props {
  message: Message;
  agent?: ModelInfo;
  fileMeta?: UploadedFileMeta[];
  siblings?: SiblingGroup;
  onSelectBranch?: (siblingId: string) => void;
  onCitationClick: (citation: Citation) => void;
  onEditSubmit?: (newContent: string) => void;
}

export default function MessageBubble({
  message,
  agent,
  fileMeta = [],
  siblings,
  onSelectBranch,
  onCitationClick,
  onEditSubmit,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);

  const isUser = message.role === "user";

  if (editing) {
    return (
      <div className="chat-bubble user editing">
        <textarea className="input" value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} />
        <div className="modal-actions" style={{ marginTop: 8 }}>
          <button type="button" className="btn btn-secondary" onClick={() => setEditing(false)}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setEditing(false);
              onEditSubmit?.(draft);
            }}
          >
            Save & regenerate
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={`chat-bubble-wrap ${isUser ? "user" : "agent"}`}>
      {!isUser && agent && <div className="bubble-agent-label">{agent.name}</div>}
      <div className={`chat-bubble ${isUser ? "user" : "agent blueprint"} ${message.blocked ? "blocked" : ""}`}>
        {!isUser && (
          <>
            <i className="corner tl" />
            <i className="corner tr" />
            <i className="corner bl" />
            <i className="corner br" />
          </>
        )}
        {fileMeta.length > 0 && (
          <div className="attachment-row" style={{ marginBottom: 8 }}>
            {fileMeta.map((f) => (
              <span key={f.id} className="chip">
                {f.filename}
              </span>
            ))}
          </div>
        )}

        {message.blocked && <div className="blocked-badge">🛑 blocked by a hook policy</div>}

        {message.toolCall && (
          <div className="tool-call-badge">⚙ executing tool: {message.toolCall}</div>
        )}
        {message.skillCall && (
          <div className="tool-call-badge">🧩 activated skill: {message.skillCall}</div>
        )}

        <MarkdownRenderer content={message.content || (message.streaming ? "…" : "")} citations={message.citations} onCitationClick={onCitationClick} />

        {message.streaming && <span className="stream-cursor">▍</span>}
      </div>

      <div className="bubble-footer">
        {isUser && onEditSubmit && (
          <button type="button" className="bubble-action" onClick={() => setEditing(true)}>
            Edit
          </button>
        )}
        {siblings && onSelectBranch && <BranchNav siblings={siblings} onSelect={onSelectBranch} />}
      </div>
    </div>
  );
}
