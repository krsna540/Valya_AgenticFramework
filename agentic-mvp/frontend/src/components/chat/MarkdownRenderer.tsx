import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import type { Components } from "react-markdown";
import CodeBlock from "./CodeBlock";
import CitationBadge from "./CitationBadge";
import type { Citation } from "../../types";

const CITATION_RE = /\[(\d+)\]/g;

/**
 * Walks rendered children looking for plain-text citation markers like "[1]"
 * and swaps them for interactive CitationBadge elements, without touching
 * non-text children (nested elements, code spans, etc.) so we only ever
 * intercept prose, never markup.
 */
function injectCitations(
  children: ReactNode,
  citations: Citation[],
  onCitationClick: (c: Citation) => void,
): ReactNode {
  if (citations.length === 0) return children;

  const process = (node: ReactNode, key: string): ReactNode => {
    if (typeof node === "string") {
      const parts: ReactNode[] = [];
      let lastIndex = 0;
      let match: RegExpExecArray | null;
      CITATION_RE.lastIndex = 0;
      let i = 0;
      while ((match = CITATION_RE.exec(node))) {
        const n = parseInt(match[1], 10);
        if (n < 1 || n > citations.length) continue;
        if (match.index > lastIndex) parts.push(node.slice(lastIndex, match.index));
        parts.push(
          <CitationBadge
            key={`${key}-cite-${i++}`}
            index={n}
            citation={citations[n - 1]}
            onOpen={onCitationClick}
          />,
        );
        lastIndex = CITATION_RE.lastIndex;
      }
      if (parts.length === 0) return node;
      if (lastIndex < node.length) parts.push(node.slice(lastIndex));
      return parts;
    }
    if (Array.isArray(node)) {
      return node.map((child, idx) => process(child, `${key}-${idx}`));
    }
    return node;
  };

  return process(children, "root");
}

interface Props {
  content: string;
  citations?: Citation[];
  onCitationClick?: (citation: Citation) => void;
}

// Note: we intentionally do NOT enable rehype-raw (which would let raw HTML
// in model output be parsed into real DOM elements). Without it,
// react-markdown treats any literal HTML tags in the text as plain escaped
// text, which is inherently XSS-safe. rehype-sanitize is kept as a defensive
// second layer in case raw-HTML support is ever added later — this plays the
// same "sanitization barrier" role the design doc describes for dompurify,
// but integrated into the markdown AST pipeline instead of a post-hoc string
// pass, which is the currently-recommended approach for this library combo.
export default function MarkdownRenderer({ content, citations = [], onCitationClick = () => {} }: Props) {
  const components: Components = {
    code({ className, children, ...rest }) {
      const match = /language-(\w+)/.exec(className || "");
      const text = String(children).replace(/\n$/, "");
      const isBlock = Boolean(match) || text.includes("\n");
      if (isBlock) {
        return <CodeBlock language={match?.[1] ?? "text"} code={text} />;
      }
      return (
        <code className={className} {...rest}>
          {children}
        </code>
      );
    },
    p({ children }) {
      return <p>{injectCitations(children, citations, onCitationClick)}</p>;
    },
    li({ children }) {
      return <li>{injectCitations(children, citations, onCitationClick)}</li>;
    },
    td({ children }) {
      return <td>{injectCitations(children, citations, onCitationClick)}</td>;
    },
  };

  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
