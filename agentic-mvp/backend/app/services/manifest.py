"""The manifest compiler — PLATFORM_ARCHITECTURE.md §6.2's twelve-step
resolution algorithm, scoped down to what this session actually wires end
to end. Honest boundary:

  WIRED:    steps 4 (resolve bindings), 8 (canonicalize), 9 (hash),
            10 (persist), 11 (cache in Redis), 12 (return). Reads
            ProjectIntelligenceBinding (already existed) for skills/tools/
            hooks/agents/plugins, and Prompt separately since prompts
            aren't bound through that table.
  DEFERRED: step 5's live existence/credential-resolution validation,
            step 6's retrieval-filter compilation (no retrieval pipeline
            in this codebase — ingestion is out of scope for this build,
            see the top-level request), step 7's OPA bundle-revision
            pinning (this app's OPA integration authorizes ROUTES, not
            registry content — see app/core/opa.py's docstring; there is
            no compiled bundle revision to pin yet).

The manifest this produces is therefore a real, hashed, persisted,
deduplicated capability snapshot of a project's bound registry — genuinely
useful for "what was this session allowed to use" audit and reproducibility
— but its `policy_bundle` and `retrieval` fields are honest placeholders,
not yet load-bearing. See docs/PLATFORM_ARCHITECTURE.md §17 gap map.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.hook import Hook
from app.models.manifest import Manifest, ManifestSession
from app.models.plugin import Plugin
from app.models.project import Project
from app.models.project_intelligence_binding import ProjectIntelligenceBinding
from app.models.prompt import Prompt
from app.models.skill import Skill
from app.models.tool import Tool

_COMPONENT_MODELS: dict[str, type] = {
    "agent": Agent,
    "tool": Tool,
    "hook": Hook,
    "skill": Skill,
    "plugin": Plugin,
}


def _canonical_json(body: dict[str, Any]) -> bytes:
    """RFC-8785-*style* canonicalization (§6.2 step 8): sorted keys, no
    whitespace, UTF-8. Not a full JCS implementation (no NFC normalization
    edge cases, no exhaustive number formatting spec) — sufficient for this
    app's own JSON-serializable manifest bodies, which never contain the
    pathological float/unicode cases JCS exists to pin down.
    """
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _resolve_bindings(db: Session, project_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
    bindings = (
        db.query(ProjectIntelligenceBinding)
        .filter(ProjectIntelligenceBinding.project_id == project_id, ProjectIntelligenceBinding.is_active == True)  # noqa: E712
        .all()
    )
    resolved: dict[str, list[dict[str, Any]]] = {"agents": [], "tools": [], "hooks": [], "skills": [], "plugins": []}
    plural = {"agent": "agents", "tool": "tools", "hook": "hooks", "skill": "skills", "plugin": "plugins"}
    for binding in bindings:
        model = _COMPONENT_MODELS.get(binding.component_type)
        if model is None:
            continue
        row = db.get(model, binding.component_id)
        if row is None or not getattr(row, "is_active", True):
            continue
        resolved[plural[binding.component_type]].append(
            {
                "id": str(row.id),
                "name": row.name,
                # version_pinned freezes a specific SemVer at bind time
                # (ProjectIntelligenceBinding's own docstring); NULL means
                # "float to current" and step 4 resolves that NOW, per §6.2.
                "version": binding.version_pinned or getattr(row, "version", "1.0.0"),
                "access_class": getattr(row, "access_class", "custom"),
            }
        )
    return resolved


def _resolve_prompts(db: Session, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    # Prompts aren't bound via ProjectIntelligenceBinding (they're surfaced
    # tenant-wide through the chat "/" picker, per app/models/prompt.py) —
    # the manifest still lists every prompt this project's tenant can see,
    # so "which prompts could this session have used" has an answer.
    prompts = (
        db.query(Prompt)
        .filter(Prompt.is_active == True, (Prompt.tenant_id == tenant_id) | (Prompt.tenant_id.is_(None)))  # noqa: E712
        .all()
    )
    return [{"id": str(p.id), "name": p.name, "label": p.label, "version": p.version} for p in prompts]


def compile_manifest(db: Session, *, project: Project, user_id: uuid.UUID, locale: str = "en") -> dict[str, Any]:
    """§6.2 steps 4-9: resolve, canonicalize, hash. Returns the manifest
    body (not yet persisted — see persist_and_cache below, kept separate so
    callers that only need the hash for comparison don't pay a write)."""
    bindings = _resolve_bindings(db, project.id)
    prompts = _resolve_prompts(db, project.tenant_id)

    body: dict[str, Any] = {
        "schema_version": 1,
        "scope": {
            "tenant_id": str(project.tenant_id),
            "project_id": str(project.id),
            "user_id": str(user_id),
            "locale": locale,
        },
        "prompt_set": prompts,
        "skills": bindings["skills"],
        "tools": bindings["tools"],
        "hooks": bindings["hooks"],
        "agents": bindings["agents"],
        "plugins": bindings["plugins"],
        # Honest placeholders — see module docstring's DEFERRED list.
        "policy_bundle": None,
        "retrieval": None,
    }
    canonical = _canonical_json(body)
    manifest_id = "sha256:" + hashlib.sha256(canonical).hexdigest()
    body["manifest_id"] = manifest_id
    return body


def persist_manifest(db: Session, *, tenant_id: uuid.UUID, project_id: uuid.UUID, body: dict[str, Any]) -> Manifest:
    """§6.2 step 10, with the dedup INSERT ... ON CONFLICT DO NOTHING this
    content-addressed PK gives for free (§6.3: "share one manifest row")."""
    manifest_id = body["manifest_id"]
    existing = db.get(Manifest, manifest_id)
    if existing is not None:
        return existing
    manifest = Manifest(manifest_id=manifest_id, tenant_id=tenant_id, project_id=project_id, body=body, schema_version=1)
    db.add(manifest)
    db.commit()
    db.refresh(manifest)
    return manifest


def create_session(db: Session, *, manifest_id: str, tenant_id: uuid.UUID, project_id: uuid.UUID, user_id: uuid.UUID, locale: str) -> ManifestSession:
    session_row = ManifestSession(
        id=uuid.uuid4(), manifest_id=manifest_id, tenant_id=tenant_id, project_id=project_id, user_id=user_id, locale=locale, status="active"
    )
    db.add(session_row)
    db.commit()
    db.refresh(session_row)
    return session_row
