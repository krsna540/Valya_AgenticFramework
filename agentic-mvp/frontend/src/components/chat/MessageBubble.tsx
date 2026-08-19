import { memo, useState } from "react";
import type { Citation, Message, ModelInfo, SiblingGroup, UploadedFileMeta } from "../../types";
import MarkdownRenderer from "./MarkdownRenderer";
import BranchNav from "./BranchNav";
import MessageFeedbackControls from "./MessageFeedback";

interface Props {
  message: Message;
  agent?: ModelInfo;
  fileMeta?: UploadedFileMeta[];
  siblings?: SiblingGroup;
  onSelectBranch?: (siblingId: string) => void;
  onCitationClick: (citation: Citation) => void;
  onEditSubmit?: (newContent: string) => void;
  /** true when several agents answered the same turn and this message is
      rendered inside a side-by-side comparison column. */
  split?: boolean;
}

function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

/**
 * A single message in the Q&A thread.
 *
 * Deliberately asymmetric, following the pattern modern assistant UIs
 * converged on: the *question* is a compact tinted bubble on the right,
 * the *answer* is full-width prose on the left with an author row and no
 * container at all. Wrapping long structured answers (headings, lists,
 * tables, code) in a bordered balloon is what made this thread feel
 * cramped — prose needs the full column width to breathe.
 */
function MessageBubble({
  message,
  agent,
  fileMeta = [],
  siblings,
  onSelectBranch,
  onCitationClick,
  onEditSubmit,
  split = false,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);
  const [copied, setCopied] = useState(false);

  const isUser = message.role === "user";

  async function copy() {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable (insecure origin / denied) — silently ignore
    }
  }

  if (editing) {
    return (
      <div className="qa-ask">
        <div className="qa-edit">
          <textarea className="input" value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} autoFocus />
          <div className="qa-edit-actions">
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEditing(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => {
                setEditing(false);
                onEditSubmit?.(draft);
              }}
            >
              Save &amp; regenerate
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── the question ────────────────────────────────────────────────
  if (isUser) {
    return (
      <div className="qa-ask">
        <div className="qa-ask-body">
          {fileMeta.length > 0 && (
            <div className="qa-files">
              {fileMeta.map((f) => (
                <span key={f.id} className="qa-file">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
                    <path d="M14 2v6h6" />
                  </svg>
                  {f.filename}
                </span>
              ))}
            </div>
          )}
          <div className="qa-ask-text">{message.content}</div>
        </div>
        <div className="qa-ask-tools">
          {onEditSubmit && (
            <button type="button" className="qa-tool" onClick={() => setEditing(true)}>
              Edit
            </button>
          )}
          {siblings && onSelectBranch && <BranchNav siblings={siblings} onSelect={onSelectBranch} />}
        </div>
      </div>
    );
  }

  // ── the answer ──────────────────────────────────────────────────
  const name = agent?.name ?? "Agent";
  return (
    <div className={`qa-answer${split ? " split" : ""}${message.blocked ? " blocked" : ""}`}>
      <div className="qa-author">
        <span className="qa-avatar">{initialsOf(name)}</span>
        <span className="qa-author-name">{name}</span>
        {message.streaming && <span className="qa-thinking">thinking…</span>}
      </div>

      <div className="qa-answer-body">
        {message.blocked && (
          <div className="qa-notice blocked">Response halted by a hook policy</div>
        )}
        {message.toolCall && (
          <div className="qa-notice">
            <span className="qa-notice-dot" />
            Running tool <code>{message.toolCall}</code>
          </div>
        )}
        {message.skillCall && (
          <div className="qa-notice">
            <span className="qa-notice-dot" />
            Using skill <code>{message.skillCall}</code>
          </div>
        )}

        <MarkdownRenderer
          content={message.content}
          citations={message.citations}
          onCitationClick={onCitationClick}
          streaming={message.streaming}
        />

        {message.streaming && !message.content && <div className="qa-skeleton" aria-label="Generating response" />}
        {message.streaming && message.content && <span className="stream-cursor">▍</span>}

        {!message.streaming && message.citations.length > 0 && (
          <div className="qa-sources">
            <span className="qa-sources-label">Sources ({message.citations.length})</span>
            <div className="qa-sources-list">
              {message.citations.map((c, i) => (
                <button type="button" key={c.id} className="qa-source-chip" onClick={() => onCitationClick(c)}>
                  <span className="qa-source-index">{i + 1}</span>
                  {c.source}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {!message.streaming && message.content && (
        <div className="qa-answer-tools">
          <button type="button" className="qa-tool" aria-label="Copy message" onClick={copy}>
            {copied ? "Copied" : "Copy"}
          </button>
          <MessageFeedbackControls
            messageId={message.id}
            initialFeedback={message.feedback ?? null}
            initialReason={message.feedback_reason ?? null}
          />
        </div>
      )}
    </div>
  );
}

export default memo(MessageBubble);
