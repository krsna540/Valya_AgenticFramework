import type { SiblingGroup } from "../../types";

interface Props {
  siblings: SiblingGroup;
  onSelect: (siblingId: string) => void;
}

export default function BranchNav({ siblings, onSelect }: Props) {
  if (siblings.siblings.length <= 1) return null;

  const { active_index, siblings: list } = siblings;

  return (
    <div className="branch-nav">
      <button
        type="button"
        className="branch-nav-btn"
        disabled={active_index <= 0}
        onClick={() => onSelect(list[active_index - 1].id)}
      >
        ‹
      </button>
      <span>
        Try {active_index + 1}/{list.length}
      </span>
      <button
        type="button"
        className="branch-nav-btn"
        disabled={active_index >= list.length - 1}
        onClick={() => onSelect(list[active_index + 1].id)}
      >
        ›
      </button>
    </div>
  );
}
