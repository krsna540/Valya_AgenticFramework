import uuid

from sqlalchemy import JSON, Column, ForeignKey, String, Table, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import RegistryMixin, TenantScopedMixin

agent_skills = Table(
    "agent_skills",
    Base.metadata,
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("skill_id", UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True),
)


class Skill(RegistryMixin, TenantScopedMixin, Base):
    """A skill: a folder uploaded as a zip, per this app's canonical format —

        my-custom-skill/
        ├── SKILL.md          # Required: YAML frontmatter + Markdown instructions
        ├── skill.json        # Optional: config/manifest for triggers & hooks
        ├── references/       # Optional: static context, templates, styles
        ├── scripts/          # Optional: executable code (Python, Bash, JS)
        └── assets/           # Optional: images, schemas, raw data assets

    SKILL.md's frontmatter rules match the open agentskills.io spec
    (https://agentskills.io/specification) — this format started as a
    direct implementation of that spec (formerly a separate "SkillPackage"
    model, see [[project_agentic_mvp_skill_packages]] in project memory)
    before becoming the *only* way a skill is defined in this app
    ([[project_agentic_mvp_nexusclaw_manifest_conventions]]'s
    handler_key/BaseSkill catalog was retired in favor of this).

    Nothing in this model is ever executed. `scripts/` files are meant to be
    run *by an agent that decides to*, not by this app — there is no
    execution engine here, deliberately: this app built exactly that kind
    of feature once (Community Skills, real code executed via
    importlib.util.exec_module) and the user asked for it to be fully
    removed two sessions later. See docs/SKILL_STANDARD.md for the full
    rationale. `skill.json`'s `hooks` field is the one place this model
    references *behavior* — but only by pointing at handler_keys already
    vetted in app.services.hooks.BUILTIN_HOOKS, never by shipping its own
    hook code, keeping the same no-stored-code invariant as Plugin/Hook.
    """

    __tablename__ = "skills"

    license: Mapped[str | None] = mapped_column(String(255), nullable=True)
    compatibility: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_fields: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    allowed_tools: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # The exact original SKILL.md text (frontmatter + body), so downloads are
    # byte-identical to what was uploaded, plus the parsed body alone for
    # quick rendering without re-splitting frontmatter client-side.
    skill_md_raw: Mapped[str] = mapped_column(Text, nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)

    # The optional skill.json sidecar — original text (nullable: the file is
    # optional) plus its parsed triggers/hooks, denormalized into their own
    # columns so they're queryable/displayable without re-parsing JSON.
    skill_json_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {keywords: [str], intents: [str], lifecycle_events: [str]}
    triggers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Hook handler_keys (app.services.hooks.BUILTIN_HOOKS) this skill
    # declares as relevant alongside it — advisory, validated at upload time.
    hooks: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Where the extracted directory lives on disk, and a manifest of every
    # file inside it (relative paths) so the UI can browse scripts/references/
    # assets without walking the filesystem on every request.
    dir_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_manifest: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Content-addressed mirror in MinIO — {relative file path: "sha256:<hex>"}
    # — written alongside (not instead of) dir_path at upload time. See
    # app/core/minio_client.py's module docstring for exactly what's wired
    # here vs deferred (serving still reads from dir_path; this is a
    # verifiable extra copy, not yet the source of truth). Best-effort: a
    # MinIO outage at upload time leaves this {} rather than failing the
    # upload, same non-blocking posture as redis_client.py.
    blob_digests: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
