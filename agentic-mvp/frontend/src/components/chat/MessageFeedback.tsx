import { useState } from "react";
import type { MessageFeedback as FeedbackValue } from "../../types";
import { chatApi } from "../../api/chat";

const REASON_CHIPS = ["Not helpful", "Factually wrong", "Too long", "Didn't follow instructions", "Other"];

interface Props {
  messageId: string;
  initialFeedback?: FeedbackValue;
  initialReason?: string | null;
}

export default function MessageFeedbackControls({ messageId, initialFeedback = null, initialReason = null }: Props) {
  const [feedback, setFeedback] = useState<FeedbackValue>(initialFeedback ?? null);
  const [reason, setReason] = useState<string | null>(initialReason ?? null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [draft, setDraft] = useState("");

  function persist(next: FeedbackValue, nextReason: string | null) {
    chatApi.setFeedback(messageId, next, nextReason).catch(() => {
      // best-effort — local state already reflects the user's intent
    });
  }

  function toggleLike() {
    const next: FeedbackValue = feedback === "like" ? null : "like";
    setFeedback(next);
    setReason(null);
    setPickerOpen(false);
    persist(next, null);
  }

  function toggleDislike() {
    if (feedback === "dislike") {
      setFeedback(null);
      setReason(null);
      setPickerOpen(false);
      persist(null, null);
      return;
    }
    setFeedback("dislike");
    setPickerOpen(true);
    persist("dislike", reason);
  }

  function pickChip(chip: string) {
    setReason(chip);
    setDraft("");
    setPickerOpen(false);
    persist("dislike", chip);
  }

  function submitDraft() {
    const text = draft.trim();
    setReason(text || null);
    setPickerOpen(false);
    persist("dislike", text || null);
  }

  return (
    <div className={`qa-feedback${feedback ? " has-feedback" : ""}`}>
      <button
        type="button"
        className={`qa-tool qa-feedback-btn${feedback === "like" ? " active" : ""}`}
        aria-label="Like message"
        aria-pressed={feedback === "like"}
        onClick={toggleLike}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill={feedback === "like" ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M7 22V11M2 13v7a2 2 0 0 0 2 2h12.5a2 2 0 0 0 2-1.6l1.4-7A2 2 0 0 0 18 11h-5V4a2 2 0 0 0-2-2L7 11" />
        </svg>
      </button>
      <div className="qa-feedback-dislike-wrap">
        <button
          type="button"
          className={`qa-tool qa-feedback-btn${feedback === "dislike" ? " active" : ""}`}
          aria-label="Dislike message"
          aria-pressed={feedback === "dislike"}
          onClick={toggleDislike}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill={feedback === "dislike" ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M17 2v11M22 11V4a2 2 0 0 0-2-2H7.5a2 2 0 0 0-2 1.6l-1.4 7A2 2 0 0 0 6 13h5v7a2 2 0 0 0 2 2l5-9" />
          </svg>
        </button>

        {pickerOpen && (
          <div className="qa-reason-picker" role="dialog" aria-label="Why wasn't this helpful?">
            <div className="qa-reason-chips">
              {REASON_CHIPS.map((chip) => (
                <button type="button" key={chip} className="qa-reason-chip" onClick={() => pickChip(chip)}>
                  {chip}
                </button>
              ))}
            </div>
            <div className="qa-reason-free">
              <input
                className="input"
                placeholder="Tell us more (optional)"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") submitDraft();
                  if (e.key === "Escape") setPickerOpen(false);
                }}
              />
              <button type="button" className="btn btn-primary btn-sm" onClick={submitDraft}>
                Submit
              </button>
            </div>
          </div>
        )}

        {!pickerOpen && feedback === "dislike" && reason && (
          <span className="qa-feedback-reason-tag" title={reason}>
            {reason}
          </span>
        )}
      </div>
    </div>
  );
}
