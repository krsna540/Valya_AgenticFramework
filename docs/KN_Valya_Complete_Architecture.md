# KN_Valya — Complete Architecture (Admin Flow + Agent Runtime)

> **Status — FROZEN as of 2026-07-02, both flows.** This is the single consolidated reference, merging `ARCHITECTURE.md` (admin/ingestion flow) and `agent_runtime_architecture.md` (agent runtime: admin configuration + user execution). Post-freeze changes to any section require an ADR (Architecture Decision Record) and a version bump on this document. Part I covers ingestion and the core admin flow. Part II covers the agent runtime — registries, project agent configuration, the Agent Observatory dashboard, and user-flow execution. Appendices hold the shared glossary and full research backing for every decision in both parts.
>
> **Amendment — ADR-002 (2026-07-05):** Part II §A2.8 decision #9 (agentic memory backend) changes from Mem0-default to **memU-default**. Mem0 is demoted to a pluggable-adapter option alongside Zep/Graphiti. Rationale and detail in §A2.9.

---

# PART I — INGESTION & ADMIN FLOW

Enterprise agentic-AI platform: multi-tenant ingestion, unified knowledge base per project, agent-driven retrieval over a converged corpus.

## Frozen Admin Flow — Locked Decisions

The following decisions are the final admin-flow contract. Any implementation deviating from them is a bug, not a variant.

| # | Decision | Locked Choice |
|---|---|---|
| 1 | Multi-tenancy model | Tenant → Projects → Users (Postgres FK cascade); tenant_id required on every query |
| 2 | User ACL | `project_memberships` + source-inherited `acl_groups[]` propagated to every chunk |
| 3 | Connector model | Tenant-scoped connectors, project-scoped datasource instances |
| 4 | Pipeline definition | YAML in Postgres, versioned, immutable per version, declarative-only (no embedded code) |
| 5 | Pipeline binding | `(project, datasource, doc_type) → pipeline_id`, project default as fallback |
| 6 | Canonical form per document | Structured **DocumentDOM (JSON Schema-validated)** persisted in MinIO as `canonical.json`; free-text markdown rendering derived on demand for the admin document-inspector view |
| 7 | Knowledge-format standard | **OKF rejected as overkill** for this platform's scope. DocumentDOM stays the contract. Reasoning: (a) OKF is a distribution/exchange format for curated knowledge bundles across orgs — our use case is internal enrichment of source docs, not cross-org bundle exchange; (b) OKF's one-concept-per-file model conflicts with our chunking granularity; (c) OKF requires structural inference that would push us back toward LLM-driven authoring, opposite of the rule-based goal. Revisit only if a cross-org knowledge-exchange requirement emerges. |
| 8 | Chunking | Rule-based parent-child (400/2000 tok) with hard section/table/code boundaries; no LLM in the chunker itself |
| 9 | Contextualization | Cheap LLM (Haiku-class), per-chunk, cached by content hash — accepted as the one LLM step we won't remove because of its 35–49% quality lift |
| 10 | RAPTOR | 3 levels max; GMM-with-BIC over contextualized child embeddings; grounded-summary prompt with cited `source_chunk_ids` |
| 11 | Embedding | One model per tenant (BGE-M3 default), dense + sparse from same model; no per-doc-type embedders |
| 12 | Image handling | VLM caption + OCR + file stored under SHA-256 path in MinIO; captions embedded via same text embedder; original files referenced via metadata |
| 13 | Vector DB layout | One Qdrant collection per project (`project_{uuid}`); named vectors: `dense_text`, `sparse_text`, `image_clip` (optional); tenant-indexed payload |
| 14 | Virtual clusters | Saved Postgres filter expressions, applied server-side as Qdrant `must` clauses; ACL always AND-ed |
| 15 | Orchestration | Temporal, one workflow per document version, independent task queues per worker |
| 16 | Event transport | Postgres outbox → Redis Streams → Temporal `start_workflow` (idempotent by workflow_id) |
| 17 | Object storage | MinIO (S3-compatible); path layout: `raw/`, `interim/`, `canonical/`, `images/`, versioned by `v{n}` |
| 18 | Lifecycle | Per-tenant/project retention policies; sweeper job applies daily |
| 19 | Audit | Every mutation writes to `audit_log`; retained per compliance policy |
| 20 | Admin UI screens (locked) | Pipeline Editor, Document Inspector, Run Observatory, Clusters & Connectors (four plates in `docs/design/admin-screens.pdf`) — extended by two more (decision below) |
| 21 | Agent Runtime — admin screens (locked, added 2026-07-02 via ADR) | Agent & Registry Console, Project Agent Configuration, Agent Observatory — full contract in **Part II** of this document |

Post-freeze deferrals — explicitly out of admin scope, to be handled in later releases: ~~agent authoring UI~~ **resolved, see decision #21 and Part II**; cross-tenant search, cross-org knowledge exchange, browser-plugin ingestion, human-in-the-loop chunk correction remain deferred.

---

## 1. System at a Glance

```
                           ┌─────────────────────────────────────┐
                           │           React Frontend            │
                           │  Admin UI         │   User UI       │
                           │  • Tenants/Projects   • Project picker │
                           │  • Pipelines (YAML)   • Language sel.  │
                           │  • Connectors/Docs    • Agent chat     │
                           │  • Run Observatory    • Citations view │
                           └────────────────┬────────────────────┘
                                            │ HTTPS / JWT
                                            ▼
                           ┌─────────────────────────────────────┐
                           │        FastAPI Gateway              │
                           │  Auth · RBAC · Validation · Routing │
                           └──┬───────────┬─────────────┬────────┘
                              │           │             │
                  ┌───────────▼──┐  ┌─────▼──────┐  ┌──▼──────────┐
                  │   Config     │  │  Retrieval │  │   Trigger   │
                  │  Service     │  │  Service   │  │  Dispatcher │
                  │  (Postgres)  │  │  (Qdrant)  │  │  (Outbox)   │
                  └───────┬──────┘  └─────┬──────┘  └──┬──────────┘
                          │               │            │
                          │     ┌─────────┴────────┐   │
                          │     │   Reranker svc   │   │
                          │     └──────────────────┘   │
                          │                            │
                          ▼                            ▼
                  ┌──────────────┐             ┌──────────────┐
                  │  Postgres    │             │ Redis Streams│
                  │  (config DB) │             │  (events)    │
                  └──────────────┘             └──────┬───────┘
                                                      │
                                                      ▼
                                          ┌──────────────────────┐
                                          │  Temporal Cluster    │
                                          │  Workflow per doc-vN │
                                          └──┬───────────────────┘
                                             │  task queues
                  ┌──────────┬────────────┬──┴─────┬──────────┬──────────┐
                  ▼          ▼            ▼        ▼          ▼          ▼
              extractor  enricher   chunker   captioner  raptor    indexer
              workers    workers    workers   (VLM)      workers   workers
                │           │          │         │          │          │
                ▼           ▼          ▼         ▼          ▼          ▼
          ┌────────────────────────────────────────────────────────────────┐
          │       Object Store (raw bytes, interim artifacts, images)      │
          └────────────────────────────────────────────────────────────────┘
                          │                                  │
                          ▼                                  ▼
                  ┌──────────────┐                  ┌──────────────────┐
                  │  Postgres    │                  │     Qdrant       │
                  │  (chunks,    │                  │  one collection  │
                  │  lineage)    │                  │   per project    │
                  └──────────────┘                  └──────────────────┘
```

---

## 2. Component Inventory

| Component | Role | Tech |
|---|---|---|
| **Frontend** | Admin + user UI | React, Monaco (YAML editor), Tailwind |
| **API Gateway** | Authn, RBAC, request routing | FastAPI |
| **Config Service** | CRUD for tenants/projects/users/connectors/pipelines | FastAPI + SQLAlchemy |
| **Trigger Dispatcher** | Outbox → Redis Streams → Temporal `start_workflow` | Python service |
| **Temporal** | Workflow orchestration, retries, durability | Temporal Cluster |
| **Workers** | Independent processes per task queue (extractor, enricher, chunker, captioner, raptor, embedder, indexer) | Python (Temporal SDK) |
| **Retrieval Service** | Hybrid search + rerank + parent-promotion + context packing | FastAPI |
| **Reranker Service** | Cross-encoder reranking | FastAPI + GPU pod |
| **Agent Runtime** | Admin-configured, user-executed agents over retrieved context | Python, LangGraph + Temporal envelope, MLflow 3.10 observability — full detail in **Part II** |
| **Postgres** | Configuration, lineage, audit, chunk pointers | Postgres 16+ |
| **Qdrant** | Vector + sparse + payload-filtered search | Qdrant 1.10+ |
| **Object Store** | Raw documents, interim artifacts, image files, thumbnails | MinIO (S3-compatible) |
| **Redis** | Event streams, ephemeral caches, rate-limits | Redis 7 with AOF |
| **VLM** | Image captioning at ingest | Claude Sonnet Vision / Qwen2-VL / GPT-4o-mini |
| **Embedder** | Text → dense + sparse vectors | Voyage-3-large + SPLADE; or BGE-M3 (does both) |
| **Reranker** | Cross-encoder | Voyage rerank-2, Cohere rerank-3, BGE-reranker-v2-m3 |

---

## 3. Data & Storage Layers (Who Stores What)

The single most important architectural rule: each system owns one kind of state. No duplication, no drift.

| Layer | Stores | Doesn't Store |
|---|---|---|
| **Postgres** | Tenants, projects, users, connectors, datasources, pipelines (YAML + parsed), documents, document_versions, pipeline_runs, stage_runs, chunks (text + payload), virtual_clusters, events outbox, audit, lifecycle policies, agents | Workflow execution state, raw bytes, vectors |
| **Object Store** | Raw uploaded/fetched bytes, per-stage interim outputs, canonical DOM JSON (optional cache), image files + thumbnails | Anything searchable |
| **Qdrant** | Dense vectors, sparse vectors, image CLIP vectors (optional), payload (denormalized chunk metadata for filtering) | Source of truth for text — that's Postgres |
| **Temporal** | Workflow + activity execution state, retries, heartbeats, history | Business data |
| **Redis Streams** | In-flight events (bounded window), DLQ | Long-term truth — that's Postgres `events` |

The chunk text is stored twice — in Postgres (source of truth, joins, lineage) and in Qdrant payload (denormalized for retrieval). Postgres wins on conflict.

---

## 4. The Canonical DocumentDOM Contract

The single architectural rule that makes "one knowledge base across all pipelines" actually work. Every extractor (PDF, DOCX, HTML, SharePoint, SQL, Confluence, code) MUST produce this structure. After the DOM is built, no downstream stage knows which pipeline produced it.

```
DocumentDOM {
  doc_id, version, project_id, tenant_id,
  doc_type,           // pdf | docx | html | sharepoint_page | sql_row | ...
  source_uri,
  title,
  language,
  breadcrumbs[],      // [Space > Page > H1 > H2 > H3]
  acl_groups[],       // copied from source system
  metadata{},         // custom fields (capped per project)
  sections[ {
    id, level, heading, path,
    blocks[ {
      type,           // paragraph | heading | table | code | image | list | quote
      text,           // present for text-bearing blocks
      page,           // PDF/DOCX
      bbox?,          // visual position
      table?,         // structured table (markdown + JSON twin)
      code_lang?,
      image?: { sha256, width, height, mime, ocr_text?, alt_text? }
    } ]
  } ]
}
```

Validate with JSON Schema at the pipeline boundary. A connector that can't produce sections (e.g., a SQL row) emits a single synthetic section.

---

## 5. Admin Flow — Step by Step

The admin journey, from empty system to indexed corpus.

### 5.1 Provision Tenant
1. Super-admin creates tenant (`POST /tenants`) → row in `tenants`, default lifecycle policies inserted, system audit log entry.
2. Tenant admin invited via email → first login bootstraps OIDC subject.

### 5.2 Create Project
1. Tenant admin creates project → `projects` row inserted.
2. **Bootstrap event** triggers project initializer:
   - Qdrant collection `project_{uuid}` created with the full payload-index plan and named vectors declared (dense_text, sparse_text, image_clip).
   - Object-store prefix created: `raw/{tenant}/{project}/`, `interim/...`, `images/...`.
   - Default virtual clusters seeded (`All`, `Last 90 days`, `My team`).

### 5.3 Configure Connectors
1. Tenant admin defines a connector (`POST /connectors`) — type, non-secret config, secret-manager reference for credentials.
2. Health-check call validates connectivity → `connectors.health_status = 'healthy'`.
3. Connector is now reusable across projects in the tenant.

### 5.4 Attach Datasource to Project
1. Project admin attaches a connector instance with project-scope config (which SharePoint site, which folder, which SQL query) → `datasources` row.
2. Optional cron schedule for periodic sync.

### 5.5 Define / Choose Pipeline
1. Admin opens the **Pipeline Editor** (Monaco YAML + side-by-side DAG render).
2. YAML is validated against schema on save → both `yaml_spec` text and `parsed_spec` JSONB stored, `lifecycle = 'draft'`.
3. **Dry-run** runs the pipeline against a sample document, returns each stage's output without persisting — admin inspects, iterates.
4. On promote: `lifecycle = 'active'`, `activated_at` stamped. Previous active version → `deprecated`.
5. **Pipeline binding** rule: `(project, datasource, doc_type) → pipeline`. Project default is fallback.

### 5.6 Ingest Documents
Two entry points:

**A. Upload**
1. User uploads a file via UI → API streams bytes to `object_store://raw/...`.
2. Row inserted in `documents`, immutable `document_versions` row with `minio_raw_uri` and `content_hash`.
3. `events.document.uploaded` outbox row written in same transaction as the document row.

**B. Connector sync**
1. Scheduled or manual sync calls the connector worker.
2. Worker enumerates source, writes raw bytes to object store, emits `documents` + `document_versions` rows.
3. **Dedup by `content_hash`** — same hash within a doc → no new version; new doc with same hash → reference existing bytes.
4. Outbox events emitted per new/changed document.

### 5.7 Pipeline Execution (Section 6 in detail)
The outbox dispatcher consumes the event, looks up the binding, starts a Temporal workflow.

### 5.8 Run Observatory
Admin watches live in the UI:
- Per-tenant throughput, success rate, p95 stage latency.
- Drill into a failed run → see the stage that failed, its input/output artifact URIs, the error message, retry button.
- DLQ inspector for poison messages.

### 5.9 Reindex
When a pipeline changes (new chunker, new embedder), admin clicks **Reindex** on the pipeline → trigger dispatcher re-emits `document.reindex` events for every doc bound to that pipeline. Each runs the new pipeline version; Qdrant points are upserted with the new `pipeline_version`; afterward a sweeper deletes points with `pipeline_version < N`. Zero downtime.

---

## 6. Ingestion Pipeline — Step by Step

The end-to-end document journey from raw bytes to query-ready chunks. Every stage is a Temporal activity on its own task queue; workers scale independently.

```
[event] → [Trigger Dispatcher] → [Temporal workflow] → 11 stages → [chunks live in Postgres + Qdrant]
```

### Stage 0 — Trigger
- Outbox dispatcher reads unpublished rows from `events`, publishes to Redis Streams.
- A Redis consumer in the dispatcher looks up the binding and calls `Temporal.start_workflow(IngestDocument, ctx)` with `workflow_id = "{tenant}:{doc}:v{version}:{pipeline_version}"` (idempotent — duplicate starts are rejected).

### Stage 1 — Fetch
- Pulls raw bytes (already in object store for uploads; fetched fresh for connector pulls if needed).
- Output: `raw_uri` (already present).

### Stage 2 — Extract → DocumentDOM
- Pipeline-type-specific worker (PDF extractor, DOCX extractor, HTML parser, SQL row mapper).
- Produces the canonical DOM. Tables become structured blocks (markdown + JSON twin). Images are extracted as separate files to `object_store://images/{tenant}/{project}/{doc}/v{n}/{image_sha256}.{ext}`, with a thumbnail twin.
- For scanned PDFs: OCR runs as part of this stage.
- Output: `canonical_dom.json` artifact + image files written.

### Stage 3 — Image Captioning (parallel fan-out)
- For each image block in the DOM, a captioner activity runs in parallel.
- VLM prompt includes surrounding text + section breadcrumbs so captions are contextual.
- Caption hashed and cached by image SHA-256 — same logo across 10K docs is captioned once.
- Output: `{caption, ocr_text, type, entities[]}` merged back into the DOM image block.

### Stage 4 — Enrichment
- Language detection (confirms/overrides `language`).
- Topic classification (`doc_class`).
- Entity extraction (people, orgs, products → into `metadata.entities`).
- PII detection → `pii_status` flag.
- Output: enriched DOM.

### Stage 5 — Parent-Child Chunking
- Hard boundaries: never split across section, table, or code-block edges.
- **Parents** (~1500–2500 tokens) snap to section boundaries.
- **Children** (~300–500 tokens) split parents by sentence/paragraph with ~15% overlap.
- Tables become single chunks. Code blocks become single chunks. Images become single chunks (caption + OCR as `display_text`).
- Output: `chunks` rows inserted in Postgres with `parent_chunk_id`, `kind`, `ordinal`, `section_path`, `page_number`, and the chunk text — but no vectors yet.

### Stage 6 — Contextualization (Anthropic technique)
- For each child chunk, a cheap LLM generates 50–100 tokens of situating context using the parent chunk + document title as input.
- Stored as `embedding_text` (separate from `display_text`).
- This is the single biggest retrieval-quality lever — empirically reduces retrieval failures by 35–49%.

### Stage 7 — RAPTOR Summarization
- Cluster L1 children using UMAP→10d→GMM-with-BIC (soft cluster membership).
- Summarize each cluster with a strict-grounding prompt; store cited `source_chunk_ids` in payload.
- Re-cluster summaries → L2 → L3 (3 levels max).
- Each summary becomes its own chunk row with `kind='raptor_summary'`, `raptor_level=1|2|3`.

### Stage 8 — Embedding
- One embedder, one model per tenant (locked).
- Inputs to embed: L0 propositions (if enabled), L1 contextualized children, RAPTOR L1/L2/L3 summaries. **Parents are not embedded** — they're fetched by reference.
- Produces dense + sparse vectors per chunk.
- Output: vectors in memory, ready to upsert.

### Stage 9 — Index
- Single upsert per chunk into the project's Qdrant collection.
- Named vectors: `dense_text`, `sparse_text`, optionally `image_clip` (for image chunks if CLIP is enabled).
- Payload includes the full canonical metadata schema (Section 9.4 below).
- `qdrant_point_id` written back to the `chunks` row in Postgres.

### Stage 10 — Finalize
- `document_versions.is_current = TRUE` for the new version; previous version flipped to `FALSE`.
- `documents.current_version` updated.
- `documents.status = 'indexed'`.
- Audit log entry written.
- `events.document.indexed` outbox row emitted (consumers: analytics, notifications, downstream agents).

### Failure Handling
- Each stage has `retry: {max: 3, backoff: exponential}` per the YAML.
- After max retries, the message goes to `ingestion.dlq` stream.
- Temporal preserves the workflow history; admin can `Resume from stage X` after a fix.
- The previous `document_version` stays as `is_current=TRUE` until the new one finishes — readers never see a half-indexed doc.

---

## 7. Retrieval & User Flow — Step by Step

> Section 7.1's agent-picker step is now governed by Part II §A2.7 (User Flow — execution only): the agent list returned is the project's active, frozen configuration, filtered by the user's role. The mechanics below (retrieval call, generation, tool calls, provenance) are unchanged.

### 7.1 User Lands
1. User authenticates → JWT carries `tenant_id`, `user_id`, `groups[]`.
2. UI calls `GET /projects` (filtered by membership) → user picks a project.
3. UI calls `GET /agents?project={p}` → user picks an agent (or default chat agent) — **now scoped to the project's active Project Agent Configuration, see Part II §A2.5 and §A2.7**.
4. UI calls `GET /virtual_clusters?project={p}` → user optionally narrows scope ("Legal 2024", "Finance Confluence").
5. User picks output language and persona (persona selection added by Part II §A2.1).

### 7.2 User Asks a Question
1. UI POSTs `/chat` with `{project_id, agent_id, cluster_id, language, message, history}`.
2. **Agent Runtime** loads the agent's skeleton + prompt (Part II §A2.4) — system prompt, tools, retrieval policy.
3. Agent decides: does this turn need retrieval? (Most turns do; some don't.)

### 7.3 Retrieval Service Call
Inputs: `{project_id, query, cluster_id, user_groups, top_k, modality_hint}`.

```
Step 1 — Resolve filters
  cluster.filter_spec  ∧  {project_id}  ∧  {acl_groups ⊇ any(user_groups)}
  ∧  {language ∈ project.supported_languages}

Step 2 — Query analysis (small router model, ~50ms)
  - classify intent (factual | conceptual | thematic | multi-hop | visual)
  - decompose if multi-hop → N sub-queries
  - HyDE-expand if abstract/short → embed hypothetical answer instead

Step 3 — Hybrid retrieval (per sub-query)
  - dense search top-50 on dense_text
  - sparse search top-50 on sparse_text
  - RRF fuse → top-50
  - layer weights applied by intent:
      factual    : boost L0, normal L1, suppress L3
      conceptual : normal L0, boost L1, normal L3
      thematic   : suppress L0, normal L1, boost L3

Step 4 — Cross-encoder rerank top-50 → top-10

Step 5 — Parent promotion + image enrichment
  - text children whose parents are in result → replace child with parent, dedupe
  - image hits → attach file_uri + thumb_uri for UI / VLM

Step 6 — Modality balance
  - cap any single modality at 30% unless query is explicitly visual

Step 7 — Context pack
  - fill token budget (e.g., 8K), prefer diversity over depth
  - include citations: doc_id, section_path, page, source_uri
```

### 7.4 Generation
1. Agent calls the LLM with the retrieved context + system prompt + history.
2. LLM is required to cite using chunk_ids; UI maps citations back to source links.
3. Output language ≠ source language → **no translation step**; the LLM generates directly in the target language from English context (Part II §A2.8 decision #11, backed by Appendix D.6).

### 7.5 Tool Calls (Agentic Steps)
- The agent may call tools mid-turn: another retrieval, a SQL query through a sanctioned connector, a calculation, an external API.
- Each tool call is logged for audit; tools are scoped by the user's project ACL **and** the role-based tool allowlist (Part II §A2.12).

### 7.6 Response + Provenance
- UI renders the answer with inline citations.
- Each citation shows: document title, section breadcrumb, page, link to view in the document inspector, optionally a thumbnail for image citations.
- Feedback buttons (thumbs up/down, "this citation is wrong") write to a `feedback` table → tuning signal for reranker and pipeline tuning, **and feeds the Part II §A2.10 feedback loop and the Agent Observatory (§A2.6)**.

---

## 8. Cross-Cutting Concerns

### 8.1 Multi-Tenancy & ACL
- **Tenant isolation:** `tenant_id` is a required filter on every Postgres query and Qdrant search. Enforced in the FastAPI middleware, not by convention.
- **Project ACL:** users have `project_memberships` rows; every retrieval call filters by `acl_groups ⊇ user.groups`.
- **Document ACL:** carried through from source (SharePoint permissions, Confluence space ACLs, SQL row filters) into chunk payload — no separate ACL store.
- **One Qdrant collection per project** is itself a coarse isolation layer.

### 8.2 Security
- Connector credentials never in Postgres plaintext — reference Vault / AWS Secrets Manager / Azure Key Vault by URI.
- API tokens hashed (sha256) in `api_keys.key_hash`; only prefix shown in UI.
- All inter-service calls within VPC; external endpoints behind WAF.
- PII detection at ingest → `pii_status` field → virtual clusters can include/exclude redacted-only content.

### 8.3 Observability
- **Logs:** structured JSON, correlation ID = Temporal `workflow_id` for ingestion, request_id for retrieval.
- **Metrics (Prometheus):** per-stage latency histograms, per-tenant throughput, per-project chunk counts, Qdrant payload-index memory, embedder QPS, reranker p95.
- **Traces (OpenTelemetry):** retrieval pipeline traced end-to-end (intent → hybrid → rerank → promote → pack → LLM).
- **Dashboards:** run observatory + retrieval quality (avg rerank score, citation click-through, thumbs-down rate). Agent-runtime observability is MLflow 3.10-based — see Part II §A2.6 (Agent Observatory).

### 8.4 Cost Discipline
- **Embedder & VLM caching by content hash** — never re-embed or re-caption identical content.
- **Reranker is the most expensive per-query step** — rate-limit and budget per tenant.
- **RAPTOR summarization uses Haiku-class models**, not Opus/Sonnet — quality is sufficient at 1/10 cost.
- **Lifecycle policies** auto-delete interim artifacts (default 30d) and archive raw beyond 1y.

### 8.5 Data Lifecycle
- Per tenant + per project policies in `lifecycle_policies`.
- A daily sweeper job applies policies to object store and Postgres.
- Right-to-erasure: delete a document → cascade to versions, chunks, Qdrant points, image files, audit retains action only.

### 8.6 Disaster Recovery
- Postgres: streaming replica + daily logical backups.
- Qdrant: native snapshots to object store (daily).
- Object store: cross-region replication for raw + canonical buckets.
- Temporal: own cluster with multi-AZ persistence.
- Recovery test: re-ingest a sampled corpus monthly from raw bytes → verifies reproducibility.

---

## 9. Data Model References

### 9.1 Postgres Schema
See `config_db_scripts/001_create_schema.sql`. Eighteen tables; the load-bearing ones are: `tenants`, `projects`, `users`, `connectors`, `datasources`, `pipelines`, `pipeline_bindings`, `documents`, `document_versions`, `pipeline_runs`, `pipeline_stage_runs`, `chunks`, `virtual_clusters`, `events`, `lifecycle_policies`, `audit_log`, `agents`. Agent-runtime tables (extending `agents` and adding `personas`, `tools`, `skills`, `hooks`, `role_permissions`, `project_registry_bindings`, `project_agent_configs`, `usage_ledger`) are specified in Part II §A2.14.

### 9.2 Pipeline YAML Skeleton
```yaml
name: sharepoint-pdf-v3
version: 3
applies_to: { doc_types: [pdf], datasource_types: [sharepoint] }
triggers:
  - type: event
    source: redis_stream
    topic: documents.uploaded
stages:
  - { id: extract,   worker: pdf_extractor,        params: {ocr: auto} }
  - { id: caption,   worker: image_captioner,      depends_on: [extract] }
  - { id: enrich,    worker: metadata_enricher,    depends_on: [caption] }
  - { id: chunk,     worker: parent_child_chunker, depends_on: [enrich] }
  - { id: context,   worker: contextualizer,       depends_on: [chunk] }
  - { id: raptor,    worker: raptor_summarizer,    depends_on: [context] }
  - { id: embed,     worker: embedder,             depends_on: [raptor] }
  - { id: index,     worker: qdrant_indexer,       depends_on: [embed] }
on_failure: { retry: {max: 3, backoff: exponential}, dead_letter: ingestion.dlq }
```

### 9.3 Qdrant Collection Bootstrap
At project creation:
- Collection name: `project_{project_uuid}`
- Named vectors: `dense_text` (1024-dim cosine), `sparse_text` (sparse), `image_clip` (768-dim cosine, optional)
- HNSW: m=16, ef_construct=200
- Payload indexes declared up-front for every filterable field (see 9.4).

### 9.4 Canonical Qdrant Payload
```
{
  // identity
  chunk_id, document_id, document_version, project_id, tenant_id,

  // layer
  layer,                  // proposition | child | parent | raptor
  raptor_level,           // 0 | 1 | 2 | 3
  modality,               // text | image | table | code
  parent_chunk_id,
  source_chunk_ids,       // raptor summaries: leaves they cover
  child_chunk_ids,

  // text
  display_text,
  embedding_text_hash,

  // provenance
  doc_type, source_system, source_uri,
  page_number, section_path, breadcrumbs[],

  // image (only on modality=image)
  image: { file_uri, thumb_uri, sha256, width, height, mime, type, entities[], ocr_text },

  // semantics
  language, token_count, content_hash,
  pipeline_id, pipeline_version, embedded_at, embedding_model,

  // governance
  acl_groups[], sensitivity, pii_status, retention_class,

  // ranking signals
  doc_recency_ts, doc_authority_score,

  // tenant-defined (capped at 32 indexed fields per project)
  metadata: { ...custom... }
}
```

### 9.5 Event Schema (Redis Streams)
```
{
  event_id, event_type, tenant_id, project_id,
  aggregate_type, aggregate_id, document_id, document_version,
  triggered_by, timestamp
}
```

---

## 10. Implementation Roadmap

A pragmatic build sequence — each milestone is independently demoable.

### Milestone 1 — Foundations (Week 1–3)
- Postgres schema deployed (DDL ready in `config_db_scripts/`).
- FastAPI gateway with auth (OIDC), RBAC middleware, tenant/project/user CRUD.
- React shell: tenant + project list, user invite.
- Object store + Qdrant + Redis + Temporal running locally via Docker Compose.

### Milestone 2 — Single Pipeline End-to-End (Week 4–6)
- Canonical DOM schema published.
- One extractor: PDF.
- Bare-minimum pipeline: extract → chunk (parent-child only) → embed → index.
- Upload UI works; user can ask a question and get text answers with citations.
- **This is the spine.** Everything else is enrichment.

### Milestone 3 — Pipeline Configurability (Week 7–8)
- YAML editor in admin UI, schema validation, dry-run.
- Versioned pipelines, bindings table, lifecycle (draft/active/deprecated).
- Trigger dispatcher (outbox → Redis → Temporal).
- Run observatory: live status, retry, DLQ.

### Milestone 4 — Retrieval Quality (Week 9–10)
- Contextual chunking (the 35–49% quality lever).
- Hybrid retrieval (dense + sparse + RRF).
- Cross-encoder reranking.
- Parent promotion, modality balance.

### Milestone 5 — RAPTOR + Virtual Clusters (Week 11–12)
- RAPTOR summarizer stage.
- Per-layer query weighting by intent.
- `virtual_clusters` table + UI for create/edit/select.
- Payload-index discipline enforced.

### Milestone 6 — Multimodal (Week 13–14)
- Image extraction during DOM build.
- VLM-based contextual captioning.
- Image files stored under SHA-256 paths with thumbnails.
- Multimodal retrieval (caption-text embed; optional CLIP).

### Milestone 7 — Connectors (Week 15–18)
- SharePoint, Confluence, S3, SQL, NoSQL — one per sprint.
- Each connector implements the canonical DOM contract.
- Per-connector ACL passthrough.

### Milestone 8 — Agents (Week 19–22)
- Superseded/detailed by Part II. Summary: Agent & Registry Console, Project Agent Configuration (freeze workflow), LangGraph runtime + Temporal envelope, tool framework (native + internal MCP), per-agent/persona retrieval policies, Agent Observatory dashboard.

### Milestone 9 — Production Hardening (Week 23–24)
- Lifecycle policies enforced by sweeper jobs.
- DR drills (restore from snapshot, re-ingest from raw).
- Cost dashboard per tenant (extends into the Part II Agent Observatory §A2.6 for agent-runtime cost).
- SLO dashboards + alerting.

### Milestone 10 — Reindex & Migration Tooling (Week 25–26)
- Safe reindex on pipeline-version bump.
- Embedding-model migration playbook (parallel collection, dual-write, cutover).
- Per-tenant export/import.

---

## 11. Design Principles (Why It Looks This Way)

A few non-obvious choices worth restating, because they shape everything:

1. **Each system owns one kind of state.** No duplication. Postgres = config + lineage; Object store = bytes; Qdrant = vectors + denormalized payload; Temporal = execution; Redis = ephemeral events. Drift between systems is the failure mode that kills platforms in year two. This same principle governs agentic memory in Part II — retrieved chunk text is passed by reference into agent state, never duplicated into LangGraph checkpoints.

2. **The canonical DocumentDOM is the only contract pipelines must satisfy.** Everything downstream of the DOM is uniform — single chunker, single embedder, single retriever, single ranker. That's how "one knowledge base" stays one knowledge base.

3. **One Qdrant collection per project, with discipline.** All four index layers, all modalities, all virtual clusters live in the same collection — distinguished by payload, filtered by indexes declared at creation. Virtual clusters are *filters*, not *collections*. Agentic memory (Part II §A2.9) gets its own, separate collection namespace — never mixed with the knowledge-base collection.

4. **Versioning is mandatory at three levels:** pipelines, document_versions, embedding_model. Without this you cannot reindex safely. Part II extends this discipline to agents, personas, tools, skills, and Project Agent Configurations.

5. **Quality compounds.** Contextual chunking (35–49% lift), hybrid retrieval (covers exact-match gaps), reranking (largest single lift after contextualization), parent promotion (gives the LLM enough context to reason), RAPTOR (covers thematic queries). Each addresses a different failure mode; together they're additive.

6. **Reindexing is a first-class operation.** It will happen. New chunker, new embedder, new contextualizer prompt. The system is designed so reindex is `pipeline_version++ → upsert → sweep`, not a migration project.

7. **The admin UI's three load-bearing screens are: Pipeline Editor, Document Inspector, Run Observatory.** Build these three well and the platform feels professional; skimp on them and ops will hate it. Part II adds three more load-bearing screens for the agent runtime: Agent & Registry Console, Project Agent Configuration, Agent Observatory.

---

## 12. Open Decisions Worth Resolving Early

**Resolved 2026-07-02** — every "or" below was a cloud-vendor-lock risk. Locked in favor of the fully self-hosted, Docker-deployable side of each choice, so the stack runs identically on any cloud or on-prem. Working `docker-compose.yml` for the infra layer: `docker/docker-compose.yml`.

| Decision | Locked Choice | Reason |
|---|---|---|
| Embedding model | **BGE-M3** (self-hosted), not Voyage-3-large | Apache-2.0, runs in a GPU container you control; no external SaaS call in the retrieval hot path |
| VLM for captioning | **Qwen2-VL-7B** (self-hosted), not Claude/GPT-4o-mini | Ingest-time captioning shouldn't depend on an external API being up |
| Reranker | **BGE-reranker-v2-m3** (self-hosted), not Cohere/Voyage rerank | Same reasoning — self-hosted, Apache-2.0 |
| Object store | **MinIO, always** — including cloud deployments, not native S3/Azure Blob | S3-compatible API means app code never changes; using native S3/Blob directly is the lock-in this "or" was hiding |
| Authn | **Keycloak**, not Auth0 | Auth0 is SaaS; Keycloak is a container, same OIDC protocol |
| Secrets | **HashiCorp Vault** (self-hosted) | Not tied to AWS Secrets Manager or Azure Key Vault |
| Orchestration hosting | **Self-hosted Temporal**, not Temporal Cloud | Official Docker images, backed by your own Postgres |
| GenAI observability hosting | **Self-hosted MLflow 3.10**, not Databricks-managed | Docker image, Postgres backend store, MinIO artifact store |
| Chat/generation LLM & embedding access path | **Revisited 2026-07-08** — Chat/generation LLM stays API-based (Claude/GPT-class) but is now called through the **AI Gateway built into the self-hosted `mlflow` service** (MLflow >=3.0 bundles tracking + gateway in one process — no separate container/image), not a direct `anthropic` SDK call — still not via AWS Bedrock or Azure OpenAI Service. Routes (`chat`, `contextualizer`) are created against that service's REST API by `docker/scripts/bootstrap-mlflow-gateway.sh`, which also holds the only pre-encryption copy of `ANTHROPIC_API_KEY`. Embedding model (BGE-M3) stays a direct HTTP call to the self-hosted `embedder` service, unchanged — it returns dense+sparse vectors in one call, which the gateway's OpenAI-compatible embeddings shape can't represent without losing the sparse half hybrid retrieval depends on | Same axis as before (model-quality dependency, not cloud-infra dependency), plus: the gateway centralizes the provider API key as one encrypted secret instead of an env var on every backend/worker process, and lets the model/provider be swapped via the gateway's REST API/UI, no backend code change |
| Pipeline YAML extensibility | No user-Python; declarative-only for v1 | Sandbox burden isn't worth it yet |
| Qdrant cardinality strategy | One collection per project; revisit at 50M points | Operational simplicity wins until proven otherwise |
| Frontend state | TanStack Query + Zustand | Pairs well with FastAPI |

---

# PART II — AGENT RUNTIME (ADMIN CONFIGURATION + USER EXECUTION)

All agent/tool/skill/persona/hook configuration lives in the Admin flow; the User flow is execution-only, operating strictly within what an admin has enabled and frozen for that project. This fills Part I decision #21. Section numbers in this Part are prefixed `A2.` to keep them unambiguous alongside Part I's numbering.

## A2.0 Relationship to Part I

- Extends `agents` (table 18, `config_db_scripts/001_create_schema.sql`) and reuses the exact versioned/draft/active/deprecated lifecycle already locked for `pipelines` (Part I decision #4, §5.5).
- Reuses the existing datasource→project attachment flow (Part I §5.4) as the upstream step in one continuous admin journey: **onboard datasources → attach to project → enable agents/tools/skills/personas for that project (new) → freeze → grant role access (new) → users execute.**
- Retrieval Service, Qdrant knowledge-base collections, and the ingestion pipeline (Part I §1–§10) are untouched.

---

## A2.1 Functional Split — Admin Configures, Users Execute

The core design. Registries (agent/persona/tool/skill/hook) have one clear owner:

| Responsibility | Owner | Where |
|---|---|---|
| Define agent skeletons (tools, hooks, memory policy, planning strategy) | Tenant/project admin | Admin — Agent & Registry Console |
| Define personas (prompt + data scope + tool allowlist) | Tenant/project admin | Admin — Agent & Registry Console |
| Register native tools + internal MCP servers | Tenant admin | Admin — Agent & Registry Console |
| Author/approve skills (incl. feedback-loop candidates) | Project admin | Admin — Agent & Registry Console |
| Configure hooks (guardrail bindings) | Tenant admin | Admin — Agent & Registry Console |
| Select which agents/personas/tools/skills apply to a project | Project admin | Admin — Project Agent Configuration |
| Map roles to allowed agents/personas/tools | Project admin | Admin — Project Agent Configuration |
| Freeze a project's agent configuration (v1, v2, ...) | Project admin | Admin — Project Agent Configuration |
| View usage stats + quality metrics, per item and per project | Tenant/project admin | Admin — Agent Observatory (dashboard) |
| Approve/reject feedback-loop prompt optimizations and candidate skills | Project admin | Admin — Agent Observatory (dashboard) |
| Pick project, agent, persona, language; run agent; give feedback | End user | User flow — execution only |

A user's `GET /agents?project={p}` call (Part I §7.1) returns strictly the subset in that project's **active** (frozen) configuration, further filtered by the user's role — not the tenant's full registry. Users never create, modify, or enable a registry item.

---

## A2.2 System at a Glance

```
┌─────────────────────────────── ADMIN — CONFIGURATION PLANE ───────────────────────────────┐
│                                                                                              │
│  Agent & Registry Console                    Project Agent Configuration                    │
│  ┌────────────┬────────────┬─────────────┐   ┌──────────────────────────────────────────┐  │
│  │ Agent reg. │ Persona    │ Tools reg.   │   │ Select enabled: agents[] personas[]        │  │
│  │ (skeleton  │ registry   │ (native+MCP, │   │ tools[] skills[]  (from tenant registry)   │  │
│  │ + prompt_  │            │ internal)    │   │ Role → allowlist mapping (role_permissions)│  │
│  │ ref)       │            │              │   │ Draft → Dry-run/Preview → PROMOTE (freeze) │  │
│  ├────────────┼────────────┼─────────────┤   │ → previous version deprecated               │  │
│  │ Skills reg.│ Hooks reg. │              │   │  = project_agent_configs (versioned)         │  │
│  │ (incl.     │            │              │   │                                              │  │
│  │ candidates)│            │              │   │                                              │  │
│  └────────────┴────────────┴─────────────┘   └──────────────────────────────────────────┘  │
│                                                                                              │
│  Agent Observatory (dashboard)                                                               │
│  ┌────────────────────────────────────────────────────────────────────────────────────────┐│
│  │ Stats: enablement count, invocations, error rate, p95 latency, cost (usage_ledger)       ││
│  │ Quality: RAGAS, RLC, persona-consistency, feedback rate, eval-regression history          ││
│  │ Approval queue: prompt-optimization candidates, skill candidates (feedback loop, §A2.10)  ││
│  └────────────────────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────┬───────────────────────────────────────────────┘
                                                 │ freeze/promote → active project_agent_config
                                                 ▼
┌─────────────────────────────── USER — EXECUTION PLANE ────────────────────────────────────┐
│  React UI: project picker → agent picker (frozen subset only) → persona → language → chat   │
│                                                  │ HTTPS/JWT (tenant_id, user_id, groups[])   │
│                                                  ▼                                           │
│  Agent Gateway (FastAPI): RBAC check against role_permissions (admin-configured, read-only    │
│  here) · rate-limit check · session bootstrap                                                │
│                                                  ▼                                           │
│  Temporal (durable envelope — long tasks, HITL pauses, retries)                              │
│                                                  ▼                                           │
│  LangGraph Runtime (per session)                                                             │
│    Hooks: SessionStart → PreAgentCall → PreToolUse → [tool] → PostToolUse → PostAgentCall     │
│    → ... → SessionEnd                                                                        │
│    Planning: ReAct | Plan-and-Execute | ReWOO | LLM Compiler | Reflexion (risk-gated)          │
│    Topology: Supervisor + parallel workers (complexity-gated fan-out)                          │
│       ↓                    ↓                   ↓                    ↓                       │
│  Tools registry        Skills registry      Agentic memory       Retrieval Service            │
│  (read-only lookup)    (read-only lookup)   (memU: Resource/     (existing, Part I §7.3)       │
│                                              Item/Category,                                     │
│                                              CoALA-mapped,                                      │
│                                              pluggable)                                        │
│                                                  ↓                                           │
│  MLflow 3.10 (Tracing, Evaluation, Prompt Registry, AI Gateway) — OTel-native, GenAI            │
│  semantic conventions ── rollup ──► usage_ledger + feedback (Postgres) ──► Agent Observatory   │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

The dashed boundary matters: everything above the line is admin-authored config; everything below reads that config but never writes it.

---

## A2.3 Component Inventory

| Component | Role | Tech | Owner |
|---|---|---|---|
| Agent & Registry Console | CRUD for agents/personas/tools/skills/hooks | React admin UI + FastAPI | Admin |
| Project Agent Configuration | Select/bind registry items to a project, role mapping, freeze | React admin UI + FastAPI | Admin |
| Agent Observatory | Usage stats, quality metrics, approval queue | React admin UI, MLflow-backed | Admin |
| Agent Gateway | AuthN/RBAC/rate-limit entry point for chat | FastAPI | Backend (User-facing) |
| Durable envelope | Long-running agent tasks, HITL pauses, retries | Temporal (reused from ingestion) | Backend |
| Reasoning runtime | Per-session graph execution, checkpointing, streaming | LangGraph | Backend |
| Hooks layer | Deterministic guardrail/observability injection | Custom middleware, framework-independent | Backend |
| Agentic memory | Working/episodic/semantic/procedural (CoALA-mapped) | memU default (Resource/Item/Category layers), pluggable adapter | Backend |
| Prompt management | Versioned prompt content, alias-based instant rollout | MLflow Prompt Registry | Admin authors, backend reads |
| Observability | Tracing, evaluation, GenAI OTel export | MLflow 3.10 | Backend, surfaced in Admin |
| Access control | Role → permission → allowlist(agents, personas, tools) | Simple RBAC (Sandhu model), no ABAC | Admin authors, backend enforces |
| Rate limiting | Token-bucket per user/project/tenant | Redis, fed by metering events | Backend |
| Metering | Multi-dimensional usage attribution, chargeback source of truth | Postgres `usage_ledger` + Redis counters | Backend, surfaced in Admin |
| Feedback loop | Signal collection → prompt/memory/skill improvement | MLflow GEPA optimizer + rollup job | Backend generates, Admin approves |
| Multi-org marketplace | Cross-org agent publish/discover, A2A, sandboxing | — | **Deferred** |

---

## A2.4 Admin — Agent & Registry Console

Tenant-scoped CRUD, one screen per registry, all following the same versioned/immutable-per-version discipline as `pipelines`:

| Registry | Admin actions | Notes |
|---|---|---|
| **Agent registry** | Create/edit skeleton (tools, hooks, memory policy, planning strategy), point `prompt_ref` at an MLflow Prompt Registry entry, version, activate/deprecate | Skeleton changes require a new version (session-pinned); prompt content inside an already-enabled agent can update immediately via MLflow alias without a new skeleton version or project refreeze |
| **Persona registry** | Create/edit (`prompt_ref`, `data_scope`, `tool_allowlist`), version | Reusable across multiple agents/projects |
| **Tools registry** | Register native functions; register internal MCP servers (capability manifest, connection info); semantic index over tool descriptions | No public MCP registry reach — internal catalog only |
| **Skills registry** | Author skills directly, or review/approve candidate skills surfaced by the feedback loop (§A2.10) | Candidate → active promotion requires explicit admin approval, never auto-published |
| **Hooks registry** | Configure hook bindings (matcher pattern → action) | Tenant-wide by default; project-level overrides allowed |

---

## A2.5 Admin — Project Agent Configuration (the freeze workflow)

The binding layer connecting tenant-wide registries to a specific project — the exact analog of the existing **pipeline binding** pattern (`(project, datasource, doc_type) → pipeline`, Part I §5.5), applied to agents:

**`(project) → {enabled agents[], personas[], tools[], skills[]} + role_permissions`**, versioned.

### A2.5.1 Workflow

1. **Draft** — project admin selects, from the tenant's registries, the subset of agents/personas/tools/skills this project needs. A validation pass checks referential integrity: an enabled agent's skeleton must only reference tools/skills also enabled for the project.
2. **Role mapping** — admin assigns which project roles (from `project_memberships`) may use which agents/personas/tools, populating `role_permissions`.
3. **Dry-run / preview** — admin runs a test session as a given role/persona before promoting, same spirit as the Pipeline Editor's dry-run against a sample document.
4. **Promote (freeze v1)** — `status = 'active'`, `activated_at` stamped; the prior active configuration flips to `deprecated`. From this point, users see and can only invoke what's in the active configuration.
5. **Iterate** — a later change is a new draft → dry-run → promote cycle (`v2`, `v3`, ...). Prompt-content-only changes (via MLflow alias) don't require a new version.

### A2.5.2 Why versioned, not live-edited

Same reasoning as pipelines and agent skeletons: "which agents could this user access, under which role, on this date" must be answerable from an immutable record, not reconstructed from an edit log.

---

## A2.6 Admin — Agent Observatory (Dashboard)

Admin screen, sibling to the existing Run Observatory (Part I §5.8), for the agent runtime instead of ingestion. Pairs aggregate stats with quality/eval signal in one screen, per the enterprise agent-monitoring convention of not splitting operational and quality monitoring across separate tools.

### A2.6.1 Stats (availability + usage)

| Metric | Source | Grain |
|---|---|---|
| Enablement count (how many projects have this item active) | `project_registry_bindings` | Per agent/persona/tool/skill |
| Invocation count, active sessions | MLflow trace rollup | Per agent, per project |
| Error rate, p95 latency | MLflow trace rollup | Per tool/skill |
| Token/cost consumption | `usage_ledger` | Per agent/project/user (chargeback view) |
| Availability status | Registry tables (`active`/`deprecated`/`candidate`) | Per item |

### A2.6.2 Quality

| Metric | Source | Grain |
|---|---|---|
| Faithfulness, answer relevancy, context precision/recall | RAGAS via MLflow Evaluation (LLM-as-judge) | Per agent |
| Response Language Correctness (RLC) | Custom scorer | Per agent × language |
| Persona-consistency score (PersonaGym-style, multi-turn) | Custom scorer | Per persona |
| Tool-call accuracy / task-completion (τ-bench-style, end-state correctness) | Custom scorer against connector state | Per agent, tool-write-capable only |
| Feedback thumbs-up rate, citation-wrong rate | `feedback` table | Per agent/persona |
| Eval-regression pass/fail history | MLflow Evaluation, tied to prompt-optimization promotions | Per prompt version |

### A2.6.3 Approval queue

Where the feedback loop (§A2.10) surfaces work for a human: pending GEPA-optimized prompt candidates awaiting an eval-gate + admin sign-off before their `production` alias moves, and pending candidate skills awaiting approval before entering the active Skills Registry. Keeps the self-improvement loop visible and admin-controlled rather than a silent background process.

---

## A2.7 User Flow (execution only)

1. User authenticates → JWT carries `tenant_id`, `user_id`, `groups[]`.
2. `GET /projects` (existing, filtered by membership).
3. `GET /agents?project={p}` — returns only the active `project_agent_configs` subset, filtered further by the user's role via `role_permissions`.
4. User picks agent, persona (same filtered list), language.
5. Chat proceeds: Temporal envelope → LangGraph runtime → hooks → tools/skills/memory/retrieval → MLflow tracing.
6. Feedback buttons write to `feedback`, feeding the Admin-side Agent Observatory and the feedback loop — the user generates signal, only an admin acts on it.

---

## A2.8 Locked Decisions

The following are the final agent-runtime contract, admin-side and user-side. Any implementation deviating from them is a bug, not a variant.

| # | Decision | Locked Choice | Reversibility |
|---|---|---|---|
| 1 | Reasoning framework | LangGraph — explicit state graph, checkpointing, streaming, interrupt/resume | Hard |
| 2 | Durable execution split | Temporal = outer task envelope; LangGraph checkpointer = inner reasoning loop | Medium |
| 3 | Multi-agent topology | Supervisor/orchestrator-worker only; debate/mixture-of-agents narrowly as a risk-gated verification step | Easy |
| 4 | Default planning pattern | ReAct; ReWOO/LLM Compiler for decomposable/parallel multi-tool turns; Reflexion risk-gated; ToT reserved for genuine multi-path search | Easy |
| 5 | Tool access pattern | Model-invoked, tools registry with semantic retrieval, not full-catalog context stuffing | Easy |
| 6 | Tool registry scope | Native + internal MCP servers only. No public MCP registry reach | Easy to expand later |
| 7 | Agent config split | Skeleton (version-pinned per session) vs. prompt content (MLflow alias, reflects immediately) | Easy |
| 8 | Memory taxonomy | CoALA-mapped: working=LangGraph state, episodic=memU (Memory Item Layer), semantic=memU (MemoryCategory Layer, optionally RAG-indexed on Qdrant), procedural=Skills Registry | Medium |
| 9 | Memory backend | **memU, default** (ADR-002, 2026-07-05, supersedes Mem0-default); pluggable adapter for Mem0/Zep/Graphiti per project | Easy |
| 10 | Memory organization | A-MEM-style structured/linked notes, not flat vectors — memU's Resource→Item→Category layering is the reference implementation | Easy |
| 11 | Language handling | No document translation; target-language generation instruction per-turn; RLC required eval metric | Trivial |
| 12 | Persona model | Prompt-level (MLflow alias) + data-scope narrowing + tool-allowlist subset; can only narrow access | Easy |
| 13 | Access control | **Simple RBAC** (Sandhu model) — role → static allowlist, enforced at `PreToolUse`/`PreAgentCall`. No ABAC for now | Easy to upgrade later |
| 14 | Rate limiting | Token-bucket per user/project/tenant, Redis, fed by metering events | Easy |
| 15 | Metering | Tag at `SessionStart`, propagate through hooks; MLflow trace = raw truth; `usage_ledger` = rollup/chargeback truth | Trivial |
| 16 | Observability | MLflow 3.10 — Tracing, Evaluation, Prompt Registry, AI Gateway | Hard |
| 17 | Feedback loop | Explicit + implicit signals → rollup → prompt optimization / episodic write-back / procedural candidates, all gated before promotion | Medium |
| 18 | Multi-org marketplace | Out of scope — see §A2.15 | Deferred |
| 19 | **Configuration ownership** | **All registry CRUD and project-agent binding lives in Admin. User flow is execution-only** | Hard |
| 20 | **Project freeze mechanism** | `project_agent_configs`, versioned draft → dry-run → active → deprecated, mirrors pipeline binding exactly | Medium |
| 21 | **Dashboard** | Agent Observatory — stats + quality + approval queue, one screen, admin-only | Easy |

---

## A2.9 Agentic Memory — Detail

### A2.9.1 CoALA Mapping

CoALA (Sumers et al., 2023) is the organizing frame — Appendix D.4. Four memory types, each mapped to existing infrastructure:

| CoALA type | KN_Valya component | Backend |
|---|---|---|
| Working | LangGraph state, checkpointed | Postgres checkpointer (chunk text passed by reference only — never store retrieved payloads in graph state, per the write-amplification failure mode in Appendix D.9) |
| Episodic | Session transcripts + distilled insights (ExpeL/Reflexion-style) | memU (Memory Item Layer) |
| Semantic | Long-term facts, preferences, persona history | memU (MemoryCategory Layer); RAG-mode retrieval indexes into a dedicated Qdrant collection namespace `mem_{tenant}_{project}` — separate from retrieval collections `project_{uuid}` |
| Procedural | Skills Registry, growable via feedback loop (Voyager-style) | Postgres |

### A2.9.2 Pluggable Backend Interface

```
write(memory_type, content, metadata) -> memory_id
search(query, memory_type, filters) -> [memory_note]
consolidate(scope) -> summary
```

**Default: memU** (ADR-002, 2026-07-05). memU implements this interface over its own three-layer store (Resource → Memory Item → MemoryCategory) and supports two `search` strategies selectable per project: RAG-based (embedding search, backed by the existing Qdrant instance) and LLM-based (direct structured-file reading, no embedding step). A project needing temporal-fact/graph reasoning, or the original Mem0 integration, can swap in Mem0/Zep/Graphiti behind the same interface via `memory_policy.backend` in the agent YAML (configured in Admin — Agent & Registry Console) — no agent-code change. Precedent: MemEngine's unified memory-slot paradigm and LangGraph's own `BaseStore` abstraction.

### A2.9.3 Note Structure

Each semantic/episodic write follows an A-MEM-style structured note (context description, keywords, tags, links to related notes), and retrieval is scored by relevance **and** recency/importance (Generative Agents precedent), not cosine similarity alone. memU satisfies this natively: its MemoryCategory layer is a self-evolving, linked-note structure (not a flat vector store), and its `consolidate()`-equivalent reorganizes categories as usage patterns shift — no additional glue code needed to meet decision #10.

---

## A2.10 Feedback Loop — Detail

Follows the four-stage loop from the self-evolving-agents survey (Appendix D.5): **signal collection → evaluation → update → gated redeployment**.

1. **Collect** — explicit (`feedback` table) + implicit (rephrase-after-answer, `PostToolUse` validation failure, HITL rejection), tagged with the same identifiers as metering.
2. **Evaluate** — periodic rollup job buckets feedback into (a) reranker tuning signal [existing, Part I §7.6], (b) a GEPA training set per agent/persona.
3. **Update** — prompt content via `mlflow.genai.optimize_prompts()` (GEPA); episodic memory via distilled insight write (not raw transcript); procedural memory via candidate skills from successful multi-tool sequences.
4. **Gated redeployment** — nothing promotes automatically. Optimized prompts pass an eval regression check; candidate skills require admin approval — both surfaced in the **Agent Observatory approval queue (§A2.6.3)**, not a silent background process.

---

## A2.11 Hooks

| Hook | Fires | Role |
|---|---|---|
| `SessionStart` | Session bootstrap | Stamp metering/tracing identifiers, load persona + language + agent version |
| `PreAgentCall` | Before any subagent/handoff | RBAC allowlist check, language directive injection |
| `PreToolUse` | Before any tool/skill call | RBAC allowlist check, rate-limit check, ACL scoping, block/deny/rewrite/escalate |
| `PostToolUse` | After tool/skill returns | Citation-grounding validation, telemetry, feedback-signal capture on failure |
| `PostAgentCall` | After subagent/handoff returns | Plan-validity logging, duplication check |
| `OnError` | Any failure | Retry/escalate/dead-letter, mirrors ingestion DLQ pattern |
| `SessionEnd` | Session close | Memory write-back (episodic), metering finalization, feedback rollup trigger |

Hook bindings are admin-configured (§A2.4); the hook contract itself is framework-independent, wrapping a LangGraph node call or a Temporal activity identically.

---

## A2.12 Access Control & Rate Limiting

- `project_memberships` (existing) gives role assignment.
- `role_permissions`: `(role, allowed_agent_ids[], allowed_persona_ids[], allowed_tool_ids[])` — **explicitly authored by the project admin as part of the Project Agent Configuration freeze workflow (§A2.5.1 step 2)**, not a separate standalone table users or backend processes populate independently.
- Enforcement is a set-membership lookup inside `PreToolUse`/`PreAgentCall` — no rule engine, no attribute evaluation.
- Upgradeable later: enforcement already lives at the hook layer, so swapping in ABAC/OPA/Cerbos is a hook-body change, not an architecture change.

Rate limiting: token-bucket per `(user, project, tenant)` scope in Redis, fed by the same tagged events that feed metering.

---

## A2.13 Metering

- Every span carries `{tenant_id, project_id, user_id, persona_id, agent_id, agent_version, session_id, feature}`, stamped at `SessionStart`, propagated through every hook.
- MLflow trace is the raw source of truth.
- Rollup job aggregates into `usage_ledger` (Postgres) — hourly for the Agent Observatory, daily as the chargeback source of truth.
- Redis counters (shared with rate limiting) give sub-second enforcement without waiting on the rollup.

---

## A2.14 Data Model Additions

Extends `config_db_scripts/001_create_schema.sql` table 18 (`agents`) and adds new tables. Sketch, not final DDL:

```
agents                     -- extend: add prompt_ref (MLflow URI), planning_strategy, memory_policy JSONB
personas                   -- id, tenant_id, project_id, name, prompt_ref, data_scope JSONB, tool_allowlist[], version
tools                      -- id, tenant_id, name, kind ('native'|'mcp'), schema JSONB, connection_info JSONB, version
skills                     -- id, tenant_id, project_id, name, spec, version, status ('candidate'|'active')
hooks                      -- id, tenant_id, hook_type, matcher_pattern, action_ref, version
role_permissions           -- role, allowed_agent_ids[], allowed_persona_ids[], allowed_tool_ids[]
project_registry_bindings  -- project_id, item_type ('agent'|'persona'|'tool'|'skill'), item_id,
                               item_version, enabled, bound_at, bound_by
project_agent_configs      -- project_id, version, status ('draft'|'active'|'deprecated'),
                               bindings_snapshot JSONB, role_permissions_snapshot JSONB,
                               activated_at, activated_by
usage_ledger                -- tenant_id, project_id, user_id, agent_id, agent_version, period,
                               tokens_in, tokens_out, tool_calls, cost
feedback                    -- (existing) extend with agent_id, agent_version, persona_id, session_id
```

`project_agent_configs` is the freeze artifact — the versioned snapshot, same pattern as `pipelines`. All tables follow the existing versioned-immutable-per-version discipline.

---

## A2.15 Post-Freeze Deferrals

- **Multi-org agent marketplace** — A2A protocol, signed Agent Cards, cross-org registry/discovery, publisher billing.
- **Sandboxing / isolation** — Firecracker microVMs, gVisor, third-party code execution isolation.
- **ABAC / policy engine** (OPA, Cerbos) — simple RBAC covers the current need; hook-layer enforcement is ready for this upgrade without an architecture change.
- **Public MCP registry reach** — internal tools registry only.

---

# APPENDIX A — GLOSSARY

**Ingestion & Admin Flow**
- **Canonical DocumentDOM** — the uniform structured document representation every pipeline must produce.
- **Virtual cluster** — a saved metadata filter expression that scopes retrieval within a project collection.
- **Layer** — one of {proposition, child, parent, raptor_summary}; all live in the same Qdrant collection.
- **Contextual chunking** — prepending 50–100 tokens of situating context to a chunk before embedding (per Anthropic's research).
- **RAPTOR** — recursive abstractive summarization producing a hierarchical index over the corpus.
- **Parent promotion** — at retrieval time, replacing child chunks with their parents to give the LLM more context.
- **Pipeline binding** — the rule `(project, datasource, doc_type) → pipeline` that determines which pipeline ingests a given document.

**Agent Runtime**
- **Skeleton vs. prompt content** — an agent's structural definition (tools, hooks, memory policy, planning strategy — version-pinned per session) vs. its behavioral prompt (system prompt, persona instructions — MLflow Prompt Registry alias, mutable without a new session).
- **Project Agent Configuration** — the versioned, freezable binding `(project) → {enabled agents, personas, tools, skills, role_permissions}`, the exact analog of pipeline binding applied to agents.
- **Freeze (v1, v2, ...)** — promoting a draft Project Agent Configuration to `active`; the only configuration users can execute against until the next promotion.
- **Agent Observatory** — the admin dashboard pairing usage stats with quality/eval metrics per registry item and per project, plus the feedback-loop approval queue.
- **CoALA memory taxonomy** — working / episodic / semantic / procedural.
- **Candidate skill/insight** — a feedback-loop-generated artifact awaiting eval-gate or admin approval before promotion to active/production status.
- **Hook** — a deterministic middleware interception point, independent of the underlying orchestration framework.

---

# APPENDIX B — RESEARCH BACKING: INGESTION & RETRIEVAL

Every architectural choice with its supporting evidence, tradeoffs, and field observations. Citations link to arxiv where available.

## B.1 Retrieval Architecture

### B.1.1 Parent-Child Hierarchical Chunking

**What we do.** Split documents into small child chunks (~300–500 tok) for precise vector matches and larger parent chunks (~1500–2500 tok) returned to the LLM for context. Embed only children; fetch parents by reference.

**Research backing.**
- The general "small-to-big" retrieval pattern is documented in production RAG literature and is a core technique in LlamaIndex's `HierarchicalNodeParser`. The motivation traces to the bias-variance tradeoff between retrieval precision (small chunks match more cleanly) and generation grounding (large chunks give the LLM more to work with).
- Empirically validated in the **Dense X Retrieval** study (Chen et al., EMNLP 2024, [arXiv:2312.06648](https://arxiv.org/abs/2312.06648)), which formalized the granularity question and showed that retrieval and generation prefer different chunk sizes.

**Pros.**
- Decouples retrieval-time precision from generation-time context.
- Smaller embedded units → higher cosine separation → fewer false neighbors.
- Parent reconstruction at query time naturally clusters multiple child hits into one parent (deduplication for free).

**Cons.**
- 2× chunk-store overhead in Postgres (parents and children both stored).
- Boundary discipline matters: poor parent boundaries (e.g., mid-section splits) degrade context quality.
- Parents-by-reference adds one Postgres roundtrip per query unless cached.

**Observations.**
- 15% overlap on children, none on parents, is the sweet spot — overlap on parents creates redundancy in the LLM context that hurts more than it helps.
- Tables, code blocks, and images should be their own indivisible chunks regardless of token count.
- The single highest-leverage tuning knob is **parent size**: too small and the LLM lacks grounding; too large and you crowd out diversity in the context window.

---

### B.1.2 RAPTOR (Recursive Abstractive Tree-Organized Retrieval)

**What we do.** Cluster child chunks (UMAP→10d→GMM-with-BIC), summarize each cluster with a grounded prompt, recursively re-cluster summaries up to 3 levels. Each summary becomes its own chunk with `raptor_level` payload.

**Research backing.**
- **Sarthi et al., ICLR 2024**, ["RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval"](https://arxiv.org/abs/2401.18059). Coupling RAPTOR retrieval with GPT-4 improved the QuALITY benchmark by 20% absolute over flat retrieval — a result that has held up in independent replications.
- Subsequent work like **SiReRAG** ([arXiv:2412.06206](https://arxiv.org/abs/2412.06206)) extends the idea with similar+related indexing and confirms the multi-level abstraction principle generalizes.

**Pros.**
- Catches thematic queries ("what does the corpus say about X overall?") that leaf-only retrieval misses.
- Soft cluster membership (GMM) lets a chunk participate in multiple themes — matches how humans actually navigate knowledge.
- Adds modest storage overhead: typically 5–15% more chunks for substantial recall gains on multi-hop and global queries.

**Cons.**
- Summarization costs at ingest (a small-LLM call per cluster, recursively). Real but cacheable.
- Hallucination risk in summaries if the prompt doesn't enforce strict grounding to source chunks.
- Beyond 3 levels, summaries become so abstract they retrieve for everything and rank for nothing.

**Observations.**
- Cluster on **contextualized child embeddings** (after B.1.3), not raw parent embeddings — the richer signal produces cleaner clusters.
- Always store `source_chunk_ids` in the summary's payload; at retrieval time you can promote source children when a summary hits, giving the LLM verifiable grounding.
- Haiku-class models are sufficient for the summary step — Opus/Sonnet adds cost without measurable quality lift on this task.

---

### B.1.3 Contextual Chunking (Anthropic's Contextual Retrieval)

**What we do.** Before embedding each child chunk, prepend 50–100 tokens of situating context generated by a small LLM, using parent + document title as input.

**Research backing.**
- **Anthropic Engineering** (Sept 2024), ["Contextual Retrieval"](https://www.anthropic.com/engineering/contextual-retrieval). Published benchmarks:
  - Contextual Embeddings alone: **35% reduction** in top-20 retrieval failure rate (5.7% → 3.7%).
  - + Contextual BM25: **49% reduction** (5.7% → 2.9%).
  - + Reranking: **67% reduction**.
- Evaluation spanned codebases, fiction, arXiv papers, and science docs — the gains are not domain-specific.

**Pros.**
- The single largest "for-free" quality lever in modern RAG. No model change, no infrastructure change — just an extra LLM call per chunk at ingest.
- Compounds with hybrid retrieval and reranking (additively, per Anthropic's data).
- Solves the "chunk-in-isolation" problem cleanly: "The threshold rose to 80%" becomes searchable as a Risk-Policy fact.

**Cons.**
- Ingest cost grows by one small-LLM call per chunk (typically Haiku-class, ~$0.0001–$0.0005/chunk depending on context window).
- Adds 50–100 tokens to the embedded text, slightly inflating embedding latency.
- Quality depends on the contextualizer prompt — sloppy prompts produce generic, low-signal context.

**Observations.**
- Cache aggressively by `(parent_chunk_id, chunk_hash)` — re-ingestion shouldn't re-contextualize unchanged chunks.
- Store the contextualized text as `embedding_text` and the raw chunk as `display_text`. Embed the former, return the latter to users.
- The Anthropic prompt template (asking the LLM to "situate this chunk within the overall document for retrieval purposes") is hard to improve on; don't over-engineer it.

---

### B.1.4 Hybrid Dense + Sparse Retrieval

**What we do.** Store dense (semantic) and sparse (lexical) vectors as named vectors on every Qdrant point. Query both at retrieval time, fuse via RRF.

**Research backing.**
- Sparse retrieval traces to **BM25** (Robertson, 1994), still a strong baseline. Modern learned-sparse: **SPLADE** (Formal et al., SIGIR 2021, [arXiv:2107.05720](https://arxiv.org/abs/2107.05720)) and SPLADEv2 ([arXiv:2109.10086](https://arxiv.org/abs/2109.10086)) — produce sparse representations with learned term expansion, achieving 9%+ nDCG@10 gains on TREC DL 2019 and SOTA on BEIR.
- The classic dense baseline is **DPR** (Karpukhin et al., EMNLP 2020, [arXiv:2004.04906](https://arxiv.org/abs/2004.04906)).
- Hybrid superiority over either alone is well-documented; Anthropic's contextual-retrieval study (above) explicitly shows BM25 + dense compounds.

**Pros.**
- Sparse catches exact-term matches (product codes, error strings, named entities, code identifiers) that dense embeddings smooth over.
- Dense catches semantic equivalents and paraphrase that sparse misses.
- Failure modes are largely independent — fusion gains are real, not redundant.

**Cons.**
- 2× index size (dense + sparse vectors per point).
- Slightly higher query latency (two searches before fusion).
- Sparse models (SPLADE) are bigger to host than BM25 — pick BM25 for cost-sensitive deployments, SPLADE when sparse quality matters.

**Observations.**
- Qdrant's native sparse-vector support means no separate BM25 service to operate.
- **BGE-M3** (B.2.1) produces both dense and sparse vectors from one model — biggest operational simplification available today.
- Don't try to weight dense vs sparse manually; RRF (B.1.5) handles fusion without hyperparameters.

---

### B.1.5 Reciprocal Rank Fusion (RRF)

**What we do.** Fuse ranked result lists from dense and sparse retrieval using `score(d) = Σ 1/(k + rank_i(d))` with `k=60`.

**Research backing.**
- **Cormack et al., SIGIR 2009**, "Reciprocal Rank Fusion outperforms Condorcet and Individual Rank Learning Methods". Original paper; demonstrated RRF beats score-normalization fusion across TREC tasks.
- The `k=60` constant emerged from TREC empirics in 2009; modern benchmarks find `k ∈ [40, 80]` performs equivalently, so most vendors default to 60.

**Pros.**
- Zero hyperparameter tuning across queries/corpora — same `k=60` works everywhere.
- Score-free: doesn't require normalizing incomparable similarity scales (cosine vs BM25 vs CLIP-similarity).
- Trivially extensible: add an L3 RAPTOR-search list, or a CLIP-image list, fuse all in one call.

**Cons.**
- Treats all source rankings as equally trustworthy — if one is much noisier than another, weighted fusion could win.
- Loses score information that downstream calibration (e.g., learning-to-rank) could use.

**Observations.**
- For 95% of production RAG, RRF is the right answer — pick something better only after measuring that fusion is your bottleneck.
- Combine with a downstream cross-encoder reranker (B.1.6) and RRF's "no score" weakness becomes a non-issue: the reranker re-scores anyway.

---

### B.1.6 Cross-Encoder Reranking

**What we do.** After hybrid retrieval returns top-50, run a cross-encoder on each (query, candidate) pair to produce a true relevance score; keep top-10.

**Research backing.**
- Cross-encoders are foundational; the architecture trades efficiency for accuracy by attending jointly to query and document.
- **ColBERT** (Khattab & Zaharia, SIGIR 2020, [arXiv:2004.12832](https://arxiv.org/abs/2004.12832)) introduced late interaction — a middle path between bi-encoder speed and cross-encoder quality.
- Modern rerankers — **BGE-reranker-v2-m3** (arXiv:2402.03216 line), Cohere rerank-3, Voyage rerank-2 — push cross-encoder design to production efficiency. BGE-reranker-v2-m3 scores 51.8 nDCG@10 on BEIR at 278M params, with bge-reranker-large adding ~2 nDCG@10 at double the latency.

**Pros.**
- Largest single quality lever after contextual chunking — Anthropic measured the +reranking step taking failure rate from 49% reduction to 67% reduction.
- Catches semantic nuance bi-encoders miss because the model sees query and chunk *together*.
- Self-hostable (BGE-reranker-v2-m3) for tight cost/latency; SaaS rerankers (Cohere) for highest quality.

**Cons.**
- O(N) inference cost per query — keep N to top-50 for sensible latency.
- GPU pod required for self-hosted rerankers at production QPS.
- Cross-encoders are typically text-only; multimodal rerank requires either separate passes per modality or a multimodal model (Cohere rerank-3 handles this).

**Observations.**
- BGE-reranker-v2-m3 is the best cost/quality/license default in 2026 — multilingual, fast, Apache-2.0.
- Rerank latency budget: ~200ms for 50 candidates on a single L4 GPU is achievable and worth the spend.
- The "should I rerank?" question has one answer in production: yes, almost always. The exceptions are sub-100ms latency budgets or vanishingly small candidate pools.

---

### B.1.7 HyDE — Hypothetical Document Embeddings (Optional)

**What we do.** For abstract or short queries, ask a small LLM to write a hypothetical answer, embed *that*, search with it. Skip for keyword queries.

**Research backing.**
- **Gao et al., ACL 2023**, ["Precise Zero-Shot Dense Retrieval without Relevance Labels"](https://arxiv.org/abs/2212.10496). HyDE significantly outperforms unsupervised dense retrievers (Contriever) and matches fine-tuned retrievers in zero-shot settings.

**Pros.**
- Bridges the "query is short, documents are long" semantic mismatch.
- Particularly strong on conceptual / how-to queries.
- Zero training required — works with any LLM + any retriever.

**Cons.**
- Adds an LLM call to every retrieval (~150–500ms even with Haiku).
- Can backfire on factual queries — a hallucinated hypothetical introduces noise vectors.
- Multi-step expansion can drift from user intent.

**Observations.**
- Gate HyDE behind a 5B-param intent classifier (or even a regex+heuristic): apply only when query length < 8 tokens and intent is conceptual/abstract.
- Cache HyDE expansions by query hash — repeated queries are common.
- Skip HyDE entirely if you already have HyDE-trained or instruction-tuned embedders (BGE-M3, Voyage-3).

---

### B.1.8 Proposition-Level Retrieval (Optional L0 Layer)

**What we do.** Extract atomic factual propositions from text as a fifth layer, embedded separately. Boost for factual lookup queries.

**Research backing.**
- **Chen et al., EMNLP 2024**, ["Dense X Retrieval: What Retrieval Granularity Should We Use?"](https://arxiv.org/abs/2312.06648). Indexing by fine-grained propositions significantly outperforms passage-level retrieval, especially on QA tasks under fixed compute budgets.

**Pros.**
- Higher precision on factual lookup ("when was X founded?", "what is the limit?").
- Atomic units survive aggressive token-budget constraints in the LLM context.

**Cons.**
- Extraction step is an extra LLM call per chunk at ingest.
- 3–10× chunk count increase — meaningful storage and embedding cost.
- Diminishing returns when combined with strong reranking + contextual chunking.

**Observations.**
- Start without propositions; add only if eval shows factual-query failures dominate.
- When enabled, weight L0 strongly for factual intent and suppress for thematic intent (see Section 7.3 layer-weighting table).

---

### B.1.9 Multimodal Retrieval — Captions vs CLIP vs ColPali

**What we do.** Default approach: VLM-generated contextualized captions become the embedded text representation; original image files stored separately and referenced via metadata. Optional second vector for CLIP-based visual similarity.

**Research backing.**
- **CLIP** (Radford et al., ICML 2021, [arXiv:2103.00020](https://arxiv.org/abs/2103.00020)) — foundational image-text joint embedding via contrastive learning on 400M web pairs.
- **ColPali** (Faysse et al., 2024, [arXiv:2407.01449](https://arxiv.org/abs/2407.01449)) — end-to-end VLM-based document retrieval using late-interaction over patch embeddings; outperforms OCR-then-retrieve on visually rich docs.
- Practitioner-published benchmarks show multimodal RAG improves retrieval accuracy 25–40% on visually rich corpora vs text-only.

**Pros.**
- Caption-text approach plugs into existing text-retrieval stack with zero architectural change.
- VLM captioning is cacheable by image SHA-256 — same logo across 10K docs is captioned once.
- Combined caption + OCR text covers both diagrammatic and textual content in images.

**Cons.**
- Caption quality is the ceiling for retrieval quality; cheap VLMs produce flat, generic captions.
- Pure CLIP embeddings retrieve by visual similarity, not semantic meaning — best for "find similar diagrams" queries, not document QA.
- ColPali requires storing 1024 patch embeddings per page (heavy storage); justifies only if visually rich docs are the bulk of the corpus.

**Observations.**
- **Default path:** contextualized captions + OCR text embedded via the same text embedder = single index, simple query path, strong baseline.
- **Add CLIP** (named vector `image_clip`) only if users will issue visual queries ("find diagrams that look like X"). Adds ~1KB/image at storage cost.
- **Consider ColPali** only for document-heavy corpora (legal, technical) where OCR loses structure (tables, charts, layout). It's a different architecture, not an incremental add.
- VLM choice: Claude Haiku Vision or Qwen2-VL-7B for cost; GPT-4o-mini or Claude Sonnet Vision for highest caption quality.

---

## B.2 Embedding & Model Choices

### B.2.1 BGE-M3 (or Voyage-3) as Primary Embedder

**What we do.** One embedder, one model, locked per tenant. Default recommendation: **BGE-M3** (self-hosted) for cost-sensitive deployments, **Voyage-3-large** for SaaS-friendly setups.

**Research backing.**
- **Chen et al., ACL 2024 Findings**, ["M3-Embedding: Multi-Linguality, Multi-Functionality, Multi-Granularity Text Embeddings"](https://arxiv.org/abs/2402.03216). BGE-M3 supports 100+ languages, dense + multi-vector + sparse retrieval in a single model, and 8K-token contexts. SOTA on multilingual and long-document benchmarks.

**Pros.**
- BGE-M3 produces dense **and** sparse vectors from one model — eliminates the second embedder service.
- Multilingual coverage matters for enterprise (the user-flow language selector pairs naturally with this).
- 8K context handles parent chunks without truncation.
- Apache-2.0 license, self-hostable on commodity GPUs.

**Cons.**
- Self-hosting still requires GPU capacity planning at scale.
- Voyage/Cohere SaaS embedders may edge BGE-M3 on English-only benchmarks by 1–3 nDCG points.
- Embedding model changes are migration-grade events — pick carefully.

**Observations.**
- Lock the model per **tenant**, not per project. Cross-project retrieval within a tenant becomes possible only when vectors are comparable.
- Model migration playbook: parallel collection with new embeddings → dual-read → cutover. Plan it before you need it.

---

### B.2.2 Why Not Multiple Embedders by Doc Type

**What we do.** One embedder for all doc types in the same tenant.

**Rationale.** Mixing embedders within a collection breaks vector-space comparability: cosine distance between a Voyage vector and a BGE vector is meaningless. Convergence to a single knowledge base requires a single embedding space.

**Cons accepted.** Slight quality compromise on niche domains (e.g., code-specific embedders like CodeRankEmbed would win on code search) in exchange for unified retrieval.

**Observation.** For code-heavy projects, you can run a parallel code-only collection with a specialized embedder, and route by `doc_type=code` at the dispatcher. Don't put it in the unified collection.

---

## B.3 Storage & Indexing

### B.3.1 Single Qdrant Collection Per Project (with Payload Indexes)

**What we do.** One collection per project; tenant_id + project_id + ACL filters applied server-side via payload indexes; payload indexes declared at collection creation.

**Research backing.**
- **Qdrant official guidance** ([Multitenancy docs](https://qdrant.tech/documentation/manage-data/multitenancy/), [Multitenancy article](https://qdrant.tech/articles/multitenancy/)): "In most cases, a single collection per embedding model with payload-based partitioning for different tenants is recommended." Creating thousands of collections causes resource overhead, performance degradation, and cluster instability.

**Pros.**
- One query covers all of a project's knowledge.
- Virtual clusters (named metadata filters) require this — they cannot span collections.
- Reranker sees text + image + table results in one ranking pass.
- Scaling: Qdrant handles ~50M points per collection comfortably.

**Cons.**
- Beyond ~50M points, may require sub-sharding via Qdrant's custom shard keys.
- Forgetting to declare a payload index on a filter field collapses to a scan — operational discipline required.

**Observations.**
- Use Qdrant's **tenant indexing** (`is_tenant: true`) on the `project_id` field. This co-locates per-project data on disk and dramatically reduces seeks.
- HNSW config: `payload_m=16`, `m=0` for the global index — biases the graph toward in-tenant edges instead of cross-tenant.
- Declare *every* payload index at creation time. Adding one later requires a full reindex of that field.

---

### B.3.2 Virtual Clusters via Named Metadata Filters

**What we do.** Save filter expressions in Postgres `virtual_clusters`; apply at query time as `must` clauses in Qdrant.

**Research backing.**
- This is essentially the "saved-filter" pattern from enterprise search (SOLR, Elasticsearch faceted search), applied to vector retrieval. Qdrant's payload-filtering performance with proper indexes makes it constant-time.

**Pros.**
- No data duplication — clusters are queries, not collections.
- Trivially composable: cluster ∩ cluster ∩ ACL filter, all in one Qdrant call.
- Dynamic clusters (`{{user.groups}}` substitution) handle ACL elegantly.

**Cons.**
- Filter performance degrades sharply if any field used in the filter lacks an index.
- Unbounded user-defined metadata fields can explode Qdrant memory footprint.

**Observations.**
- Cap custom metadata fields per project at 32 to bound payload-index memory.
- Pre-filter before vector search, never post-filter — Qdrant's filter-then-search is far cheaper than search-then-filter on selective predicates.

---

## B.4 Pipeline & Workflow

### B.4.1 Temporal for Durable Orchestration

**What we do.** Each document ingestion is a Temporal workflow; each stage is a Temporal activity on its own task queue.

**Research backing & precedent.**
- Temporal grew out of Uber's Cadence project; the durable-execution model is now industry standard for long-running, failure-prone workflows (Snap, Netflix, DoorDash, Coinbase all run Temporal at scale).
- Practitioner comparisons consistently distinguish Temporal (durable execution, application workflows) from Airflow (DAG scheduling, batch ETL).

**Pros.**
- Workers can crash mid-stage; the workflow resumes exactly where it left off — no custom retry/state-machine code.
- Independent task queues per worker = true horizontal scaling per stage.
- First-class retries, heartbeats, signals, child workflows.
- Workflow history doubles as audit trail.

**Cons.**
- Operational complexity: Temporal cluster + Postgres/Cassandra persistence + workers.
- Learning curve for the workflow-vs-activity split.
- Overkill for sub-second jobs (use a queue + worker pattern instead).

**Observations.**
- Set `workflow_id = "{tenant}:{doc}:v{version}:{pipeline_version}"` for idempotent starts — Temporal will reject duplicates, which makes the outbox dispatcher trivially safe.
- Run Temporal on its own Postgres (separate from the config DB) to isolate workflow history growth.
- Airflow is the wrong tool here despite being more familiar — its DAG-of-tasks model assumes scheduled batch, not event-triggered long-running document journeys.

---

### B.4.2 YAML-Defined Pipelines

**What we do.** Pipeline = YAML spec stored versioned in Postgres; declarative DAG of named stages; no embedded code.

**Rationale.** Configuration-as-data wins over code for: tenant self-service, dry-runs, diffing versions in UI, blast-radius limits.

**Pros.**
- Tenant/project admins can author pipelines without committing code.
- Pipeline diffs render cleanly in the admin UI.
- Easy to validate, gate, and approve before activation.

**Cons.**
- Limits expressiveness vs Python-defined pipelines.
- Adding a new stage type requires a worker deployment, not a YAML change.

**Observations.**
- Resist the temptation to embed Python (or any sandboxed code) in YAML for v1. Sandboxing is a security project of its own, and 90% of use cases need only the declarative form.
- Validate YAML with JSON Schema on save; reject invalid specs before they ever reach the dispatcher.

---

### B.4.3 The Canonical DocumentDOM Contract

**What we do.** Every extractor (PDF, DOCX, HTML, SharePoint, SQL, etc.) emits the same structured representation; chunking and downstream stages are pipeline-agnostic.

**Rationale.** This is the architectural keystone — without it, "single knowledge base" silently fragments into per-source islands as each pipeline grows its own quirks.

**Pros.**
- One chunker, one embedder, one retriever for all sources.
- New connectors are isolated work — they only need to produce the DOM, downstream is free.
- Schema-validatable boundary catches drift before it ships.

**Cons.**
- Forces awkwardness on non-document sources (SQL rows, API responses) — they must synthesize sections/blocks.
- The schema becomes a versioning concern: changes break all extractors.

**Observations.**
- Publish the DOM as a JSON Schema; CI-check every extractor against it.
- When the schema must change, version it (`v1`, `v2`) and run extractors against pinned versions — gradual migration rather than flag day.

---

## B.5 Event-Driven Architecture

### B.5.1 Transactional Outbox Pattern

**What we do.** Pipeline-triggering events are written to a Postgres `events` table in the same transaction as the document insert. A separate dispatcher polls and publishes to Redis Streams.

**Research backing.**
- **Chris Richardson, "Microservices Patterns"** (2018) — canonical formalization. [microservices.io: Transactional Outbox](https://microservices.io/patterns/data/transactional-outbox.html).
- Used at Netflix, Uber, and most large-scale event-driven systems to solve the "dual write" problem.

**Pros.**
- Guarantees event publication consistency with state change — no lost events on crash between DB commit and broker publish.
- Replayable: re-publishing the outbox is the disaster-recovery primitive.
- Decouples application code from broker availability — writes succeed even when Redis is down.

**Cons.**
- Adds a polling dispatcher service (or CDC consumer).
- Adds end-to-end latency (polling interval, typically 100ms–1s).
- Outbox table grows; needs a cleanup policy.

**Observations.**
- CDC-based dispatchers (Debezium) are lower latency but heavier ops. Polling is the right starting point.
- Purge published events after 7–30 days; keep an audit aggregate for longer.

---

### B.5.2 Redis Streams (Choice Over Kafka, for Now)

**What we do.** Redis Streams as the event transport between outbox dispatcher and Temporal trigger.

**Research backing & comparisons.**
- AWS, OneUptime, and multiple practitioner comparisons consistently characterize the tradeoff as: **Kafka** for high-throughput, durable, persistent-by-disk event streaming; **Redis Streams** for high-performance, in-memory streams with optional persistence and bounded retention.

**Pros.**
- One fewer system to operate vs Kafka.
- Native consumer groups, ack/pending/claim semantics — not Pub/Sub which drops messages.
- Microsecond-class latency.

**Cons.**
- Memory-bound retention — not a long-term log.
- Durability depends on AOF + replication setup; not as ironclad as Kafka's disk-first model by default.
- No per-key partitioning by default — cross-consumer ordering is per-stream only.

**Observations.**
- Configure with `appendonly yes`, `appendfsync everysec`, Sentinel or Cluster for failover. Default single-node Redis will lose events on crash.
- Use `MAXLEN ~ 1000000` on `XADD` to cap memory.
- The Postgres outbox is your *real* event store — Redis Streams is the fast delivery channel. If a Redis incident loses events, you re-drive from the outbox. This is what makes the Redis-Streams-over-Kafka tradeoff safe.
- Migration to Kafka later is a dispatcher change, not an application change.

---

## B.6 Decision Confidence Summary (Ingestion)

| Decision | Confidence | Primary citation | Reversibility |
|---|---|---|---|
| Parent-child chunking | High | LlamaIndex production, Dense X | Easy |
| RAPTOR | High | [Sarthi 2024 ICLR](https://arxiv.org/abs/2401.18059) | Easy (additive) |
| Contextual chunking | Very High | [Anthropic 2024](https://www.anthropic.com/engineering/contextual-retrieval) | Trivial |
| Hybrid dense+sparse | Very High | SPLADE, BGE-M3 | Easy |
| RRF fusion | Very High | [Cormack 2009](https://dl.acm.org/doi/10.1145/1571941.1572114) | Trivial |
| Cross-encoder rerank | Very High | ColBERT, BGE-reranker-v2-m3 | Easy |
| HyDE | Medium | [Gao 2022](https://arxiv.org/abs/2212.10496) | Optional / easy |
| Proposition retrieval | Medium | [Chen 2024](https://arxiv.org/abs/2312.06648) | Optional |
| Captions + CLIP multimodal | High | [CLIP 2021](https://arxiv.org/abs/2103.00020), ColPali | Add-only |
| BGE-M3 / Voyage-3 | High | [BGE-M3 2024](https://arxiv.org/abs/2402.03216) | Hard (migration) |
| Qdrant single-collection-per-project | High | Qdrant official guidance | Hard (re-index) |
| Virtual clusters via metadata | High | IR practice + Qdrant filters | Easy |
| Temporal | High | Industry consensus | Hard (rewrite) |
| YAML pipelines | High | Configuration-as-data norm | Easy |
| Canonical DocumentDOM | Very High | Architectural keystone | Hard (changes propagate) |
| Outbox pattern | Very High | [Richardson 2018](https://microservices.io/patterns/data/transactional-outbox.html) | Trivial |
| Redis Streams (vs Kafka) | Medium | Practitioner comparisons | Easy (swap dispatcher) |

"Hard" reversibility means a real migration project; "Easy" means a deploy with no data movement; "Trivial" means a config or code change.

---

## B.7 Sources (Ingestion)

**Foundational papers**
- [CLIP — Radford et al. 2021](https://arxiv.org/abs/2103.00020)
- [DPR — Karpukhin et al. 2020](https://arxiv.org/abs/2004.04906)
- [ColBERT — Khattab & Zaharia 2020](https://arxiv.org/abs/2004.12832)
- [SPLADE — Formal et al. 2021](https://arxiv.org/abs/2107.05720)
- [SPLADEv2 — Formal et al. 2021](https://arxiv.org/abs/2109.10086)

**Modern RAG techniques**
- [RAPTOR — Sarthi et al. 2024](https://arxiv.org/abs/2401.18059)
- [HyDE — Gao et al. 2022](https://arxiv.org/abs/2212.10496)
- [Dense X Retrieval — Chen et al. 2024](https://arxiv.org/abs/2312.06648)
- [BGE-M3 — Chen et al. 2024](https://arxiv.org/abs/2402.03216)
- [ColPali — Faysse et al. 2024](https://arxiv.org/abs/2407.01449)
- [Anthropic Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval)

**Architectural patterns**
- [Transactional Outbox — microservices.io](https://microservices.io/patterns/data/transactional-outbox.html)
- [Qdrant Multitenancy](https://qdrant.tech/documentation/manage-data/multitenancy/)
- [Qdrant Multitenancy Article](https://qdrant.tech/articles/multitenancy/)
- Cormack et al. 2009, "Reciprocal Rank Fusion outperforms Condorcet and Individual Rank Learning Methods" (SIGIR)

---

# APPENDIX D — RESEARCH BACKING: AGENT RUNTIME

### D.1 Reasoning & Planning Patterns

| Pattern | Citation | Finding |
|---|---|---|
| ReAct | Yao et al., 2022, [arXiv:2210.03629](https://arxiv.org/abs/2210.03629) | Interleaved reason+act reduces hallucination vs. pure CoT; +34%/+10% success on ALFWorld/WebShop |
| ReWOO | Xu et al., 2023, [arXiv:2305.18323](https://arxiv.org/abs/2305.18323) | Decoupled planning: 5x token efficiency, +4% accuracy on HotpotQA, robust to tool failure |
| LLM Compiler | Kim et al., 2023, [arXiv:2312.04511](https://arxiv.org/abs/2312.04511), ICML 2024 | Parallel DAG execution: 3.7x latency, 6.7x cost, ~9% accuracy improvement over ReAct |
| Reflexion | Shinn et al., 2023, [arXiv:2303.11366](https://arxiv.org/abs/2303.11366), NeurIPS 2023 | Verbal self-reflection stored in episodic buffer improves subsequent trials |
| Tree of Thoughts | Yao et al., 2023, [arXiv:2305.10601](https://arxiv.org/abs/2305.10601), NeurIPS 2023 | Proposer+evaluator branch/prune search; best for genuine multi-path problems |
| Plan-and-Solve | Wang et al., 2023, [arXiv:2305.04091](https://arxiv.org/abs/2305.04091), ACL 2023 | "Understand → plan → execute" beats zero-shot CoT on math/reasoning |

### D.2 Multi-Agent Topology

- AutoGen — Wu et al., 2023, [arXiv:2308.08155](https://arxiv.org/abs/2308.08155) — composable conversation patterns, grounding for supervisor message-passing.
- MetaGPT — SOP-encoded roles reduce hallucination in complex multi-step tasks.
- Multi-Agent Debate — Du et al., 2023; Mixture-of-Agents — Wang et al., 2024, [arXiv:2406.04692](https://arxiv.org/abs/2406.04692) — reserved for bounded verification steps, not default topology.
- Survey — Guo et al., 2024, [arXiv:2402.01680](https://arxiv.org/abs/2402.01680).

### D.3 Tool Use

- Toolformer — Schick et al., 2023, [arXiv:2302.04761](https://arxiv.org/abs/2302.04761) — self-supervised tool-call decision-making.
- Gorilla — Patil et al., 2023, [arXiv:2305.15334](https://arxiv.org/abs/2305.15334).
- ToolLLM/ToolBench — Qin et al., 2023, [arXiv:2307.16789](https://arxiv.org/abs/2307.16789) — retrieval-augmented tool selection outperforms full-catalog context stuffing at scale.

### D.4 Agentic Memory

- CoALA — Sumers et al., 2023, [arXiv:2309.02427](https://arxiv.org/abs/2309.02427) — working/episodic/semantic/procedural taxonomy.
- MemGPT — Packer et al., 2023, [arXiv:2310.08560](https://arxiv.org/abs/2310.08560) — OS-inspired tiered memory.
- Generative Agents — Park et al., 2023, [arXiv:2304.03442](https://arxiv.org/abs/2304.03442) — recency + importance + relevance-weighted retrieval.
- memU (NevaMind-AI) — Resource→Memory Item→MemoryCategory layered architecture; 92.09% avg accuracy on the LOCOMO benchmark across reasoning tasks in the maintainers' published results; supports RAG-based and LLM-based (direct file read) retrieval. Apache-2.0. **Default memory backend per ADR-002 (2026-07-05).**
- Mem0 — Chhikara et al., 2025, [arXiv:2504.19413](https://arxiv.org/abs/2504.19413) — benchmarked on LOCOMO; graph-variant available. Retained as a pluggable alternative (decision #9).
- A-MEM — Xu et al., 2025, [arXiv:2502.12110](https://arxiv.org/abs/2502.12110) — Zettelkasten-style dynamic note organization.
- MemEngine — Zhang et al., 2025 — unified memory-slot paradigm, pluggable storage/retrieval.

### D.5 Feedback Loop / Self-Improvement

- ExpeL — Zhao et al., 2023, [arXiv:2308.10144](https://arxiv.org/abs/2308.10144), AAAI 2024 — distilled insights, not raw transcripts.
- Voyager — Wang et al., 2023, [arXiv:2305.16291](https://arxiv.org/abs/2305.16291) — ever-growing skill library via iterative environment-feedback prompting.
- Self-Refine — Madaan et al., 2023, [arXiv:2303.17651](https://arxiv.org/abs/2303.17651), NeurIPS 2023.
- Self-Evolving Agents Survey — Fang et al., 2025, [arXiv:2508.07407](https://arxiv.org/abs/2508.07407) — signal→evaluation→update→redeploy framework.
- MLflow GEPA prompt optimization — `mlflow.genai.optimize_prompts()` ([MLflow docs](https://mlflow.org/docs/latest/genai/prompt-registry/optimize-prompts/)).

### D.6 Multilingual Generation

- QTT-RAG — Moon et al., 2025, [arXiv:2510.23070](https://arxiv.org/abs/2510.23070), ACL MRL 2025 — KN_Valya avoids the document-translation failure mode entirely by generating directly in the target language from English context.

### D.7 Persona

- Character-LLM — Shao et al., 2023, [arXiv:2310.10158](https://arxiv.org/abs/2310.10158), EMNLP 2023 — profile/experience-conditioning sufficient, no fine-tuning needed.
- RoleLLM — ACL 2024 Findings; PersonaGym — [arXiv:2407.18416](https://arxiv.org/abs/2407.18418) — persona-consistency evaluation methodology.

### D.8 Evaluation

- RAGAS — Es et al., 2023, [arXiv:2309.15217](https://arxiv.org/abs/2309.15217).
- AgentBench — Liu et al., 2023, [arXiv:2308.03688](https://arxiv.org/abs/2308.03688).
- τ-bench — Yao et al., 2024, [arXiv:2406.12045](https://arxiv.org/abs/2406.12045) — tool-agent-user interaction scored by end system-state correctness.

### D.9 Orchestration & Durable Execution

- LangGraph vs. Google ADK — production comparisons, 2026 — explicit state graph vs. code-driven workflow engine; LangGraph chosen for conditional-edge flexibility and lighter dependency footprint given non-GCP stack.
- LangGraph + Postgres checkpoint bloat at scale — documented write-amplification failure mode; mitigated by reference-only state, consistent with Part I §11 principle 1.
- Temporal for durable AI agent execution — deterministic workflows coordinating non-deterministic activities; industry adoption (OpenAI, Replit, Lovable, ADP) as of 2026.

### D.10 RBAC

- Sandhu, Coyne, Feinstein & Youman, "Role-Based Access Control Models," *IEEE Computer* 29(2), 1996 — foundational RBAC model, basis for §A2.12.

### D.11 MLflow / Observability

- MLflow 3.10 GenAI docs — [mlflow.org/docs/latest/genai](https://mlflow.org/docs/latest/genai/) — Tracing (OTel-native, GenAI semantic conventions), Evaluation (LLM-as-judge), Prompt Registry (alias-based lifecycle management), AI Gateway.
- MLflow Prompt Registry lifecycle via aliases — [mlflow.org/docs/latest/genai/prompt-registry/manage-prompt-lifecycles-with-aliases](https://mlflow.org/docs/latest/genai/prompt-registry/manage-prompt-lifecycles-with-aliases/) — changes take effect immediately by loading prompts at runtime from the registry.

### D.12 Admin Governance & Catalog Patterns

- Google Cloud Agent Platform — Agent Identity, **Agent Registry**, and **Agent Gateway** as the enterprise pattern for centralized, trackable agent governance across internally-built and partner-sourced agents (2026 product architecture).
- Microsoft's governed agent stack — agents follow a **draft/live lifecycle**: builders iterate privately, publish when ready, published agents automatically inherit governance policy (version-controlled, auditable before deployment) — direct precedent for the draft → dry-run → promote (freeze) workflow in §A2.5.
- Enterprise agent observability convention (Braintrust, Galileo, Groundcover, 2026 buyer guides) — dashboards should pair aggregate stats with per-agent quality/eval scores in one place — basis for combining §A2.6.1 and §A2.6.2 into a single Observatory screen.

---

*Frozen 2026-07-02, both parts. This document supersedes `ARCHITECTURE.md` and `agent_runtime_architecture.md` as the single reference; those two files remain on disk as the pre-merge historical record. Post-freeze changes to any section require an ADR and a version bump on this document.*
