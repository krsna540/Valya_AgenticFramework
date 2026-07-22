import type { Citation } from "../../types";

interface Props {
  index: number;
  citation?: Citation;
  onOpen: (citation: Citation) => void;
}

export default function CitationBadge({ index, citation, onOpen }: Props) {
  if (!citation) {
    return <>[{index}]</>;
  }
  return (
    <button
      type="button"
      className="citation-badge"
      title={citation.source}
      onClick={() => onOpen(citation)}
    >
      {index}
    </button>
  );
}
