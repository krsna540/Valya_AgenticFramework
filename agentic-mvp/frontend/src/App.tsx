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

// The three mockup-faithful shells (admin-app.html/superadmin-app.html/
// user-app.html) — see components/mds/*Shell.tsx and
// styles/mockup-design-system.css. These are now the primary role-based
// flows; the "Hive"-reskinned pages above (SuperAdminLayout, AdminLayout,
// ChatPage, Platform*Page, Admin*Page) stay mounted at their original
// routes rather than being deleted — they're still fully functional and
// several of the mds- screens link real data through the same api/*
// modules those pages use, so nothing is orphaned, just no longer the
// default landing flow. See [[project_agentic_mvp_foundation_runtime_build]].
import SuperAdminShell from "./components/mds/SuperAdminShell";
import AdminShell from "./components/mds/AdminShell";
import UserShell from "./components/mds/UserShell";
import SaHealthPage from "./pages/superadmin/HealthPage";
import SaTenantsPage from "./pages/superadmin/TenantsPage";
import SaCatalogPage from "./pages/superadmin/CatalogPage";
import SaModelsPage from "./pages/superadmin/ModelsPage";
import SaRulesPage from "./pages/superadmin/RulesPage";
import SaAuditPage from "./pages/superadmin/AuditPage";
import Admin2OverviewPage from "./pages/admin2/OverviewPage";
import Admin2WorkspacesPage from "./pages/admin2/WorkspacesPage";
import Admin2PeoplePage from "./pages/admin2/PeoplePage";
import Admin2SourcesPage from "./pages/admin2/SourcesPage";
import Admin2AbilitiesPage from "./pages/admin2/AbilitiesPage";
import Admin2RulesPage from "./pages/admin2/RulesPage";
import UserHomePage from "./pages/user/HomePage";
import UserWorkspacePage from "./pages/user/WorkspacePage";
import UserActivityPage from "./pages/user/ActivityPage";
import UserSourcesPage from "./pages/user/SourcesPage";
import UserSettingsPage from "./pages/user/SettingsPage";

// Three role-based flows (see docs/AUTHORIZATION.md and the three uploaded
// mockups this app was rebuilt onto):
//   super_admin -> superadmin-app.html shell, platform-wide, no tenant of its own
//   admin       -> admin-app.html shell, one tenant's workspaces/people/sources/abilities/rules
//   user        -> user-app.html shell, workspace/chat is the whole flow
function RoleHome() {
  const { user } = useAuth();
  if (user?.role === "super_admin") return <Navigate to="/app/sa/health" replace />;
  if (user?.role === "user") return <Navigate to="/app/u/home" replace />;
  return <Navigate to="/app/admin2/overview" replace />;
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

            {/* Super Admin flow: legacy dashboard, kept reachable but no
                longer the default landing route (see RoleHome). */}
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

            {/* Super Admin flow: superadmin-app.html shell — the default
                landing route for super_admin (see RoleHome). Distinct
                prefix (/app/sa) from the legacy /app/platform dashboard
                above, so the two never collide on the same path. */}
            <Route path="/app/sa" element={<SuperAdminShell />}>
              <Route index element={<Navigate to="health" replace />} />
              <Route path="health" element={<SaHealthPage />} />
              <Route path="tenants" element={<SaTenantsPage />} />
              <Route path="catalog" element={<SaCatalogPage />} />
              <Route path="models" element={<SaModelsPage />} />
              <Route path="rules" element={<SaRulesPage />} />
              <Route path="audit" element={<SaAuditPage />} />
            </Route>

            {/* Admin flow: admin-app.html shell — the default landing route
                for admin (see RoleHome). Distinct path prefix (/app/admin2)
                from the legacy /app/admin tri-layer flow above, so both stay
                reachable without route collisions. */}
            <Route path="/app/admin2" element={<AdminShell />}>
              <Route index element={<Navigate to="overview" replace />} />
              <Route path="overview" element={<Admin2OverviewPage />} />
              <Route path="workspaces" element={<Admin2WorkspacesPage />} />
              <Route path="people" element={<Admin2PeoplePage />} />
              <Route path="sources" element={<Admin2SourcesPage />} />
              <Route path="abilities" element={<Admin2AbilitiesPage />} />
              <Route path="rules" element={<Admin2RulesPage />} />
            </Route>

            {/* User flow: user-app.html shell — the default landing route
                for user (see RoleHome). Distinct from the legacy full-screen
                /app/chat route, which stays reachable. */}
            <Route path="/app/u" element={<UserShell />}>
              <Route index element={<Navigate to="home" replace />} />
              <Route path="home" element={<UserHomePage />} />
              <Route path="workspace" element={<UserWorkspacePage />} />
              <Route path="workspace/:conversationId" element={<UserWorkspacePage />} />
              <Route path="activity" element={<UserActivityPage />} />
              <Route path="sources" element={<UserSourcesPage />} />
              <Route path="settings" element={<UserSettingsPage />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </AuthProvider>
    </HashRouter>
  );
}
