from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import RegistryMixin, TenantScopedMixin


class Plugin(RegistryMixin, TenantScopedMixin, Base):
    """A plugin bundle: a named, versioned collection of already-registered
    Skills/Hooks/Tools, installed together as one unit.

    Manifest shape adopted from KnowledgeNexusClaw's plugins/<name>/manifest.yaml
    (see docs/SKILL_STANDARD.md), with one deliberate difference: NexusClaw's
    plugin installer dynamically imports hook *.py modules from disk at
    install time (real code, freshly executed). That mechanism is the same
    shape as the Community Skills real-code-execution path this app built and
    then fully removed at the user's request (see docs/SKILL_STANDARD.md's
    "What's different from NexusClaw" section) — so it is not reproduced
    here. Instead, exports_* are plain string keys that must already resolve
    to a vetted, code-reviewed handler_key in SKILL_REGISTRY / BUILTIN_HOOKS
    (validated in app/schemas/plugin.py's PluginCreate/PluginUpdate, the same
    "no stored/eval'd code" invariant Skill and Hook already enforce).
    """

    __tablename__ = "plugins"

    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    # Skill handler_keys (app.skills.catalog.SKILL_REGISTRY) this plugin
    # bundles. Installing/activating the plugin is advisory bookkeeping only
    # — it does not create Skill rows automatically; see PluginRead's
    # `unresolved_exports` for what the UI shows when one of these no longer
    # resolves (e.g. after a catalog change).
    exports_skills: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Hook handler_keys (app.services.hooks.BUILTIN_HOOKS).
    exports_hooks: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Tool names this plugin documents/bundles (advisory only — Tool rows are
    # still created/managed independently via the Tools registry).
    exports_tools: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Slash-command shortcuts this plugin declares. Advisory only, same as
    # NexusClaw's `commands` export — this app has no command-shortcut layer
    # yet, so these are just labels shown in the UI.
    exports_commands: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Declared prerequisites, checked at create/update time so an admin can't
    # publish a plugin whose dependencies can't be satisfied.
    requires_permissions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    requires_env: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
