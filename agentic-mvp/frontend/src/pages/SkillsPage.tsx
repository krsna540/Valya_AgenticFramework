import { ChangeEvent, useEffect, useRef, useState } from "react";
import type { Skill } from "../types";
import { skillsApi } from "../api/skills";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";
import MarkdownRenderer from "../components/chat/MarkdownRenderer";

export default function SkillsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [items, setItems] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [viewingFile, setViewingFile] = useState<{ path: string; text: string } | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setItems(await skillsApi.list());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const created = await skillsApi.upload(file);
      await load();
      setSelectedId(created.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleToggleActive(skill: Skill) {
    try {
      await skillsApi.updateActive(skill.id, !skill.is_active);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this skill? This removes its files too.")) return;
    try {
      await skillsApi.remove(id);
      if (selectedId === id) setSelectedId(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    }
  }

  async function viewFile(skillId: string, path: string) {
    setFileError(null);
    try {
      const text = await skillsApi.getFileContent(skillId, path);
      setViewingFile({ path, text });
    } catch (err) {
      setFileError(err instanceof ApiError ? err.message : "Failed to load file");
    }
  }

  const selected = items.find((i) => i.id === selectedId) ?? null;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Skills</h1>
          <p>
            A skill is a folder — <code>SKILL.md</code> (required) plus optional <code>skill.json</code> (triggers
            &amp; hooks), <code>references/</code>, <code>scripts/</code>, and <code>assets/</code> — uploaded as a
            zip. Nothing inside is executed automatically; <code>scripts/</code> are stored and browsable, meant to
            be run by an agent that decides to.
          </p>
        </div>
        {isAdmin && (
          <div>
            <input ref={fileInputRef} type="file" accept=".zip" style={{ display: "none" }} onChange={handleUpload} />
            <button className="btn" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
              {uploading ? "Uploading..." : "Upload skill .zip"}
            </button>
          </div>
        )}
      </div>

      {error && <p className="error-text">{error}</p>}

      <div className="registry-layout">
        <div className="blueprint registry-list-col">
          <i className="corner tl" />
          <i className="corner tr" />
          <i className="corner bl" />
          <i className="corner br" />
          {loading ? (
            <p className="empty-state">Loading...</p>
          ) : items.length === 0 ? (
            <p className="empty-state">No skills uploaded yet.</p>
          ) : (
            items.map((skill) => (
              <div
                key={skill.id}
                className={`rowbtn ${selectedId === skill.id ? "selected" : ""}`}
                onClick={() => setSelectedId(skill.id)}
              >
                <span className="rowbtn-title">
                  <code>{skill.name}</code>
                </span>
                <div className="rowbtn-tags">
                  <span className={`tag ${skill.is_active ? "tag-accent" : "tag-neutral"}`}>
                    {skill.is_active ? "active" : "inactive"}
                  </span>
                  {skill.hooks.length > 0 && <span className="tag tag-neutral">{skill.hooks.length} hook(s)</span>}
                  <span className="text-muted" style={{ fontSize: 11.5 }}>{skill.file_manifest.length} files</span>
                </div>
              </div>
            ))
          )}
        </div>

        <div className="blueprint registry-panel">
          <i className="corner tl" />
          <i className="corner tr" />
          <i className="corner bl" />
          <i className="corner br" />
          {!selected ? (
            <p className="registry-panel-placeholder">Select a skill to view its SKILL.md and files, or upload a new one.</p>
          ) : (
            <>
              <div className="detail-header">
                <div>
                  <h6 className="detail-kicker">Skill</h6>
                  <h2>
                    <code>{selected.name}</code>
                  </h2>
                </div>
                <span className={`tag ${selected.is_active ? "tag-accent" : "tag-neutral"}`}>
                  {selected.is_active ? "active" : "inactive"}
                </span>
              </div>

              <div className="field">
                <label>Metadata</label>
                <div className="rowbtn-tags">
                  <span className="tag tag-neutral">v{selected.version}</span>
                  <span className="tag tag-neutral">{selected.status}</span>
                  {selected.license && <span className="tag tag-neutral">license: {selected.license}</span>}
                  {selected.compatibility && <span className="tag tag-neutral">compatibility: {selected.compatibility}</span>}
                  {selected.allowed_tools && <span className="tag tag-neutral">allowed-tools: {selected.allowed_tools}</span>}
                  {Object.entries(selected.metadata).map(([k, v]) => (
                    <span key={k} className="tag tag-neutral">
                      {k}: {v}
                    </span>
                  ))}
                </div>
              </div>

              {(selected.triggers.keywords.length > 0 ||
                selected.triggers.intents.length > 0 ||
                selected.triggers.lifecycle_events.length > 0 ||
                selected.hooks.length > 0) && (
                <div className="field">
                  <label>Triggers &amp; hooks (skill.json)</label>
                  <div className="rowbtn-tags">
                    {selected.triggers.keywords.map((k) => (
                      <span key={`kw-${k}`} className="tag tag-accent-2">
                        keyword: {k}
                      </span>
                    ))}
                    {selected.triggers.intents.map((i) => (
                      <span key={`intent-${i}`} className="tag tag-accent-2">
                        intent: {i}
                      </span>
                    ))}
                    {selected.triggers.lifecycle_events.map((e) => (
                      <span key={`lc-${e}`} className="tag tag-accent-2">
                        {e}
                      </span>
                    ))}
                    {selected.hooks.map((h) => (
                      <span key={`hook-${h}`} className="tag tag-neutral">
                        hook: {h}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="field">
                <label>SKILL.md instructions</label>
                <div className="card" style={{ maxHeight: 280, overflowY: "auto" }}>
                  <MarkdownRenderer content={selected.body_markdown || "*(empty body)*"} />
                </div>
              </div>

              <div className="field">
                <label>Files ({selected.file_manifest.length})</label>
                {selected.file_manifest.length === 0 ? (
                  <p className="empty-state" style={{ padding: "4px 0", textAlign: "left" }}>
                    Just SKILL.md.
                  </p>
                ) : (
                  <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
                    {selected.file_manifest.map((path) => (
                      <li key={path}>
                        <button
                          type="button"
                          className="bubble-action"
                          style={{ color: "var(--color-accent)" }}
                          onClick={() => viewFile(selected.id, path)}
                        >
                          {path}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {fileError && <p className="error-text">{fileError}</p>}
              </div>

              {isAdmin && (
                <div className="panel-actions">
                  <div>
                    <button type="button" className="btn-danger btn" onClick={() => handleDelete(selected.id)}>
                      Delete
                    </button>
                  </div>
                  <div className="panel-actions-right">
                    <button type="button" className="btn-secondary btn" onClick={() => handleToggleActive(selected)}>
                      {selected.is_active ? "Deactivate" : "Activate"}
                    </button>
                    <a className="btn" href={skillsApi.downloadUrl(selected.id)}>
                      Download .zip
                    </a>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {viewingFile && (
        <div className="modal-backdrop" onClick={() => setViewingFile(null)}>
          <div className="card modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 720 }}>
            <h2>{viewingFile.path}</h2>
            <pre className="code-block-plain" style={{ maxHeight: 420, overflow: "auto" }}>
              {viewingFile.text}
            </pre>
            <div className="modal-actions">
              <button type="button" className="btn-secondary btn" onClick={() => setViewingFile(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
