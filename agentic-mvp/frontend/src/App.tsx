import { Navigate, Route, Routes } from "react-router-dom";
import { HashRouter } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import SuperAdminLayout from "./components/SuperAdminLayout";
import AdminLayout from "./components/AdminLayout";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import BootstrapSuperAdmin from "./pages/BootstrapSuperAdmin";
import AgentsPage from "./pages/AgentsPage";
import SkillsPage from "./pages/SkillsPage";
import ToolsPage from "./pages/ToolsPage";
import PluginsPage from "./pages/PluginsPage";
import HooksPage from "./pages/HooksPage";
import PromptsPage from "./pages/PromptsPage";
import ChatPage from "./pages/ChatPage";
import PersonasPage from "./pages/PersonasPage";
import DatasourcesPage from "./pages/DatasourcesPage";
import ProjectsPage from "./pages/ProjectsPage";
import AdminUsersPage from "./pages/AdminUsersPage";
import AdminKnowledgePage from "./pages/AdminKnowledgePage";
import AdminExpertisePage from "./pages/AdminExpertisePage";
import AdminNormsPage from "./pages/AdminNormsPage";
import PlatformOverviewPage from "./pages/PlatformOverviewPage";
import PlatformTenantsPage from "./pages/PlatformTenantsPage";
import PlatformAdminsPage from "./pages/PlatformAdminsPage";
import PlatformModelsPage from "./pages/PlatformModelsPage";
import PlatformCostPage from "./pages/PlatformCostPage";
import PlatformHealthPage from "./pages/PlatformHealthPage";
import PlatformAuditPage from "./pages/PlatformAuditPage";

// Three role-based flows (see docs/AUTHORIZATION.md and the Knowledge
// Nexus mockups this app was reskinned onto):
//   super_admin -> platform dashboard (SuperAdminLayout), no tenant of its own
//   admin       -> tri-layer Knowledge/Expertise/Norms tabs (AdminLayout)
//   user        -> chat is the whole flow, no wrapping shell of its own
function RoleHome() {
  const { user } = useAuth();
  if (user?.role === "super_admin") return <Navigate to="/app/platform/overview" replace />;
  if (user?.role === "user") return <Navigate to="/app/chat" replace />;
  return <Navigate to="/app/admin/knowledge" replace />;
}

export default function App() {
  return (
    <HashRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/bootstrap-super-admin" element={<BootstrapSuperAdmin />} />

          <Route element={<ProtectedRoute />}>
            <Route path="/app" element={<RoleHome />} />

            {/* User flow: chat is the entire experience, full-screen. */}
            <Route path="/app/chat" element={<ChatPage />} />

            {/* Tenant Admin flow: dark topbar + Knowledge/Expertise/Norms tabs. */}
            <Route path="/app/admin" element={<AdminLayout />}>
              <Route index element={<Navigate to="knowledge" replace />} />
              <Route path="knowledge" element={<AdminKnowledgePage />} />
              <Route path="expertise" element={<AdminExpertisePage />} />
              <Route path="norms" element={<AdminNormsPage />} />
              {/* Full-detail registry pages, reachable but not top-level tabs. */}
              <Route path="projects" element={<ProjectsPage />} />
              <Route path="users" element={<AdminUsersPage />} />
              <Route path="prompts" element={<PromptsPage />} />
              <Route path="skills" element={<SkillsPage />} />
              <Route path="tools" element={<ToolsPage />} />
              <Route path="plugins" element={<PluginsPage />} />
              <Route path="hooks" element={<HooksPage />} />
              <Route path="datasources" element={<DatasourcesPage />} />
              <Route path="personas" element={<PersonasPage />} />
              <Route path="agents" element={<AgentsPage />} />
            </Route>

            {/* Super Admin flow: platform-wide dashboard. */}
            <Route path="/app/platform" element={<SuperAdminLayout />}>
              <Route index element={<Navigate to="overview" replace />} />
              <Route path="overview" element={<PlatformOverviewPage />} />
              <Route path="tenants" element={<PlatformTenantsPage />} />
              <Route path="admins" element={<PlatformAdminsPage />} />
              <Route path="models" element={<PlatformModelsPage />} />
              <Route path="cost" element={<PlatformCostPage />} />
              <Route path="health" element={<PlatformHealthPage />} />
              <Route path="audit" element={<PlatformAuditPage />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </AuthProvider>
    </HashRouter>
  );
}
