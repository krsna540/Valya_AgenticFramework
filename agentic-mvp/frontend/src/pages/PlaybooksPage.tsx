import { FormEvent, useEffect, useState } from "react";
import {
  playbooksApi,
  type Playbook,
  type PlaybookApprovalGate,
  type PlaybookAssumption,
  type PlaybookExample,
  type PlaybookExchange,
  type PlaybookGuardrail,
  type PlaybookInput,
  type PlaybookInputKind,
  type PlaybookOutOfScope,
  type PlaybookStep,
} from "../api/playbooks";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";
import TagInput from "../components/TagInput";

// Authoring surface for the Playbook registry (the sixth registry kind —
// PLATFORM_ARCHITECTURE.md §11.5). The form is organised as the seven
// authoring components an operations author actually writes, in the order
// they write them, rather than in column order:
//
//   1. Name & Scope        name / description / target_persona / out_of_scope
//   2. High-Level Goal     objective (+ when_to_use, the Planner's selection
//                          signal, which lives in the same section because
//                          authors conflate the two otherwise)
//   3. Inputs & Sources    inputs
//   4. Sequential Steps    canonical_steps, with optional IF/ELSE per step
//   5. Guardrails          guardrails
//   6. Approval Gates      approval_gates
//   7. Few-Shot Examples   few_shot_examples
//
// plus the two §11.5 fields that are not authoring components but do belong
// to the same row: required_criteria (the success rubric — mandatory, the
// backend rejects an empty one) and known_assumptions (scar tissue).

interface FormState {
  name: string;
  description: string;
  is_active: boolean;
  version: string;
  status: "Active" | "Experimental" | "Deprecated";

  objective: string;
  when_to_use: string;
  target_persona: string;
  out_of_scope: PlaybookOutOfScope[];
  inputs: PlaybookInput[];
  canonical_steps: PlaybookStep[];
  guardrails: PlaybookGuardrail[];
  approval_gates: PlaybookApprovalGate[];
  few_shot_examples: PlaybookExample[];
  required_criteria: string[];
  known_assumptions: PlaybookAssumption[];
}

function emptyForm(): FormState {
  return {
    name: "",
    description: "",
    is_active: true,
    version: "1.0.0",
    status: "Active",
    objective: "",
    when_to_use: "",
    target_persona: "",
    out_of_scope: [],
    inputs: [],
    canonical_steps: [{ title: "", detail: "", condition: null, else_detail: null }],
    guardrails: [],
    approval_gates: [],
    few_shot_examples: [],
    required_criteria: [],
    known_assumptions: [],
  };
}

function formFromPlaybook(p: Playbook): FormState {
  return {
    name: p.name,
    description: p.description ?? "",
    is_active: p.is_active,
    version: p.version,
    status: (p.status as FormState["status"]) ?? "Active",
    objective: p.objective ?? "",
    when_to_use: p.when_to_use ?? "",
    target_persona: p.target_persona ?? "",
    out_of_scope: p.out_of_scope ?? [],
    inputs: p.inputs ?? [],
    // A playbook mined by the promotion ladder can legitimately have zero
    // steps; the editor always shows at least one blank row so there is
    // something to type into.
    canonical_steps: p.canonical_steps?.length ? p.canonical_steps : [{ title: "", detail: "", condition: null, else_detail: null }],
    guardrails: p.guardrails ?? [],
    approval_gates: p.approval_gates ?? [],
    few_shot_examples: p.few_shot_examples ?? [],
    required_criteria: p.required_criteria ?? [],
    known_assumptions: p.known_assumptions ?? [],
  };
}

const INPUT_KINDS: { value: PlaybookInputKind; label: string }[] = [
  { value: "data_property", label: "data property" },
  { value: "datasource", label: "datasource" },
  { value: "tool", label: "tool" },
  { value: "skill", label: "skill" },
];

/** Generic add/update/remove for any of the repeated component lists, so
 *  each of the six repeaters below is three one-liners instead of three
 *  near-identical closures. */
function listOps<T>(items: T[], set: (next: T[]) => void) {
  return {
    add: (blank: T) => set([...items, blank]),
    update: (i: number, patch: Partial<T>) => set(items.map((x, j) => (j === i ? { ...x, ...patch } : x))),
    remove: (i: number) => set(items.filter((_, j) => j !== i)),
  };
}

export default function PlaybooksPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState<Playbook[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [panelMode, setPanelMode] = useState<"closed" | "create" | "edit">("closed");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm());
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setItems(await playbooksApi.list());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load playbooks");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function openCreate() {
    setPanelMode("create");
    setEditingId(null);
    setForm(emptyForm());
    setFormError(null);
  }

  function openEdit(p: Playbook) {
    setPanelMode("edit");
    setEditingId(p.id);
    setForm(formFromPlaybook(p));
    setFormError(null);
  }

  function closePanel() {
    setPanelMode("closed");
    setEditingId(null);
    setFormError(null);
  }

  const steps = listOps(form.canonical_steps, (canonical_steps) => setForm({ ...form, canonical_steps }));
  const scope = listOps(form.out_of_scope, (out_of_scope) => setForm({ ...form, out_of_scope }));
  const inputs = listOps(form.inputs, (next) => setForm({ ...form, inputs: next }));
  const rails = listOps(form.guardrails, (guardrails) => setForm({ ...form, guardrails }));
  const gates = listOps(form.approval_gates, (approval_gates) => setForm({ ...form, approval_gates }));
  const examples = listOps(form.few_shot_examples, (few_shot_examples) => setForm({ ...form, few_shot_examples }));
  const assumptions = listOps(form.known_assumptions, (known_assumptions) => setForm({ ...form, known_assumptions }));

  function updateExchange(exampleIndex: number, exchangeIndex: number, patch: Partial<PlaybookExchange>) {
    examples.update(exampleIndex, {
      exchanges: form.few_shot_examples[exampleIndex].exchanges.map((x, j) =>
        j === exchangeIndex ? { ...x, ...patch } : x,
      ),
    });
  }

  function addExchange(exampleIndex: number) {
    const existing = form.few_shot_examples[exampleIndex].exchanges;
    // Alternate speakers by default — the next turn after a user line is
    // almost always the agent, and vice versa. (Indexed rather than .at(-1):
    // this project's tsconfig lib target predates ES2022.)
    const nextRole: PlaybookExchange["role"] =
      existing.length > 0 && existing[existing.length - 1].role === "user" ? "agent" : "user";
    examples.update(exampleIndex, {
      exchanges: [...existing, { role: nextRole, content: "", internal_note: "" }],
    });
  }

  function removeExchange(exampleIndex: number, exchangeIndex: number) {
    examples.update(exampleIndex, {
      exchanges: form.few_shot_examples[exampleIndex].exchanges.filter((_, j) => j !== exchangeIndex),
    });
  }

  async function handleSubmit(e?: FormEvent) {
    e?.preventDefault();
    setFormError(null);

    // Mirror the two server-side constraints here so the author gets the
    // message next to the field rather than as a 422 blob. The backend
    // still enforces both — this is convenience, not the boundary.
    if (!form.name.trim()) {
      setFormError("Name is required.");
      return;
    }
    if (!form.when_to_use.trim()) {
      setFormError("‘When to use’ is required — it is how the Planner decides to reach for this playbook.");
      return;
    }
    if (form.required_criteria.length === 0) {
      setFormError("Add at least one success criterion. A playbook nobody can tell succeeded is not a playbook.");
      return;
    }

    const payload = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      is_active: form.is_active,
      version: form.version,
      status: form.status,
      objective: form.objective,
      when_to_use: form.when_to_use,
      target_persona: form.target_persona,
      // Drop rows the author added but left blank rather than sending empty
      // strings that would fail min_length validation server-side.
      out_of_scope: form.out_of_scope.filter((o) => o.topic.trim()),
      inputs: form.inputs.filter((i) => i.name.trim()),
      canonical_steps: form.canonical_steps.filter((s) => s.title.trim()),
      guardrails: form.guardrails.filter((g) => g.rule.trim()),
      approval_gates: form.approval_gates.filter((g) => g.name.trim()),
      few_shot_examples: form.few_shot_examples
        .filter((x) => x.title.trim())
        .map((x) => ({ ...x, exchanges: x.exchanges.filter((ex) => ex.content.trim()) })),
      required_criteria: form.required_criteria,
      known_assumptions: form.known_assumptions.filter((a) => a.assumption.trim()),
    };

    setSubmitting(true);
    try {
      if (panelMode === "create") {
        const created = await playbooksApi.create(payload);
        await load();
        openEdit(created);
      } else if (editingId) {
        await playbooksApi.update(editingId, payload);
        await load();
      }
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Save failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this playbook?")) return;
    try {
      await playbooksApi.remove(id);
      if (editingId === id) closePanel();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    }
  }

  async function handleFork(id: string) {
    try {
      const forked = await playbooksApi.fork(id);
      await load();
      openEdit(forked);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Fork failed");
    }
  }

  // A platform-shared row (tenant_id === null) is readable by every tenant
  // but editable by nobody — the same convention every other registry uses.
  // Forking is the supported way to customize one.
  const editingRow = editingId ? items.find((p) => p.id === editingId) ?? null : null;
  const isShared = editingRow?.tenant_id === null;
  const canSave = isAdmin && !isShared;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Playbooks</h1>
          <p>
            A canonical decomposition of a recurring process — scope, goal, approved inputs, ordered steps, guardrails,
            approval gates and sample dialogue. Read by the Planner when it recognises a matching task.
          </p>
        </div>
        {isAdmin && (
          <button className="btn btn-primary" onClick={openCreate}>
            New Playbook
          </button>
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
            <p className="empty-state">No playbooks yet.</p>
          ) : (
            items.map((item) => (
              <div
                key={item.id}
                className={`rowbtn ${editingId === item.id ? "selected" : ""}`}
                onClick={() => openEdit(item)}
              >
                <span className="rowbtn-title">{item.name}</span>
                <div className="rowbtn-tags">
                  <span className={`tag ${item.is_active ? "tag-accent" : "tag-neutral"}`}>
                    {item.is_active ? "active" : "inactive"}
                  </span>
                  {item.tenant_id === null && <span className="tag tag-neutral">shared</span>}
                  <span className="tag tag-neutral">{item.canonical_steps?.length ?? 0} steps</span>
                  <span className="text-muted" style={{ fontSize: 11.5 }}>v{item.version}</span>
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
          {panelMode === "closed" ? (
            <p className="registry-panel-placeholder">
              {isAdmin ? "Select a playbook to view details, or create a new one." : "Select a playbook to view details."}
            </p>
          ) : (
            <>
              <div className="detail-header">
                <div>
                  <h6 className="detail-kicker">Playbook</h6>
                  <h2>{panelMode === "create" ? "New Playbook" : form.name || "Edit Playbook"}</h2>
                </div>
              </div>

              {isShared && (
                <p className="text-muted" style={{ marginBottom: 12 }}>
                  This is a platform-shared playbook — read-only. Fork it to make an editable copy your tenant owns.
                </p>
              )}

              <form onSubmit={handleSubmit}>
                {/* 1 — Name & Scope */}
                <h3 className="section-heading">1 · Name &amp; scope</h3>
                <div className="field">
                  <label>Name</label>
                  <input
                    className="input"
                    required
                    placeholder="e.g. Premium Subscription Billing"
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                  />
                </div>
                <div className="field">
                  <label>Description</label>
                  <textarea
                    className="input"
                    rows={2}
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                  />
                </div>
                <div className="field">
                  <label>Target persona</label>
                  <textarea
                    className="input"
                    rows={2}
                    placeholder="Polite, empathetic, solution-oriented. Short conversational sentences."
                    value={form.target_persona}
                    onChange={(e) => setForm({ ...form, target_persona: e.target.value })}
                  />
                  <small className="text-muted">How the agent should sound while running this process.</small>
                </div>

                <label>Out of scope</label>
                {form.out_of_scope.map((o, i) => (
                  <div key={i} className="field-row" style={{ alignItems: "flex-end", marginBottom: 8 }}>
                    <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                      <label>Topic</label>
                      <input
                        className="input"
                        placeholder="Technical streaming issues"
                        value={o.topic}
                        onChange={(e) => scope.update(i, { topic: e.target.value })}
                      />
                    </div>
                    <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                      <label>Hand off to</label>
                      <input
                        className="input"
                        placeholder="Technical Support Playbook"
                        value={o.handoff_to}
                        onChange={(e) => scope.update(i, { handoff_to: e.target.value })}
                      />
                    </div>
                    <button type="button" className="btn-secondary btn" onClick={() => scope.remove(i)}>
                      &times;
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="btn-secondary btn"
                  onClick={() => scope.add({ topic: "", handoff_to: "" })}
                  style={{ marginBottom: 16 }}
                >
                  + Add out-of-scope boundary
                </button>

                {/* 2 — High-level goal */}
                <h3 className="section-heading">2 · High-level goal</h3>
                <div className="field">
                  <label>Objective</label>
                  <textarea
                    className="input"
                    rows={2}
                    placeholder="Resolve billing discrepancies, process authorized refunds, retain users considering cancellation."
                    value={form.objective}
                    onChange={(e) => setForm({ ...form, objective: e.target.value })}
                  />
                  <small className="text-muted">What the agent must achieve during the interaction.</small>
                </div>
                <div className="field">
                  <label>When to use *</label>
                  <textarea
                    className="input"
                    rows={2}
                    placeholder="A customer disputes a charge, requests a refund, or asks to cancel a paid plan."
                    value={form.when_to_use}
                    onChange={(e) => setForm({ ...form, when_to_use: e.target.value })}
                  />
                  <small className="text-muted">
                    How the Planner decides to reach for this playbook at all — a selection signal, not the goal.
                  </small>
                </div>

                {/* 3 — Inputs & sources */}
                <h3 className="section-heading">3 · Inputs &amp; sources</h3>
                <p className="text-muted" style={{ marginTop: -6, marginBottom: 10, fontSize: 12.5 }}>
                  Anything not listed here is, by this playbook's own contract, unavailable to the agent.
                </p>
                {form.inputs.map((inp, i) => (
                  <div key={i} className="sectioncard" style={{ marginBottom: 10 }}>
                    <div className="field-row" style={{ alignItems: "flex-end" }}>
                      <div className="field" style={{ flex: "0 0 200px", marginBottom: 0 }}>
                        <label>Name</label>
                        <input
                          className="input"
                          placeholder="Billing_History"
                          value={inp.name}
                          onChange={(e) => inputs.update(i, { name: e.target.value })}
                        />
                      </div>
                      <div className="field" style={{ flex: "0 0 160px", marginBottom: 0 }}>
                        <label>Kind</label>
                        <select
                          className="input"
                          value={inp.kind}
                          onChange={(e) => inputs.update(i, { kind: e.target.value as PlaybookInputKind })}
                        >
                          {INPUT_KINDS.map((k) => (
                            <option key={k.value} value={k.value}>
                              {k.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                        <label>Description</label>
                        <input
                          className="input"
                          placeholder="Past invoices, failed charges, applied credits"
                          value={inp.description}
                          onChange={(e) => inputs.update(i, { description: e.target.value })}
                        />
                      </div>
                      <button type="button" className="btn-secondary btn" onClick={() => inputs.remove(i)}>
                        &times;
                      </button>
                    </div>
                  </div>
                ))}
                <button
                  type="button"
                  className="btn-secondary btn"
                  onClick={() => inputs.add({ name: "", kind: "data_property", description: "", ref_id: null })}
                  style={{ marginBottom: 16 }}
                >
                  + Add input
                </button>

                {/* 4 — Sequential steps */}
                <h3 className="section-heading">4 · Sequential steps</h3>
                {form.canonical_steps.map((s, i) => {
                  const conditional = s.condition != null;
                  return (
                    <div key={i} className="sectioncard" style={{ marginBottom: 10 }}>
                      <div className="field-row" style={{ alignItems: "flex-end" }}>
                        <div className="field" style={{ flex: "0 0 40px", marginBottom: 0 }}>
                          <label>#</label>
                          <input className="input" value={i + 1} readOnly disabled />
                        </div>
                        <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                          <label>Title</label>
                          <input
                            className="input"
                            placeholder="Check eligibility rules"
                            value={s.title}
                            onChange={(e) => steps.update(i, { title: e.target.value })}
                          />
                        </div>
                      </div>

                      <div className="field" style={{ marginTop: 10 }}>
                        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <input
                            type="checkbox"
                            checked={conditional}
                            onChange={(e) =>
                              steps.update(i,
                                e.target.checked
                                  ? { condition: "", else_detail: "" }
                                  : { condition: null, else_detail: null },
                              )
                            }
                          />
                          Conditional step (IF / ELSE)
                        </label>
                      </div>

                      {conditional && (
                        <div className="field">
                          <label>IF</label>
                          <textarea
                            className="input"
                            rows={2}
                            placeholder="the charge occurred within the last 14 days AND the user streamed under 2 hours"
                            value={s.condition ?? ""}
                            onChange={(e) => steps.update(i, { condition: e.target.value })}
                          />
                        </div>
                      )}

                      <div className="field">
                        <label>{conditional ? "THEN" : "Detail"}</label>
                        <textarea
                          className="input"
                          rows={2}
                          placeholder={conditional ? "mark as Eligible" : "Verify identity, then identify the charge date and amount."}
                          value={s.detail}
                          onChange={(e) => steps.update(i, { detail: e.target.value })}
                        />
                      </div>

                      {conditional && (
                        <div className="field">
                          <label>ELSE</label>
                          <textarea
                            className="input"
                            rows={2}
                            placeholder="mark as Ineligible"
                            value={s.else_detail ?? ""}
                            onChange={(e) => steps.update(i, { else_detail: e.target.value })}
                          />
                        </div>
                      )}

                      {form.canonical_steps.length > 1 && (
                        <button type="button" className="btn-secondary btn" onClick={() => steps.remove(i)}>
                          Remove step
                        </button>
                      )}
                    </div>
                  );
                })}
                <button
                  type="button"
                  className="btn-secondary btn"
                  onClick={() => steps.add({ title: "", detail: "", condition: null, else_detail: null })}
                  style={{ marginBottom: 16 }}
                >
                  + Add step
                </button>

                {/* 5 — Guardrails */}
                <h3 className="section-heading">5 · Guardrails &amp; banned moves</h3>
                <p className="text-muted" style={{ marginTop: -6, marginBottom: 10, fontSize: 12.5 }}>
                  Recorded and shown to reviewers. Not yet enforced at runtime — enforcement belongs to the Hook engine
                  and is not wired to playbooks in this build.
                </p>
                {form.guardrails.map((g, i) => (
                  <div key={i} className="field-row" style={{ alignItems: "flex-end", marginBottom: 8 }}>
                    <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                      <label>Rule</label>
                      <input
                        className="input"
                        placeholder="Never promise a refund before running the eligibility calculation"
                        value={g.rule}
                        onChange={(e) => rails.update(i, { rule: e.target.value })}
                      />
                    </div>
                    <div className="field" style={{ flex: "0 0 120px", marginBottom: 0 }}>
                      <label>Severity</label>
                      <select
                        className="input"
                        value={g.severity}
                        onChange={(e) => rails.update(i, { severity: e.target.value as PlaybookGuardrail["severity"] })}
                      >
                        <option value="block">block</option>
                        <option value="warn">warn</option>
                      </select>
                    </div>
                    <button type="button" className="btn-secondary btn" onClick={() => rails.remove(i)}>
                      &times;
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="btn-secondary btn"
                  onClick={() => rails.add({ rule: "", severity: "block" })}
                  style={{ marginBottom: 16 }}
                >
                  + Add guardrail
                </button>

                {/* 6 — Approval gates */}
                <h3 className="section-heading">6 · Approval gates</h3>
                {form.approval_gates.map((g, i) => (
                  <div key={i} className="sectioncard" style={{ marginBottom: 10 }}>
                    <div className="field-row" style={{ alignItems: "flex-end" }}>
                      <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                        <label>Gate</label>
                        <input
                          className="input"
                          placeholder="Refund over limit"
                          value={g.name}
                          onChange={(e) => gates.update(i, { name: e.target.value })}
                        />
                      </div>
                      <div className="field" style={{ flex: "0 0 160px", marginBottom: 0 }}>
                        <label>Threshold</label>
                        <input
                          className="input"
                          placeholder="₹1,500"
                          value={g.threshold}
                          onChange={(e) => gates.update(i, { threshold: e.target.value })}
                        />
                      </div>
                      <div className="field" style={{ flex: "0 0 180px", marginBottom: 0 }}>
                        <label>Approver</label>
                        <input
                          className="input"
                          placeholder="Billing supervisor"
                          value={g.approver}
                          onChange={(e) => gates.update(i, { approver: e.target.value })}
                        />
                      </div>
                      <button type="button" className="btn-secondary btn" onClick={() => gates.remove(i)}>
                        &times;
                      </button>
                    </div>
                    <div className="field" style={{ marginTop: 10, marginBottom: 0 }}>
                      <label>Pause when</label>
                      <input
                        className="input"
                        placeholder="Refund amount exceeds the Refund_Tool limit"
                        value={g.condition}
                        onChange={(e) => gates.update(i, { condition: e.target.value })}
                      />
                    </div>
                  </div>
                ))}
                <button
                  type="button"
                  className="btn-secondary btn"
                  onClick={() => gates.add({ name: "", condition: "", approver: "", threshold: "" })}
                  style={{ marginBottom: 16 }}
                >
                  + Add approval gate
                </button>

                {/* 7 — Few-shot examples */}
                <h3 className="section-heading">7 · Few-shot examples</h3>
                {form.few_shot_examples.map((ex, i) => (
                  <div key={i} className="sectioncard" style={{ marginBottom: 10 }}>
                    <div className="field-row" style={{ alignItems: "flex-end" }}>
                      <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                        <label>Scenario</label>
                        <input
                          className="input"
                          placeholder="Eligible refund, happy path"
                          value={ex.title}
                          onChange={(e) => examples.update(i, { title: e.target.value })}
                        />
                      </div>
                      <button type="button" className="btn-secondary btn" onClick={() => examples.remove(i)}>
                        &times;
                      </button>
                    </div>

                    {ex.exchanges.map((x, j) => (
                      <div key={j} className="field-row" style={{ alignItems: "flex-start", marginTop: 10 }}>
                        <div className="field" style={{ flex: "0 0 110px", marginBottom: 0 }}>
                          <label>Speaker</label>
                          <select
                            className="input"
                            value={x.role}
                            onChange={(e) => updateExchange(i, j, { role: e.target.value as PlaybookExchange["role"] })}
                          >
                            <option value="user">user</option>
                            <option value="agent">agent</option>
                          </select>
                        </div>
                        <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                          <label>Says</label>
                          <textarea
                            className="input"
                            rows={2}
                            value={x.content}
                            onChange={(e) => updateExchange(i, j, { content: e.target.value })}
                          />
                          {x.role === "agent" && (
                            <input
                              className="input"
                              style={{ marginTop: 6, fontSize: 12.5 }}
                              placeholder="Internal note — e.g. (Tool check: charge 24h ago, 0 min streamed → Eligible)"
                              value={x.internal_note}
                              onChange={(e) => updateExchange(i, j, { internal_note: e.target.value })}
                            />
                          )}
                        </div>
                        <button type="button" className="btn-secondary btn" onClick={() => removeExchange(i, j)}>
                          &times;
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      className="btn-secondary btn"
                      style={{ marginTop: 10 }}
                      onClick={() => addExchange(i)}
                    >
                      + Add turn
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="btn-secondary btn"
                  onClick={() => examples.add({ title: "", exchanges: [{ role: "user", content: "", internal_note: "" }] })}
                  style={{ marginBottom: 16 }}
                >
                  + Add example
                </button>

                {/* §11.5 fields that are not authoring components */}
                <h3 className="section-heading">Success criteria *</h3>
                <TagInput
                  label=""
                  values={form.required_criteria}
                  onChange={(required_criteria) => setForm({ ...form, required_criteria })}
                  placeholder="Refund decision matches eligibility rules, ..."
                  helpText="At least one is required — this is the rubric the Critic scores the run against."
                />

                <h3 className="section-heading">Known assumptions</h3>
                <p className="text-muted" style={{ marginTop: -6, marginBottom: 10, fontSize: 12.5 }}>
                  The things that historically break. Filled in by whoever noticed a recurring failure.
                </p>
                {form.known_assumptions.map((a, i) => (
                  <div key={i} className="field-row" style={{ alignItems: "flex-end", marginBottom: 8 }}>
                    <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                      <label>Assumption</label>
                      <input
                        className="input"
                        value={a.assumption}
                        onChange={(e) => assumptions.update(i, { assumption: e.target.value })}
                      />
                    </div>
                    <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                      <label>Evidence</label>
                      <input
                        className="input"
                        value={a.evidence_note}
                        onChange={(e) => assumptions.update(i, { evidence_note: e.target.value })}
                      />
                    </div>
                    <button type="button" className="btn-secondary btn" onClick={() => assumptions.remove(i)}>
                      &times;
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="btn-secondary btn"
                  onClick={() => assumptions.add({ assumption: "", evidence_note: "" })}
                  style={{ marginBottom: 16 }}
                >
                  + Add assumption
                </button>

                <h3 className="section-heading">Lifecycle</h3>
                <div className="field-row">
                  <div className="field">
                    <label>Version</label>
                    <input className="input" value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} />
                  </div>
                  <div className="field">
                    <label>Status</label>
                    <select
                      className="input"
                      value={form.status}
                      onChange={(e) => setForm({ ...form, status: e.target.value as FormState["status"] })}
                    >
                      <option value="Active">Active</option>
                      <option value="Experimental">Experimental</option>
                      <option value="Deprecated">Deprecated</option>
                    </select>
                  </div>
                </div>
                <div className="field" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="checkbox"
                    id="pb_is_active"
                    checked={form.is_active}
                    onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                  />
                  <label htmlFor="pb_is_active" style={{ margin: 0 }}>Active</label>
                </div>
              </form>

              {formError && <p className="error-text">{formError}</p>}

              {isAdmin && (
                <div className="panel-actions">
                  <div>
                    {editingId && !isShared && (
                      <button type="button" className="btn btn-danger" onClick={() => handleDelete(editingId)}>
                        Delete
                      </button>
                    )}
                    {editingId && isShared && (
                      <button type="button" className="btn btn-secondary" onClick={() => handleFork(editingId)}>
                        Fork into my tenant
                      </button>
                    )}
                  </div>
                  <div className="panel-actions-right">
                    <button type="button" className="btn btn-secondary" onClick={closePanel}>
                      Close
                    </button>
                    {canSave && (
                      <button type="button" className="btn btn-primary" disabled={submitting} onClick={() => handleSubmit()}>
                        {submitting ? "Saving..." : "Save"}
                      </button>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
