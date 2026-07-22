import { dump, load } from "js-yaml";

/** Renders a plain object as YAML text for the read-only/editable YAML view
 * every registry side panel offers alongside its form fields. */
export function toYamlText(obj: unknown): string {
  return dump(obj, { noRefs: true, lineWidth: 100 });
}

/** Parses YAML text back into a plain object. Throws on invalid YAML —
 * callers should catch and surface a form error. */
export function fromYamlText(text: string): Record<string, unknown> {
  const parsed = load(text);
  if (parsed === null || parsed === undefined) return {};
  if (typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("YAML must describe an object (key: value pairs)");
  }
  return parsed as Record<string, unknown>;
}
