import DatasourcesPage from "./DatasourcesPage";

// The Admin Knowledge tab is exactly the existing Datasources registry —
// connectors, sync status, chunking/embedding policy per source — just
// reached via the tri-layer tab shell instead of the old sidebar nav.
export default function AdminKnowledgePage() {
  return <DatasourcesPage />;
}
