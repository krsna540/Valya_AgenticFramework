import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# --- Persona Trait Schema ----------------------------------------------------
# One sub-model per vector from the spec (Identity & Archetype's headline
# fields live as their own Persona columns — archetype/base_model — not
# here). Every field has a default so a brand-new Persona can be created
# with an empty/near-empty form and filled in incrementally; nothing here
# is enforced at the DB layer (traits is a single JSONB column), only at
# this pydantic boundary — see app/models/persona.py's docstring.


class CoreObjectives(BaseModel):
    mission_statement: str = ""
    primary_kpis: list[str] = Field(default_factory=list)
    success_criteria: str = ""


class TargetAudience(BaseModel):
    primary_audience: str = ""  # e.g. "internal developers", "C-suite executives"
    technical_depth: str = Field(default="balanced", pattern="^(basic|balanced|expert)$")


class CapabilitiesTools(BaseModel):
    allowed_tool_ids: list[uuid.UUID] = Field(default_factory=list)
    allowed_mcp_server_names: list[str] = Field(default_factory=list)


class KnowledgeDomain(BaseModel):
    scope_description: str = ""  # e.g. "Limited to Q3 Marketing Docs"
    allowed_datasource_ids: list[uuid.UUID] = Field(default_factory=list)


class GuardrailsBoundaries(BaseModel):
    rules: list[str] = Field(default_factory=list)  # e.g. "Never discuss competitor pricing"


class ToneVoice(BaseModel):
    # 0 = Casual/Concise, 100 = Formal/Verbose — sliders per the spec.
    formality: int = Field(default=50, ge=0, le=100)
    verbosity: int = Field(default=50, ge=0, le=100)


class PersonalityQuirks(BaseModel):
    quirks: list[str] = Field(default_factory=list)  # e.g. "Uses analogies frequently"


class InteractionStyle(BaseModel):
    timing: str = Field(default="synchronous", pattern="^(synchronous|asynchronous)$")
    turn_style: str = Field(default="multi_turn", pattern="^(multi_turn|single_shot)$")


class SafetyCompliance(BaseModel):
    pii_masking: bool = True
    dlp_tier: str = Field(default="Standard", pattern="^(Relaxed|Standard|Strict)$")
    mandatory_auditing: bool = False


class PersonaTraits(BaseModel):
    core_objectives: CoreObjectives = Field(default_factory=CoreObjectives)
    target_audience: TargetAudience = Field(default_factory=TargetAudience)
    capabilities_tools: CapabilitiesTools = Field(default_factory=CapabilitiesTools)
    knowledge_domain: KnowledgeDomain = Field(default_factory=KnowledgeDomain)
    guardrails_boundaries: GuardrailsBoundaries = Field(default_factory=GuardrailsBoundaries)
    tone_voice: ToneVoice = Field(default_factory=ToneVoice)
    personality_quirks: PersonalityQuirks = Field(default_factory=PersonalityQuirks)
    interaction_style: InteractionStyle = Field(default_factory=InteractionStyle)
    safety_compliance: SafetyCompliance = Field(default_factory=SafetyCompliance)


# --- Persona CRUD wire schemas ------------------------------------------------


class PersonaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    archetype: str | None = Field(default=None, max_length=100)
    base_model: str | None = Field(default=None, max_length=100)
    traits: PersonaTraits = Field(default_factory=PersonaTraits)
    is_active: bool = True


class PersonaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    archetype: str | None = Field(default=None, max_length=100)
    base_model: str | None = Field(default=None, max_length=100)
    traits: PersonaTraits | None = None
    is_active: bool | None = None


class PersonaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    archetype: str | None
    base_model: str | None
    traits: PersonaTraits
    safety_compliance_tier: str
    is_active: bool
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class UserPersonaMappingCreate(BaseModel):
    user_id: uuid.UUID
    persona_id: uuid.UUID
    project_id: uuid.UUID | None = None
    is_default: bool = False


class UserPersonaMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    persona_id: uuid.UUID
    project_id: uuid.UUID | None
    is_default: bool
    created_at: datetime
