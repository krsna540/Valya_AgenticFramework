# config_db_scripts

Postgres DDL for the KN_Valya configuration database. Apply in numeric order.

| File | Purpose |
|---|---|
| `001_create_schema.sql` | Extensions, ENUMs, all tables, FKs, triggers, views. |
| `002_seed_reference_data.sql` | System tenant, bootstrap admin, default lifecycle policies. Idempotent. |
| `003_indexes_and_perf.sql` | Secondary indexes for admin UI / observatory queries. |
| `004_auth_and_rbac.sql` | Password credentials, SSO providers, permissions/roles/role_permissions/user_roles, refresh tokens, login audit, seed permissions + built-in roles. |
| `005_alter_chunks_metadata.sql` | Adds converged-KB filter columns to `chunks` (tenant_id, project_id, doc_type, language, tags, ...). |
| `006_virtual_clusters.sql` | `virtual_clusters` table — added in Milestone 1; referenced by Part I decision #14 and the project-bootstrap step (§5.2) but missing from 001. |
| `007_fix_tenant_admin_permission_grant.sql` | Fixes a tautological `WHERE` clause in 004's tenant_admin seed grant (was granting `tenant.admin` despite the comment saying it shouldn't). |
| `008_seed_bootstrap_admin_role.sql` | Links the bootstrap super_admin seeded in 002 to the `super_admin` role from 004 (missed when 004 was written after 002). |
| `009_chunk_contextualization_cache.sql` | `chunk_contextualizations` table — Milestone 4's contextualization cache, keyed by `(document_id, parent_content_hash, child_content_hash)` so re-ingestion doesn't re-pay the LLM cost for unchanged content (see the file's own header comment for why this key differs from the architecture doc's literal `(parent_chunk_id, chunk_hash)` wording). |
| `010_multimodal.sql` | Milestone 6: `chunks.modality`/`image_sha256`/`minio_image_uri`/`thumbnail_uri` columns, plus `image_captions` — a captioning cache keyed by `image_sha256` alone (images are already content-addressed, unlike text chunks). |

## Apply

Apply every `NNN_*.sql` file in order — `docker/scripts/apply-schema.sh` does this automatically (globs and sorts `config_db_scripts/[0-9][0-9][0-9]_*.sql`), or by hand:

```bash
for f in 001_create_schema.sql 002_seed_reference_data.sql 003_indexes_and_perf.sql \
         004_auth_and_rbac.sql 005_alter_chunks_metadata.sql 006_virtual_clusters.sql \
         007_fix_tenant_admin_permission_grant.sql 008_seed_bootstrap_admin_role.sql \
         009_chunk_contextualization_cache.sql 010_multimodal.sql; do
  psql "$DATABASE_URL" -f "$f"
done
```

## Design notes

- Everything lives in the `valya` schema.
- Execution state (workflow progress, retries, heartbeats) lives in Temporal — Postgres only stores the workflow id and final outcome.
- Bytes live in MinIO; Postgres only stores URIs.
- Vectors live in Qdrant; Postgres only stores `(collection, point_id)`.
- Pipelines are immutable per `version` — bumping a pipeline always creates a new row, which lets you reindex safely and roll back.
- `events` is an outbox table — a dispatcher publishes unpublished rows to Kafka/Redis Streams.
- All mutable tables have `created_at`, `updated_at`, and (where applicable) `deleted_at` for soft deletes.
