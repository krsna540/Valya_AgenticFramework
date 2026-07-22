// The three OPA-backed authorization flows (see docs/AUTHORIZATION.md):
//   super_admin — platform-level, tenant_id is always null. Creates
//                 tenants, assigns admins to them.
//   admin       — full control of everything within their own tenant.
//   user        — agents (read-only) + chat only. (Was "member" before
//                 the three-role model.)
export type Role = "super_admin" | "admin" | "user";

export interface User {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  tenant_id: string | null;
  role: Role;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface RateLimitSettings {
  per_user_rpm: number;
  per_tenant_rpm: number;
  tokens_per_day: number;
}

export interface GuardrailSettings {
  pii_redaction: boolean;
  prompt_injection_screening: boolean;
  groundedness_check: boolean;
  topic_blocklist: boolean;
}

export interface TenantSettings {
  rate_limits: RateLimitSettings;
  guardrails: GuardrailSettings;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  settings: TenantSettings;
  created_at: string;
}

/** What the Super Admin's Tenants table renders — see GET /platform/tenants. */
export interface TenantSummary extends Tenant {
  admin_count: number;
  user_count: number;
  workspace_count: number;
  mtd_cost_usd: number;
  layer_knowledge: boolean;
  layer_expertise: boolean;
  layer_norms: boolean;
  status_label: string;
}

// --- Platform dashboard (Super Admin) ---

export interface PlatformOverview {
  active_tenants: number;
  new_tenants_this_month: number;
  monthly_active_users: number;
  llm_spend_mtd_usd: number;
  llm_budget_usd: number;
  gateway_p95_latency_ms: number | null;
  gateway_slo_ms: number;
}

export interface UsageDailyPoint {
  date: string;
  chat_turns: number;
  tool_and_skill_calls: number;
}

export interface CostByTenantRow {
  tenant_name: string;
  tenant_slug: string;
  cost_usd: number;
}

export interface CostByTenant {
  by_tenant: CostByTenantRow[];
  avg_cost_per_request_usd: number;
}

export interface PlatformHealth {
  gateway_p95_latency_ms: number | null;
  gateway_slo_ms: number;
  error_rate_30d: number;
  total_requests_30d: number;
  last_request_at: string | null;
  datasources_failing: number;
  datasources_syncing: number;
}

export interface AuditLogEntry {
  id: string;
  tenant_id: string | null;
  actor_user_id: string | null;
  actor_email: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  extra: Record<string, unknown>;
  created_at: string;
}

export type ModelKind = "chat" | "embed";
export type ModelStatus = "live" | "eval" | "disabled";

export interface ModelGates {
  gateway_configured: boolean;
  cost_meter_registered: boolean;
  faithfulness_passed: boolean;
  task_completion_passed: boolean;
  security_redteam_passed: boolean;
  all_passed: boolean;
}

export interface ModelRoute {
  id: string;
  name: string;
  provider: string;
  route: string;
  kind: ModelKind;
  input_cost_per_1m: number;
  output_cost_per_1m: number | null;
  status: ModelStatus;
  gateway_configured: boolean;
  cost_meter_registered: boolean;
  eval_faithfulness: number | null;
  eval_faithfulness_threshold: number;
  eval_task_completion: number | null;
  eval_task_completion_threshold: number;
  eval_security_redteam_passed: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  gates: ModelGates;
}

// --- Norms: tenant access policies ---

export type PolicyMode = "enforced" | "dry_run";

export interface Policy {
  id: string;
  tenant_id: string;
  name: string;
  rule_expression: string;
  mode: PolicyMode;
  is_active: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface PolicyMapping {
  id: string;
  user_id: string;
  policy_id: string;
  created_at: string;
}

export interface RegistryItem {
  id: string;
  tenant_id?: string | null;
  name: string;
  description: string | null;
  is_active: boolean;
  config: Record<string, unknown>;
  version: string;
  status: "Active" | "Experimental" | "Deprecated";
  created_at: string;
  updated_at: string;
}

/** MCP tool annotation hints (spec 2025-06-18) — client display/behavior
 * hints only, never a security boundary. */
export interface ToolAnnotations {
  title: string | null;
  readOnlyHint: boolean;
  destructiveHint: boolean;
  idempotentHint: boolean;
  openWorldHint: boolean;
}

export function emptyToolAnnotations(): ToolAnnotations {
  return { title: null, readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true };
}

export interface Tool extends RegistryItem {
  tool_type: "function" | "mcp";
  mcp_transport: "sse" | "stdio" | null;
  mcp_endpoint: string | null;
  mcp_command: string | null;
  mcp_tool_name: string | null;
  // Manifest metadata (NexusClaw-inspired manifest.json shape)
  input_schema: Record<string, unknown> | null;
  permissions: string[];
  rate_limit_per_min: number;
  timeout_s: number;
  tags: string[];
  annotations: ToolAnnotations;
}

export interface Plugin extends RegistryItem {
  exports_skills: string[];
  exports_hooks: string[];
  exports_tools: string[];
  exports_commands: string[];
  requires_permissions: string[];
  requires_env: string[];
}

export type LifecycleEvent =
  | "SessionStart"
  | "UserPromptSubmit"
  | "PreToolUse"
  | "PostToolUse.Success"
  | "PostToolUse.Failure"
  | "PreCompact"
  | "SubagentStart"
  | "SubagentStop"
  | "Stop"
  | "Notification";

export type HandlerType = "python" | "http" | "command" | "mcp_tool";

export interface Hook extends RegistryItem {
  scope: "global" | "agent";
  lifecycle_event: LifecycleEvent;
  handler_type: HandlerType;
  handler_key: string | null;
  handler_config: Record<string, unknown>;
  execution_policy: Record<string, unknown>;
  version: string;
  status: "Active" | "Experimental" | "Deprecated";
  tags: string[];
  author: string | null;
}

/** One entry from GET /hooks/lifecycle-events — the full 10-stage taxonomy,
 * flagged for whether this app currently fires it for real. */
export interface LifecycleEventInfo {
  key: LifecycleEvent;
  wired: boolean;
}

// --- Skills: the canonical folder format ---
//
//   my-custom-skill/
//   ├── SKILL.md          # Required
//   ├── skill.json        # Optional: config/manifest for triggers & hooks
//   ├── references/       # Optional
//   ├── scripts/          # Optional: executable code
//   └── assets/           # Optional
//
// This used to be two systems (a handler_key-bound Skill calling into a
// vetted Python catalog, and this folder format as a separate
// "SkillPackage") until the handler_key system was retired in favor of
// making this the only one. See docs/SKILL_STANDARD.md.

export interface SkillTriggers {
  keywords: string[];
  intents: string[];
  lifecycle_events: string[];
}

export interface Skill {
  id: string;
  tenant_id?: string | null;
  name: string;
  description: string | null;
  is_active: boolean;
  version: string;
  status: "Active" | "Experimental" | "Deprecated";
  license: string | null;
  compatibility: string | null;
  metadata: Record<string, string>;
  allowed_tools: string | null;
  body_markdown: string;
  file_manifest: string[];
  // skill.json-derived — empty/default when the skill has no skill.json.
  triggers: SkillTriggers;
  hooks: string[];
  created_at: string;
  updated_at: string;
}

/** One entry from GET /hooks/handlers — the vetted, code-reviewed
 * implementations a Hook can bind to via handler_key. */
export interface HookHandlerInfo {
  key: string;
  stage: "before_agent_step" | "after_agent_step" | "before_message_send" | "on_error";
  description: string;
}

export interface PromptMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface PromptVariable {
  name: string;
  description: string | null;
  default: string | null;
  required: boolean;
}

export interface PromptModelParams {
  model: string | null;
  temperature: number | null;
  max_tokens: number | null;
  top_p: number | null;
  stop: string[];
}

export interface Prompt {
  id: string;
  tenant_id?: string | null;
  name: string;
  description: string | null;
  is_active: boolean;
  version: string;
  status: "Active" | "Experimental" | "Deprecated";
  label: string;
  tags: string[];
  messages: PromptMessage[];
  variables: PromptVariable[];
  model_params: PromptModelParams;
  created_at: string;
  updated_at: string;
}

/** Text to drop into the chat composer when a user picks this prompt via
 * "/" — joins the user-role message(s); falls back to every message if the
 * template has no user-role turn. {{variable}} placeholders are left as-is
 * for the person to fill in by hand. */
export function promptComposerText(prompt: Prompt): string {
  const userTurns = prompt.messages.filter((m) => m.role === "user");
  const turns = userTurns.length > 0 ? userTurns : prompt.messages;
  return turns.map((m) => m.content).join("\n\n");
}

export interface Agent {
  id: string;
  tenant_id: string | null;
  name: string;
  description: string | null;
  is_active: boolean;
  system_prompt: string | null;
  model_name: string;
  version: string;
  status: "Active" | "Experimental" | "Deprecated";
  owner_id: string;
  created_at: string;
  updated_at: string;
  skill_ids: string[];
  tool_ids: string[];
  plugin_ids: string[];
  hook_ids: string[];
}

/** A selectable chat target — in this app, an active Agent. */
export interface ModelInfo {
  id: string;
  name: string;
  model_name: string;
  description: string | null;
}

export interface UploadedFileMeta {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
}

export interface Citation {
  id: string;
  source: string;
  snippet: string;
}

export interface Conversation {
  id: string;
  agent_id: string;
  secondary_agent_ids: string[];
  title: string;
  project_id?: string | null;
  created_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  parent_message_id: string | null;
  agent_id: string | null;
  role: "user" | "assistant" | "system";
  content: string;
  is_active_branch: boolean;
  citations: Citation[];
  file_ids: string[];
  created_at: string;
  // client-only, while a response is still streaming in
  streaming?: boolean;
  toolCall?: string | null;
  skillCall?: string | null;
  // client-only: set when a before_agent_step hook halted generation
  blocked?: boolean;
}

export interface ConversationWithMessages extends Conversation {
  messages: Message[];
}

export interface SiblingInfo {
  id: string;
  is_active_branch: boolean;
  created_at: string;
}

export interface SiblingGroup {
  parent_message_id: string | null;
  agent_id: string | null;
  active_index: number;
  siblings: SiblingInfo[];
}

// --- SSE event payloads (see backend app/api/routes/chat.py `_sse`) ---

export interface SseStatusEvent {
  status: string;
  user_message_id: string;
}

export interface SseStreamStartEvent {
  agent_id: string;
}

export interface SseTokenEvent {
  agent_id: string;
  text: string;
}

export interface SseToolCallEvent {
  agent_id: string;
  tool_name: string;
}

export interface SseSkillCallEvent {
  agent_id: string;
  skill_name: string;
}

export interface SseStreamEndEvent {
  agent_id: string;
  content: string;
  citations: Citation[];
  message_id: string;
  blocked?: boolean;
}

export interface SseStreamCompleteEvent {
  conversation_id: string;
}

// --- Admin: users under tenant ---

export interface AdminUser {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  tenant_id: string | null;
  role: Role;
  created_at: string;
}

// --- Pillar 1: Persona Trait Schema ---

export interface CoreObjectives {
  mission_statement: string;
  primary_kpis: string[];
  success_criteria: string;
}

export interface TargetAudience {
  primary_audience: string;
  technical_depth: "basic" | "balanced" | "expert";
}

export interface CapabilitiesTools {
  allowed_tool_ids: string[];
  allowed_mcp_server_names: string[];
}

export interface KnowledgeDomain {
  scope_description: string;
  allowed_datasource_ids: string[];
}

export interface GuardrailsBoundaries {
  rules: string[];
}

export interface ToneVoice {
  formality: number; // 0 Casual -> 100 Formal
  verbosity: number; // 0 Concise -> 100 Verbose
}

export interface PersonalityQuirks {
  quirks: string[];
}

export interface InteractionStyle {
  timing: "synchronous" | "asynchronous";
  turn_style: "multi_turn" | "single_shot";
}

export interface SafetyCompliance {
  pii_masking: boolean;
  dlp_tier: "Relaxed" | "Standard" | "Strict";
  mandatory_auditing: boolean;
}

export interface PersonaTraits {
  core_objectives: CoreObjectives;
  target_audience: TargetAudience;
  capabilities_tools: CapabilitiesTools;
  knowledge_domain: KnowledgeDomain;
  guardrails_boundaries: GuardrailsBoundaries;
  tone_voice: ToneVoice;
  personality_quirks: PersonalityQuirks;
  interaction_style: InteractionStyle;
  safety_compliance: SafetyCompliance;
}

export function emptyPersonaTraits(): PersonaTraits {
  return {
    core_objectives: { mission_statement: "", primary_kpis: [], success_criteria: "" },
    target_audience: { primary_audience: "", technical_depth: "balanced" },
    capabilities_tools: { allowed_tool_ids: [], allowed_mcp_server_names: [] },
    knowledge_domain: { scope_description: "", allowed_datasource_ids: [] },
    guardrails_boundaries: { rules: [] },
    tone_voice: { formality: 50, verbosity: 50 },
    personality_quirks: { quirks: [] },
    interaction_style: { timing: "synchronous", turn_style: "multi_turn" },
    safety_compliance: { pii_masking: true, dlp_tier: "Standard", mandatory_auditing: false },
  };
}

export interface Persona {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  archetype: string | null;
  base_model: string | null;
  traits: PersonaTraits;
  safety_compliance_tier: string;
  is_active: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface UserPersonaMapping {
  id: string;
  user_id: string;
  persona_id: string;
  project_id: string | null;
  is_default: boolean;
  created_at: string;
}

// --- Pillar 2: Datasources ---

export type ConnectorType =
  | "sharepoint"
  | "confluence"
  | "rest_api"
  | "graphql"
  | "sql_database"
  | "nosql_database"
  | "github"
  | "gitlab"
  | "web_crawl"
  | "file_upload";

export type SecurityTier = "Public" | "Internal" | "Confidential" | "Restricted";

export type AuthType = "oauth2" | "api_key" | "basic" | "service_account" | "none";
export type SyncMode = "full_refresh" | "incremental";

/** One field in a connector type's spec — adopted from Airbyte's spec.json
 * convention (per-source JSON schema, `airbyte_secret` marking sensitive
 * fields). `secret` is a UI-masking hint only; this app never stores real
 * secrets (see Datasource's backend docstring). */
export interface ConnectorField {
  key: string;
  label: string;
  type: "string" | "number" | "boolean" | "select";
  required: boolean;
  secret: boolean;
  options?: string[];
  help_text?: string;
}

export interface ConnectorTypeInfo {
  key: ConnectorType;
  default_auth_type: AuthType;
  fields: ConnectorField[];
}

export interface Datasource {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  connector_type: ConnectorType;
  connection_config: Record<string, unknown>;
  auth_status: "not_connected" | "connected" | "expired" | "error";
  auth_config: Record<string, unknown>;
  auth_type: AuthType;
  security_classification: SecurityTier;
  sync_status: "idle" | "syncing" | "success" | "error";
  last_synced_at: string | null;
  chunking_policy: Record<string, unknown>;
  embedding_policy: Record<string, unknown>;
  sync_mode: SyncMode;
  sync_schedule_cron: string | null;
  is_active: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

// --- Pillar 3/5/6: Projects, Intelligence bindings, Runtime & Freeze ---

export type ExecutionMode = "event_driven" | "real_time_chat" | "scheduled";
// "skill_package" used to be a sixth, separate component_type before the
// handler_key Skill system was retired — "skill" now means the folder-based
// model exclusively. See docs/SKILL_STANDARD.md.
export type ComponentType = "agent" | "tool" | "hook" | "skill" | "plugin";

export interface Project {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  cost_center: string | null;
  status: "draft" | "frozen" | "deployed" | "archived";
  execution_mode: ExecutionMode;
  schedule_cron: string | null;
  webhook_slug: string | null;
  frozen_at: string | null;
  deployed_at: string | null;
  is_active: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface Binding {
  id: string;
  project_id: string;
  component_type: ComponentType;
  component_id: string;
  version_pinned: string | null;
  is_active: boolean;
  created_at: string;
  component_name: string | null;
  component_version: string | null;
}

export interface TopologyMappedUser {
  user_id: string;
  full_name: string;
  email: string;
  persona_id: string | null;
  persona_name: string | null;
}

export interface TopologyDatasource {
  datasource_id: string;
  name: string;
  connector_type: ConnectorType;
  security_classification: SecurityTier;
  sync_status: string;
}

export interface TopologyComponent {
  component_type: ComponentType;
  component_id: string;
  name: string;
  version: string;
}

export interface ProjectTopology {
  project_id: string;
  project_name: string;
  status: string;
  execution_mode: ExecutionMode;
  schedule_cron: string | null;
  webhook_slug: string | null;
  mapped_users: TopologyMappedUser[];
  datasources: TopologyDatasource[];
  intelligence: TopologyComponent[];
  resolved_at: string;
}

export interface SseErrorEvent {
  agent_id: string;
  message: string;
}
