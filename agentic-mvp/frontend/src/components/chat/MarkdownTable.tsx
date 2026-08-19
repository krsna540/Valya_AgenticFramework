import { useRef, useState } from "react";
import type { ReactNode } from "react";

function csvEscape(value: string): string {
  if (/[",\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function tableToCsv(table: HTMLTableElement): string {
  const rows = Array.from(table.rows);
  return rows
    .map((row) => Array.from(row.cells).map((cell) => csvEscape(cell.textContent?.trim() ?? "")).join(","))
    .join("\n");
}

export default function MarkdownTable({ children }: { children?: ReactNode }) {
  const ref = useRef<HTMLTableElement>(null);
  const [copied, setCopied] = useState(false);

  function handleCopyCsv() {
    if (!ref.current) return;
    navigator.clipboard.writeText(tableToCsv(ref.current)).catch(() => undefined);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="md-table-wrap">
      <div className="md-table-toolbar">
        <button type="button" className="copy-btn" onClick={handleCopyCsv}>
          {copied ? "Copied" : "Copy as CSV"}
        </button>
      </div>
      <div className="md-table-scroll">
        <table ref={ref}>{children}</table>
      </div>
    </div>
  );
}
