import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { AuditPage } from "./pages/Audit";
import { FindingPage } from "./pages/Finding";
import { ImpactPage } from "./pages/Impact";
import { LoginPage } from "./pages/Login";
import { PeriodPage } from "./pages/Period";
import { PeriodsPage } from "./pages/Periods";
import { PublicationPage, PublicationsPage } from "./pages/Publications";
import { ReviewPage } from "./pages/Review";
import { RunPage } from "./pages/Run";
import { UsersPage } from "./pages/Users";
import { VersionPage } from "./pages/Version";
import { Loading } from "./ui";

export function App() {
  const { session, loading, signOut, has } = useAuth();
  if (loading) return <Loading what="Starting" />;
  if (!session) return <LoginPage />;
  return (
    <div className="shell">
      <header className="topbar">
        <NavLink to="/" className="brand">
          Sentinel
        </NavLink>
        <nav>
          <NavLink to="/periods">Periods</NavLink>
          <NavLink to="/publications">Publications</NavLink>
          <NavLink to="/audit">Audit</NavLink>
          {has("ADMIN") && <NavLink to="/users">Users</NavLink>}
        </nav>
        <div className="whoami">
          <span>
            {session.user.display_name} <span className="muted">({session.roles.join(", ")})</span>
          </span>
          <button className="link" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/periods" replace />} />
          <Route path="/periods" element={<PeriodsPage />} />
          <Route path="/periods/:period" element={<PeriodPage />} />
          <Route path="/versions/:versionId" element={<VersionPage />} />
          <Route path="/versions/:versionId/review" element={<ReviewPage />} />
          <Route path="/publications" element={<PublicationsPage />} />
          <Route path="/publications/:ref" element={<PublicationPage />} />
          <Route path="/runs/:runId" element={<RunPage />} />
          <Route path="/runs/:runId/impact" element={<ImpactPage />} />
          <Route path="/findings/:findingId" element={<FindingPage />} />
          <Route path="/audit" element={<AuditPage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </main>
    </div>
  );
}
