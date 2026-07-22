import { KeyboardEvent, useState } from "react";

interface Props {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  helpText?: string;
}

/** Small chip-style multi-value text input, shared by any registry form that
 * needs a free-text list (tags, permissions, requires_env, ...). Enter or
 * comma commits the current text as a new chip; backspace on an empty input
 * removes the last chip. */
export default function TagInput({ label, values, onChange, placeholder, helpText }: Props) {
  const [draft, setDraft] = useState("");

  function commit(raw: string) {
    const value = raw.trim();
    if (!value) return;
    if (!values.includes(value)) onChange([...values, value]);
    setDraft("");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit(draft);
    } else if (e.key === "Backspace" && draft === "" && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  }

  function remove(value: string) {
    onChange(values.filter((v) => v !== value));
  }

  return (
    <div className="field">
      <label>{label}</label>
      <div className="tag-input-box">
        {values.map((v) => (
          <span key={v} className="tag tag-neutral tag-removable">
            {v}
            <button type="button" onClick={() => remove(v)} aria-label={`Remove ${v}`}>
              &times;
            </button>
          </span>
        ))}
        <input
          className="tag-input-field"
          value={draft}
          placeholder={values.length === 0 ? placeholder : ""}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={() => commit(draft)}
        />
      </div>
      {helpText && (
        <p className="composer-overlay-desc" style={{ marginTop: 4 }}>
          {helpText}
        </p>
      )}
    </div>
  );
}
