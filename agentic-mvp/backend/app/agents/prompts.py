"""Prompt construction for the three roles.

Kept out of the agent classes on purpose. Prompts change far more often than
control flow does, and mixing them means every prompt tweak touches a file
that also owns retry semantics and state transitions — which is how prompt
edits end up needing a careful review of graph logic.

Two conventions hold throughout:

* **Feedback is rendered as a checklist, not as prose.** A critic's
  objections reach the next attempt as an enumerated list of defects to fix.
  Burying them in a paragraph is the single most common reason a revision
  loop produces the same answer twice.

* **Language is stated in the system message, not appended to the user
  turn.** The user flow lets someone pick a response language independent of
  the language they typed in (project requirement), and an instruction at the
  end of a long prompt is the first thing a model drops.

These are the default templates. A tenant that wants its own wording points
the Agent at an MLflow Prompt Registry entry instead; this module is the
fallback and the reference for what fields a custom prompt must cover.
"""
from __future__ import annotations

import json
from typing import Any

from app.agents.state import Critique, Plan, StepResult
from app.agents.tools import PlaybookSpec, SkillSpec, ToolSpec, load_skill_context

# --- shared fragments -------------------------------------------------------

_LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "it": "Italian",
    "nl": "Dutch",
    "hi": "Hindi",
    "te": "Telugu",
    "ta": "Tamil",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "ar": "Arabic",
}


def language_clause(language: str | None) -> str:
    code = (language or "en").lower()
    name = _LANGUAGE_NAMES.get(code.split("-")[0], code)
    return f"Write your response in {name}."


def _capability_block(tools: list[ToolSpec], skills: list[SkillSpec]) -> str:
    lines: list[str] = []
    if tools:
        lines.append("Tools available to this agent:")
        lines.extend(t.prompt_line() for t in tools)
    if skills:
        lines.append("Skills available to this agent (name + description only):")
        lines.extend(s.prompt_line() for s in skills)
    if not lines:
        lines.append("No tools or skills are available; reason from the provided context only.")
    return "\n".join(lines)


def _playbook_block(playbooks: list[PlaybookSpec]) -> str:
    """Render the playbooks the selection step (app/agents/playbooks.py)
    judged relevant to this objective. Only ever called with an
    already-filtered list — the full attached catalogue is never dumped into
    the prompt, matching the "selection, not enumeration" design of §11.5.
    """
    if not playbooks:
        return ""
    sections = ["Relevant playbooks for this objective — use their canonical steps as a starting decomposition, but adapt them; do not copy steps that do not fit:"]
    for playbook in playbooks:
        lines = [f"### Playbook: {playbook.name}"]
        if playbook.when_to_use:
            lines.append(f"When to use: {playbook.when_to_use}")
        if playbook.canonical_steps:
            steps_text = "\n".join(
                f"  {i}. {step.get('title', '')}: {step.get('detail', '')}".rstrip(": ")
                for i, step in enumerate(playbook.canonical_steps, start=1)
            )
            lines.append(f"Canonical steps:\n{steps_text}")
        if playbook.required_criteria:
            lines.append(
                "The resulting plan must satisfy: "
                + "; ".join(playbook.required_criteria)
            )
        if playbook.known_assumptions:
            notes = "; ".join(
                a.get("assumption", "") for a in playbook.known_assumptions if a.get("assumption")
            )
            if notes:
                lines.append(f"Known pitfalls from past runs: {notes}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _context_block(documents: list[dict[str, Any]]) -> str:
    if not documents:
        return ""
    rendered = []
    for idx, doc in enumerate(documents, start=1):
        title = doc.get("title") or doc.get("filename") or f"document {idx}"
        snippet = (doc.get("snippet") or doc.get("content") or "").strip()
        rendered.append(f"[{idx}] {title}\n{snippet[:1500]}")
    return "Context documents (cite as [n] when you use one):\n" + "\n\n".join(rendered)


def _feedback_block(feedback_log: list[str], critique: Critique | None) -> str:
    """Render accumulated feedback as an explicit, numbered checklist."""
    if not feedback_log and critique is None:
        return ""
    lines = ["A previous attempt was rejected. Fix every item below:"]
    counter = 1
    for entry in feedback_log:
        lines.append(f"{counter}. {entry}")
        counter += 1
    if critique is not None:
        for issue in critique.issues:
            lines.append(f"{counter}. {issue}")
            counter += 1
    lines.append(
        "Do not simply restate the previous attempt. Each item above must be visibly addressed."
    )
    return "\n".join(lines)


# --- planner ----------------------------------------------------------------

PLAN_SCHEMA_HINT = json.dumps(
    {
        "objective": "string — restate the user's goal in one sentence",
        "complexity": "integer 1-5 — 1 trivial, 5 requires deep multi-step research",
        "rationale": "string — one or two sentences on why this decomposition",
        "steps": [
            {
                "id": "string — short unique id, e.g. step_1",
                "title": "string — short label",
                "instruction": "string — what to do, specific enough to act on",
                "tool_name": "string or null — must be one of the listed tools",
                "skill_name": "string or null — must be one of the listed skills",
                "depends_on": ["ids of steps that must finish first"],
            }
        ],
    },
    indent=2,
)


def planner_system_prompt(
    *,
    agent_name: str,
    system_prompt: str | None,
    tools: list[ToolSpec],
    skills: list[SkillSpec],
    max_steps: int,
    language: str,
    playbooks: list[PlaybookSpec] | None = None,
) -> str:
    base = system_prompt.strip() if system_prompt else ""
    return "\n\n".join(
        part
        for part in [
            base,
            f"You are the PLANNER for the agent '{agent_name}'.",
            (
                "Decompose the user's objective into the smallest number of concrete steps "
                f"that fully answers it — never more than {max_steps}. Each step must be "
                "independently actionable and describe an outcome, not a vague intention. "
                "Prefer fewer, larger steps: over-decomposition costs a model round-trip per "
                "step and rarely improves the answer."
            ),
            (
                "Only reference a tool or skill that appears in the list below. Referencing "
                "anything else invalidates the plan and it will be rejected. Prefer a "
                "non-destructive tool when either would do."
            ),
            _capability_block(tools, skills),
            _playbook_block(playbooks or []),
            "Rate complexity honestly — it decides whether an expensive review pass runs.",
            language_clause(language),
        ]
        if part
    )


def planner_user_prompt(
    *,
    objective: str,
    context_documents: list[dict[str, Any]],
    feedback_log: list[str],
    critique: Critique | None,
    previous_plan: Plan | None,
) -> str:
    parts = [f"Objective:\n{objective}"]
    context = _context_block(context_documents)
    if context:
        parts.append(context)
    if previous_plan is not None:
        parts.append(
            "Your previous plan was rejected:\n"
            + json.dumps(previous_plan.model_dump(mode="json"), indent=2)[:2000]
        )
    feedback = _feedback_block(feedback_log, critique)
    if feedback:
        parts.append(feedback)
    return "\n\n".join(parts)


# --- executor ---------------------------------------------------------------


def executor_system_prompt(
    *,
    agent_name: str,
    system_prompt: str | None,
    language: str,
) -> str:
    base = system_prompt.strip() if system_prompt else ""
    return "\n\n".join(
        part
        for part in [
            base,
            f"You are the EXECUTOR for the agent '{agent_name}'.",
            (
                "You are given one step of an approved plan. Carry out exactly that step and "
                "report its result. Do not attempt later steps, do not re-plan, and do not "
                "answer the overall objective — a later step does that."
            ),
            (
                "If a tool result is provided, ground your output in it and say plainly when "
                "the result was simulated rather than real. Never present a simulated result "
                "as a fact."
            ),
            language_clause(language),
        ]
        if part
    )


def executor_step_prompt(
    *,
    objective: str,
    step_index: int,
    step_total: int,
    step_title: str,
    step_instruction: str,
    prior_results: list[StepResult],
    tool_output: str | None,
    skill: SkillSpec | None,
    context_documents: list[dict[str, Any]],
    feedback_log: list[str],
    critique: Critique | None,
) -> str:
    parts = [
        f"Overall objective: {objective}",
        f"Step {step_index} of {step_total}: {step_title}\n{step_instruction}",
    ]
    if prior_results:
        summarised = "\n".join(
            f"- {r.step_id} ({r.status.value}): {r.output[:400]}" for r in prior_results
        )
        parts.append(f"Results of earlier steps in this pass:\n{summarised}")
    if tool_output:
        parts.append(f"Tool result:\n{tool_output[:3000]}")
    if skill is not None:
        parts.append(load_skill_context(skill))
    context = _context_block(context_documents)
    if context:
        parts.append(context)
    feedback = _feedback_block(feedback_log, critique)
    if feedback:
        parts.append(feedback)
    return "\n\n".join(parts)


def executor_synthesis_prompt(
    *,
    objective: str,
    results: list[StepResult],
    context_documents: list[dict[str, Any]],
    feedback_log: list[str],
    critique: Critique | None,
) -> str:
    """Final pass: fold the step results into one answer for the user.

    Separate from the per-step prompt because the audience differs — steps
    are written for the critic and the audit trail, the synthesis is written
    for the person who asked.
    """
    joined = "\n\n".join(f"### {r.step_id}\n{r.output}" for r in results) or "(no step output)"
    parts = [
        f"Objective: {objective}",
        f"Step results:\n{joined}",
        (
            "Write the final answer for the user. Draw only on the step results and context "
            "above. Cite context documents as [n] where you use them. Do not describe the "
            "plan or the process — answer the question."
        ),
    ]
    context = _context_block(context_documents)
    if context:
        parts.append(context)
    feedback = _feedback_block(feedback_log, critique)
    if feedback:
        parts.append(feedback)
    return "\n\n".join(parts)


# --- critic -----------------------------------------------------------------

CRITIQUE_SCHEMA_HINT = json.dumps(
    {
        "verdict": "one of: accept | revise | replan | escalate",
        "score": "number between 0 and 1 — overall quality",
        "feedback": "string — what to change, addressed to the executor",
        "issues": ["specific, individually fixable defects"],
        "target_step_ids": ["ids of steps to redo; empty means all"],
    },
    indent=2,
)


def critic_system_prompt(*, agent_name: str, acceptance_score: float, language: str) -> str:
    return "\n\n".join(
        [
            f"You are the CRITIC for the agent '{agent_name}'. You review a draft answer "
            "against the objective and the plan that produced it.",
            (
                "Judge four things, in order of weight: (1) does it actually answer the "
                "objective; (2) is every claim supported by a step result or a cited "
                "document; (3) are there factual or internal contradictions; (4) is it "
                "appropriately concise. Style is the least important — do not send an answer "
                "back for tone alone."
            ),
            (
                "Choose the verdict that matches the *cause* of the problem:\n"
                f"- accept: good enough (score >= {acceptance_score:.2f}). Prefer this when "
                "the defects are cosmetic — a revision costs a full extra model pass.\n"
                "- revise: the plan was sound, the execution was not.\n"
                "- replan: the plan itself addressed the wrong problem. Expensive; use only "
                "when re-executing the same plan cannot possibly help.\n"
                "- escalate: cannot be resolved without a human (missing access, ambiguous "
                "intent, or a decision the agent should not make alone)."
            ),
            "Be specific. 'Add more detail' is not actionable; name what is missing.",
            language_clause(language),
        ]
    )


def critic_user_prompt(
    *,
    objective: str,
    plan: Plan | None,
    results: list[StepResult],
    draft_answer: str,
    revision: int,
    max_revisions: int,
) -> str:
    parts = [f"Objective:\n{objective}"]
    if plan is not None:
        parts.append(
            "Plan that was executed:\n"
            + "\n".join(f"- {s.id}: {s.title} — {s.instruction}" for s in plan.steps)
        )
    if results:
        parts.append(
            "Step results:\n"
            + "\n".join(f"- {r.step_id} ({r.status.value}): {r.output[:500]}" for r in results)
        )
    parts.append(f"Draft answer to review:\n{draft_answer}")
    parts.append(
        f"Revision {revision} of at most {max_revisions}. "
        + (
            "This is the final permitted revision — accept unless the answer is genuinely "
            "unusable, because there is no further chance to improve it."
            if revision >= max_revisions
            else "There is budget for further revision if it would materially help."
        )
    )
    return "\n\n".join(parts)
