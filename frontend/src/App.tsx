import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { Shell } from "./components/Shell";
import { Empty } from "./components/ui";
import { AuditPage } from "./pages/Audit";
import { FindingPage } from "./pages/Finding";
import { ImpactPage } from "./pages/Impact";
import { LoginPage } from "./pages/Login";
import { OverviewPage } from "./pages/Overview";
import { PeriodPage } from "./pages/Period";
import { PeriodsPage } from "./pages/Periods";
import { PublicationPage, PublicationsPage } from "./pages/Publications";
import { ReviewPage } from "./pages/Review";
import { RunPage } from "./pages/Run";
import { UsersPage } from "./pages/Users";
import { VersionPage } from "./pages/Version";

export function App() {
  const { session, loading } = useAuth();
  if (loading) return null;
  if (!session) return <LoginPage />;
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<OverviewPage />} />
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
        <Route path="/overview" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Empty title="Page not found">The address does not match any screen.</Empty>} />
      </Routes>
    </Shell>
  );
}
