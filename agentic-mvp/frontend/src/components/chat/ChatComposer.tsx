import { ChangeEvent, DragEvent, KeyboardEvent, useMemo, useRef, useState } from "react";
import type { ModelInfo, Prompt, UploadedFileMeta } from "../../types";
import { promptComposerText } from "../../types";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  disabled?: boolean;

  agents: ModelInfo[];
  activeAgentIds: string[];
  onToggleAgent: (agentId: string) => void;

  prompts: Prompt[];

  attachedFiles: UploadedFileMeta[];
  uploading: boolean;
  onAttachFile: (file: File) => void;
  onRemoveAttachment: (fileId: string) => void;
}

type Overlay = "none" | "agent" | "prompt";

export default function ChatComposer({
  value,
  onChange,
  onSend,
  disabled,
  agents,
  activeAgentIds,
  onToggleAgent,
  prompts,
  attachedFiles,
  uploading,
  onAttachFile,
  onRemoveAttachment,
}: Props) {
  const [overlay, setOverlay] = useState<Overlay>("none");
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function handleChange(e: ChangeEvent<HTMLTextAreaElement>) {
    const v = e.target.value;
    onChange(v);
    if (/^@/.test(v)) {
      setOverlay("agent");
    } else if (/^\//.test(v)) {
      setOverlay("prompt");
    } else {
      setOverlay("none");
    }
  }

  const agentQuery = overlay === "agent" ? value.slice(1).toLowerCase() : "";
  const promptQuery = overlay === "prompt" ? value.slice(1).toLowerCase() : "";

  const filteredAgents = useMemo(
    () => agents.filter((a) => a.name.toLowerCase().includes(agentQuery)),
    [agents, agentQuery],
  );
  const filteredPrompts = useMemo(
    () => prompts.filter((p) => p.name.toLowerCase().includes(promptQuery)),
    [prompts, promptQuery],
  );

  function pickAgent(agentId: string) {
    onToggleAgent(agentId);
    onChange("");
    setOverlay("none");
  }

  function pickPrompt(prompt: Prompt) {
    onChange(promptComposerText(prompt));
    setOverlay("none");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (overlay !== "none" && e.key === "Escape") {
      setOverlay("none");
      return;
    }
    if (e.key === "Enter" && !e.shiftKey && overlay === "none") {
      e.preventDefault();
      if (value.trim()) onSend();
    }
  }

  function handleFiles(files: FileList | null) {
    if (!files) return;
    Array.from(files).forEach((f) => onAttachFile(f));
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    handleFiles(e.dataTransfer.files);
  }

  return (
    <div
      className={`composer ${dragOver ? "drag-over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      {overlay === "agent" && (
        <div className="composer-overlay">
          {filteredAgents.length === 0 ? (
            <div className="composer-overlay-empty">No matching agents</div>
          ) : (
            filteredAgents.map((a) => (
              <button type="button" key={a.id} className="composer-overlay-item" onClick={() => pickAgent(a.id)}>
                <span>{a.name}</span>
                {activeAgentIds.includes(a.id) && <span className="badge active">selected</span>}
              </button>
            ))
          )}
        </div>
      )}
      {overlay === "prompt" && (
        <div className="composer-overlay">
          {filteredPrompts.length === 0 ? (
            <div className="composer-overlay-empty">No matching prompt templates</div>
          ) : (
            filteredPrompts.map((p) => (
              <button type="button" key={p.id} className="composer-overlay-item" onClick={() => pickPrompt(p)}>
                <span>{p.name}</span>
                {p.description && <span className="composer-overlay-desc">{p.description}</span>}
              </button>
            ))
          )}
        </div>
      )}

      {(attachedFiles.length > 0 || uploading) && (
        <div className="attachment-row">
          {attachedFiles.map((f) => (
            <span key={f.id} className="chip selected">
              {f.filename}
              <button type="button" className="chip-remove" onClick={() => onRemoveAttachment(f.id)}>
                ×
              </button>
            </span>
          ))}
          {uploading && <span className="chip">Uploading…</span>}
        </div>
      )}

      <div className="chat-input-row">
        <input
          ref={fileInputRef}
          type="file"
          style={{ display: "none" }}
          onChange={(e) => {
            handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          className="btn btn-secondary attach-btn"
          title="Attach a file"
          onClick={() => fileInputRef.current?.click()}
        >
          📎
        </button>
        <textarea
          className="input"
          placeholder="Ask something... use @ to pick agents, / for prompt templates"
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
        />
        <button className="btn btn-primary" type="button" disabled={disabled || !value.trim()} onClick={onSend}>
          {disabled ? "..." : "Send"}
        </button>
      </div>
    </div>
  );
}
