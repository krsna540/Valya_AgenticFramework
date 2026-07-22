import type { Citation } from "../../types";

interface Props {
  citation: Citation | null;
  onClose: () => void;
}

export default function CitationDrawer({ citation, onClose }: Props) {
  if (!citation) return null;

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <h3>{citation.source}</h3>
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
        <p className="drawer-snippet">{citation.snippet}</p>
      </div>
    </div>
  );
}
