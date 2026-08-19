import { useMemo, useState } from "react";
import { PrismLight as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import jsx from "react-syntax-highlighter/dist/esm/languages/prism/jsx";
import tsx from "react-syntax-highlighter/dist/esm/languages/prism/tsx";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import javascript from "react-syntax-highlighter/dist/esm/languages/prism/javascript";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import css from "react-syntax-highlighter/dist/esm/languages/prism/css";
import markup from "react-syntax-highlighter/dist/esm/languages/prism/markup";
import sql from "react-syntax-highlighter/dist/esm/languages/prism/sql";
import yaml from "react-syntax-highlighter/dist/esm/languages/prism/yaml";

// Only registering commonly-needed languages (instead of importing the full
// Prism bundle with ~200 languages) keeps the production bundle small — see
// the "chunks larger than 500kB" build warning this replaced.
SyntaxHighlighter.registerLanguage("jsx", jsx);
SyntaxHighlighter.registerLanguage("tsx", tsx);
SyntaxHighlighter.registerLanguage("typescript", typescript);
SyntaxHighlighter.registerLanguage("ts", typescript);
SyntaxHighlighter.registerLanguage("javascript", javascript);
SyntaxHighlighter.registerLanguage("js", javascript);
SyntaxHighlighter.registerLanguage("python", python);
SyntaxHighlighter.registerLanguage("py", python);
SyntaxHighlighter.registerLanguage("bash", bash);
SyntaxHighlighter.registerLanguage("sh", bash);
SyntaxHighlighter.registerLanguage("json", json);
SyntaxHighlighter.registerLanguage("css", css);
SyntaxHighlighter.registerLanguage("html", markup);
SyntaxHighlighter.registerLanguage("xml", markup);
SyntaxHighlighter.registerLanguage("svg", markup);
SyntaxHighlighter.registerLanguage("sql", sql);
SyntaxHighlighter.registerLanguage("yaml", yaml);
SyntaxHighlighter.registerLanguage("yml", yaml);

interface CodeBlockProps {
  language: string;
  code: string;
  /** true while the parent message is still streaming in. */
  streaming?: boolean;
}

const ARTIFACT_LANGUAGES = new Set(["html", "svg"]);
const DIFF_LANGUAGES = new Set(["diff", "patch"]);
const REGISTERED_LANGUAGES = new Set([
  "jsx",
  "tsx",
  "typescript",
  "ts",
  "javascript",
  "js",
  "python",
  "py",
  "bash",
  "sh",
  "json",
  "css",
  "html",
  "xml",
  "svg",
  "sql",
  "yaml",
  "yml",
]);

const EXTENSION_BY_LANGUAGE: Record<string, string> = {
  jsx: "jsx",
  tsx: "tsx",
  typescript: "ts",
  ts: "ts",
  javascript: "js",
  js: "js",
  python: "py",
  py: "py",
  bash: "sh",
  sh: "sh",
  json: "json",
  css: "css",
  html: "html",
  xml: "xml",
  svg: "svg",
  sql: "sql",
  yaml: "yaml",
  yml: "yml",
  diff: "diff",
  patch: "patch",
};

const COLLAPSE_LINE_THRESHOLD = 25;

function DiffBlock({ code, wrap }: { code: string; wrap: boolean }) {
  const lines = code.split("\n");
  return (
    <pre className={`code-block-diff${wrap ? " wrap" : ""}`}>
      {lines.map((line, i) => {
        const kind = line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : "ctx";
        return (
          <div key={i} className={`diff-line diff-${kind}`}>
            <code>{line || " "}</code>
          </div>
        );
      })}
    </pre>
  );
}

export default function CodeBlock({ language, code, streaming = false }: CodeBlockProps) {
  const lang = language.toLowerCase();
  const isArtifact = ARTIFACT_LANGUAGES.has(lang);
  const isDiff = DIFF_LANGUAGES.has(lang);
  const [tab, setTab] = useState<"source" | "preview">(isArtifact ? "preview" : "source");
  const [copied, setCopied] = useState(false);
  const [showLineNumbers, setShowLineNumbers] = useState(false);
  const [wrap, setWrap] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const lineCount = useMemo(() => code.split("\n").length, [code]);
  const collapsible = lineCount > COLLAPSE_LINE_THRESHOLD;
  const collapsed = collapsible && !expanded;

  function handleCopy() {
    navigator.clipboard.writeText(code).catch(() => undefined);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  function handleDownload() {
    const ext = EXTENSION_BY_LANGUAGE[lang] ?? "txt";
    const blob = new Blob([code], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `snippet.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const previewDoc =
    lang === "svg"
      ? `<!doctype html><html><body style="margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh;">${code}</body></html>`
      : code;

  return (
    <div className={`code-block${collapsed ? " collapsed" : ""}`}>
      <div className="code-block-header">
        <div className="code-block-header-left">
          <span className="code-lang">{language || "text"}</span>
          {streaming && (
            <span className="code-generating" title="Generating">
              <span className="code-generating-dot" />
              generating
            </span>
          )}
        </div>
        <div className="code-block-actions">
          {isArtifact && (
            <div className="tab-switch">
              <button type="button" className={tab === "source" ? "active" : ""} onClick={() => setTab("source")}>
                Source
              </button>
              <button type="button" className={tab === "preview" ? "active" : ""} onClick={() => setTab("preview")}>
                Preview
              </button>
            </div>
          )}
          {!isArtifact && !isDiff && (
            <>
              <button
                type="button"
                className={`icon-toggle-btn${showLineNumbers ? " active" : ""}`}
                title={showLineNumbers ? "Hide line numbers" : "Show line numbers"}
                aria-pressed={showLineNumbers}
                onClick={() => setShowLineNumbers((v) => !v)}
              >
                #
              </button>
              <button
                type="button"
                className={`icon-toggle-btn${wrap ? " active" : ""}`}
                title={wrap ? "Disable wrap" : "Wrap long lines"}
                aria-pressed={wrap}
                onClick={() => setWrap((v) => !v)}
              >
                ⤾
              </button>
            </>
          )}
          <button type="button" className="copy-btn" title="Download as file" onClick={handleDownload}>
            ↓
          </button>
          <button type="button" className="copy-btn" onClick={handleCopy}>
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>

      <div className="code-block-body">
        {isArtifact && tab === "preview" ? (
          // Sandboxed with scripts allowed but NOT allow-same-origin, so
          // artifact code can't reach the parent app's cookies/localStorage/DOM.
          <iframe className="artifact-frame" sandbox="allow-scripts" srcDoc={previewDoc} title="Artifact preview" />
        ) : isDiff ? (
          <DiffBlock code={code} wrap={wrap} />
        ) : REGISTERED_LANGUAGES.has(lang) ? (
          <SyntaxHighlighter
            language={lang}
            style={oneDark}
            showLineNumbers={showLineNumbers}
            wrapLongLines={wrap}
            customStyle={{ margin: 0, borderRadius: 0, fontSize: 13 }}
          >
            {code}
          </SyntaxHighlighter>
        ) : (
          <pre className={`code-block-plain${wrap ? "" : " nowrap"}`}>
            <code>{code}</code>
          </pre>
        )}
      </div>

      {collapsible && (
        <button type="button" className="code-block-expand" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Show less" : `Show ${lineCount - COLLAPSE_LINE_THRESHOLD} more lines`}
        </button>
      )}
    </div>
  );
}
