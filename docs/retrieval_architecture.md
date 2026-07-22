# Retrieval Architecture — Converged Project Knowledge Base

> Goal: regardless of source (PDF, DOCX, HTML, SharePoint, Confluence, SQL row, NoSQL doc), everything ingested for a project ends up in **one Qdrant collection** that returns high-quality context at any time, across any granularity the question demands.

---

## 1. One Collection per Project

```
qdrant_collection = "proj_{project_id}"
```

- All pipelines, regardless of doc type, converge here. The pipeline's job is to *normalize* every input into the same canonical chunk schema.
- Tenant isolation happens at the **API/auth layer** (a user can only target collections their project ACL permits), not via separate collections per tenant. Project isolation is physical (separate collection).
- "Virtual clusters" inside the collection are achieved with **payload indexes** on metadata — see §5. You can carve the same collection into "only SharePoint PDFs in English from Q1" without creating new collections.

**Why not one collection per tenant?** Cross-project search inside one tenant is rare; cross-tenant search is forbidden. Collection-per-project gives you a clean blast radius for reindexes and per-project tuning (HNSW params, quantization) without affecting siblings.

---

## 2. The Four-Level Hierarchy

Every chunk row in Postgres carries a `kind` and a `level`. Only some levels get embedded; all of them are reachable from a vector hit via parent/child pointers.

| Kind             | Level | Token target | Embedded? | Purpose                                      |
|------------------|-------|--------------|-----------|----------------------------------------------|
| `child`          | 0     | ~400         | yes       | High-precision vector match                  |
| `parent`         | 0     | ~2000        | optional  | LLM-facing context block                     |
| `raptor_summary` | 1     | ~600         | yes       | Cluster of parents — section-level meaning   |
| `raptor_summary` | 2     | ~600         | yes       | Cluster of L1 summaries — document-level     |
| `raptor_summary` | 3     | ~600         | yes       | Cluster of L2 summaries — corpus-level theme |

A query embedding searches across **all embedded levels at once**. The retriever then uses `metadata.level` either to filter ("this query is narrow, only level 0") or to **rerank with level-aware weighting** ("this query is broad, boost levels 2-3").

---

## 3. Stage-by-Stage Pipeline (Per-DocType Pipelines, Shared Output)

```
[connector-specific extract]
        │
        ▼
[normalize -> canonical_doc_json]   ◄── different per doc type
        │
        ▼
[enrich: language, topics, entities, sections]
        │
        ▼
[parent-child chunker]              ◄── same for everyone from here down
        │
        ▼
[contextual header injection]
        │
        ▼
[RAPTOR (3 levels, GMM clustering)]
        │
        ▼
[dense embed + sparse vector (BM25/SPLADE)]
        │
        ▼
[qdrant upsert with rich payload]
```

The pipeline DAG up to "canonical_doc_json" varies by doc type (PDF needs OCR + layout; SQL row needs row→sentence; HTML needs boilerplate strip). From the chunker onward, **everything is identical**. This is what gives you the "one knowledge base" property — the stages that affect retrieval quality are shared.

### 3a. Parent-Child Chunking — concrete rules

- **Parent**: 2000 tokens, 200-token overlap. Aligns to section boundaries when possible (don't split mid-section if you can avoid it). Tracks `section_path` ("3.2 Methods > Sampling").
- **Child**: 400 tokens, 50-token overlap. **Each child inherits its parent's `section_path` and a 1-sentence "contextual header"** prepended to the embedded text. This header — "From the Q4 2025 Acme Financial Report, section 'Liquidity Risk' — " — is the single highest-ROI retrieval-quality move per Anthropic's contextual retrieval research. Generate it once with a cheap model.
- Both stored; **only children are dense-embedded by default**; parents are returned to the LLM via `parent_chunk_id` pointer when a child is hit.

### 3b. RAPTOR — concrete rules

- Cluster parent chunks (level 0) with GMM over their embeddings; soft assignments allow a chunk to belong to multiple clusters.
- Summarize each cluster with a cheap LLM (Haiku-class) into ~600 tokens.
- Repeat 2 more times. Stop when a level has ≤5 nodes (you've hit "document theme" territory).
- Every summary gets the same contextual header treatment and is embedded.
- Store the cluster membership as `metadata.cluster_members: [chunk_id, ...]` so you can reconstruct provenance.

### 3c. Hybrid Vectors

Qdrant supports **multiple vectors per point**. Store two on every embedded chunk:

- `dense`: 1024-dim from a strong embedder (Voyage-3, BGE-large, OpenAI text-embedding-3-large).
- `sparse`: SPLADE or BM25 sparse vector — catches exact-match terms (model numbers, names, code identifiers) that dense embeddings smear out.

Retrieve with **RRF (Reciprocal Rank Fusion)** over the two result lists. This single change typically lifts recall@10 by 8-15 points on enterprise corpora.

---

## 4. Retrieval Flow

```
query
  │
  ▼
[query analyzer] ──► narrow vs broad? language? entities? time scope?
  │
  ▼
[hybrid search in qdrant: dense + sparse, RRF, top_k=50]
  │   ── payload filters from query analyzer (tenant ACL, language, time, ...)
  │   ── level filter or weighting from query type
  ▼
[expand children → parents]  (dedupe parents)
  │
  ▼
[cross-encoder rerank top_k=50 → top_n=10]   (BGE-reranker or Cohere rerank)
  │
  ▼
[MMR diversity pass]  ── prevents 10 chunks from same section
  │
  ▼
[context packer]  ── parent chunks + relevant RAPTOR summaries, token-budgeted
  │
  ▼
LLM
```

**Why parents instead of children at the LLM?** Children are optimized for recall; parents preserve enough surrounding context that the LLM doesn't need to re-stitch fragments. The child is the *hook*; the parent is the *answer*.

**When to inject RAPTOR summaries:** if the top-k child hits cluster heavily within one or two parents (the query is narrow), skip summaries. If they spread across many parents and documents (the query is thematic), prepend the matching level-1 or level-2 summary so the LLM sees the forest before the trees.

---

## 5. Metadata Schema — The Heart of "Virtual Clusters"

Every Qdrant point carries this payload. The fields prefixed with **★** get payload indexes for fast filtering:

```json
{
  "★ tenant_id":          "uuid",
  "★ project_id":         "uuid",
  "★ document_id":        "uuid",
  "document_version":     4,
  "chunk_id":             "uuid",
  "parent_chunk_id":      "uuid | null",
  "★ kind":               "child | parent | raptor_summary",
  "★ level":              0,
  "★ doc_type":           "pdf | docx | html | sql_row | confluence | ...",
  "★ datasource_id":      "uuid",
  "★ datasource_type":    "sharepoint | confluence | sql | ...",
  "★ language":           "en",
  "★ tags":               ["finance", "q4-2025"],
  "★ classification":     "public | internal | confidential",
  "★ topic":              "liquidity_risk",
  "★ created_at":         1735689600,
  "★ effective_date":     1735689600,
  "source_uri":           "sp://...",
  "title":                "Q4 Financial Report",
  "section_path":         "3.2 Methods > Sampling",
  "page_number":          12,
  "content_hash":         "sha256...",
  "pipeline_id":          "uuid",
  "pipeline_version":     7,
  "embedding_model":      "voyage-3",
  "cluster_members":      ["chunk_id", "..."]
}
```

**Virtual clusters become a filter expression.** Examples:

```python
# "All SharePoint PDFs in English from Q1 2026, internal classification"
qdrant.search(
    collection_name=f"proj_{project_id}",
    query_vector=...,
    query_filter=Filter(must=[
        FieldCondition(key="datasource_type", match=MatchValue(value="sharepoint")),
        FieldCondition(key="doc_type",        match=MatchValue(value="pdf")),
        FieldCondition(key="language",        match=MatchValue(value="en")),
        FieldCondition(key="classification",  match=MatchValue(value="internal")),
        FieldCondition(key="effective_date",  range=Range(gte=Q1_START, lt=Q1_END)),
    ])
)
```

This is the **single most important reason** to put everything in one collection with rich metadata: the user (or an agent) can dynamically scope retrieval without your code knowing the carving in advance.

`pipeline_version` enables **zero-downtime reindex**: upsert under v8, delete points where `pipeline_version < 8`.

---

## 6. Storage Layout (MinIO — kept, simplified)

You said "forget MinIO" — meaning don't let storage choice distract from retrieval quality. The pragmatic answer: still use it, but with one bucket and a flat layout, not the four-bucket scheme. Bytes have to live somewhere reproducible.

```
s3://valya/{tenant}/{project}/{doc_id}/v{version}/raw.<ext>
s3://valya/{tenant}/{project}/{doc_id}/v{version}/canonical.json
s3://valya/{tenant}/{project}/{doc_id}/v{version}/chunks/{chunk_id}.txt
```

The chunk text is in MinIO (cheap, append-only) and the Qdrant payload only carries `text_uri` + `content_hash`. Putting full chunk text in Qdrant payload works at small scale but balloons memory and slows filter queries — keep payload to metadata only.

---

## 7. Quality Levers You Can Pull Without Rebuilding

These are knobs the admin UI should expose per-project, all live without reingest:

| Lever                    | Effect                                                            |
|--------------------------|-------------------------------------------------------------------|
| Reranker on/off          | +5-10 nDCG; +200ms latency                                        |
| RRF α (dense vs sparse)  | Tune for code-heavy vs prose corpora                              |
| Level weighting          | Broad-question quality without manual query classification        |
| MMR λ                    | Diversity vs relevance trade                                      |
| top_k pre-rerank         | Recall floor                                                      |
| Context budget           | Cost vs answer completeness                                       |

Reingest is required for: changing the chunker, embedding model, or RAPTOR depth.

---

## 8. What Changes in the DDL

The chunks table from `001_create_schema.sql` already covers this. One refinement: rename/repurpose the `metadata` column expectations to match the schema above, and add **payload indexes in Qdrant** as part of the project provisioning step (a startup hook on first write to a new `proj_*` collection).

```python
# project provisioning (runs once per project)
qdrant.create_collection(
    collection_name=f"proj_{project_id}",
    vectors_config={"dense": VectorParams(size=1024, distance=Distance.COSINE)},
    sparse_vectors_config={"sparse": SparseVectorParams()},
)
for field in ["tenant_id","project_id","document_id","kind","level",
              "doc_type","datasource_id","datasource_type","language",
              "tags","classification","topic","created_at","effective_date"]:
    qdrant.create_payload_index(f"proj_{project_id}", field_name=field, field_schema=...)
```

---

## 9. The "Quality at Any Point in Time" Property

The combination that delivers it:

1. **Hybrid dense+sparse** — recall on both meaning and exact terms.
2. **Parent-child** — precise hooks, complete context.
3. **RAPTOR** — answers thematic questions without manual summarization at query time.
4. **Contextual headers** — every chunk knows where it came from before the embedding model sees it.
5. **Rich metadata + payload indexes** — virtual clusters on demand, no reindex.
6. **Reranking + MMR** — quality and diversity at the top.
7. **Versioned points** — reindex without downtime when the recipe improves.

Skipping any one of these meaningfully degrades the others.
