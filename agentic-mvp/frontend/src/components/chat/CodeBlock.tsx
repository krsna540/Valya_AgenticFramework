import { useState } from "react";
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
}

const ARTIFACT_LANGUAGES = new Set(["html", "svg"]);
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

export default function CodeBlock({ language, code }: CodeBlockProps) {
  const isArtifact = ARTIFACT_LANGUAGES.has(language.toLowerCase());
  const [tab, setTab] = useState<"source" | "preview">(isArtifact ? "preview" : "source");
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(code).catch(() => undefined);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  const previewDoc =
    language.toLowerCase() === "svg"
      ? `<!doctype html><html><body style="margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh;">${code}</body></html>`
      : code;

  return (
    <div className="code-block">
      <div className="code-block-header">
        <span className="code-lang">{language || "text"}</span>
        <div className="code-block-actions">
          {isArtifact && (
            <div className="tab-switch">
              <button
                type="button"
                className={tab === "source" ? "active" : ""}
                onClick={() => setTab("source")}
              >
                Source
              </button>
              <button
                type="button"
                className={tab === "preview" ? "active" : ""}
                onClick={() => setTab("preview")}
              >
                Preview
              </button>
            </div>
          )}
          <button type="button" className="copy-btn" onClick={handleCopy}>
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>

      {isArtifact && tab === "preview" ? (
        // Sandboxed with scripts allowed but NOT allow-same-origin, so
        // artifact code can't reach the parent app's cookies/localStorage/DOM.
        <iframe
          className="artifact-frame"
          sandbox="allow-scripts"
          srcDoc={previewDoc}
          title="Artifact preview"
        />
      ) : REGISTERED_LANGUAGES.has(language.toLowerCase()) ? (
        <SyntaxHighlighter
          language={language.toLowerCase()}
          style={oneDark}
          customStyle={{ margin: 0, borderRadius: 0, fontSize: 13 }}
        >
          {code}
        </SyntaxHighlighter>
      ) : (
        <pre className="code-block-plain">
          <code>{code}</code>
        </pre>
      )}
    </div>
  );
}
