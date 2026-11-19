import { CheckCircle2, Lock, LogOut, Moon, Sun, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type AuditEvent, type Page } from "../api";
import { useAuth } from "../auth";
import { Card, Empty, Hash, LoadError, Notice, PageHeader, Segmented, Skeleton } from "../components/ui";
import { ago, initials, useLoad, when } from "../lib";
import { ROLE_INFO, roleLabel } from "../roles";
import { useTheme } from "../theme";
import { describeEvent } from "./Overview";

const RECENT = 8;

// The signed-in user's own recorded actions, newest first, from the append-only audit trail.
async function loadActivity(userId: string): Promise<AuditEvent[]> {
  const first = await api.get<Page<AuditEvent>>(`/audit/events?actor_id=${userId}&limit=1`);
  if (first.total === 0) return [];
  const offset = Math.max(0, first.total - RECENT);
  const page = await api.get<Page<AuditEvent>>(`/audit/events?actor_id=${userId}&limit=${RECENT}&offset=${offset}`);
  return [...page.items].reverse();
}

// Read-only: the backend has no self-service profile or password endpoint, so nothing here is
// editable. Identity and roles come from the authenticated session.
export function ProfilePage() {
  const { session, signOut, has } = useAuth();
  const [theme, , setTheme] = useTheme();
  const [leaving, setLeaving] = useState(false);
  const userId = session?.user.id ?? "";
  const activity = useLoad(() => loadActivity(userId), [userId]);
  if (!session) return null;
  const { user, roles } = session;

  return (
    <>
      <PageHeader title="Profile and settings" subtitle="Your Sentinel account as the server knows it, and the preferences kept in this browser." />
      <div className="stack">
        <section className="card profile-hero glass">
          <span className="avatar xl" aria-hidden>
            {initials(user.display_name)}
          </span>
          <div style={{ minWidth: 0, flex: 1 }}>
            <h2 className="profile-name">{user.display_name}</h2>
            <div className="muted mono">@{user.username}</div>
            <div className="pill-list" style={{ marginTop: 10 }}>
              {roles.map((r) => (
                <span key={r} className="badge accent">
                  {roleLabel(r)}
                </span>
              ))}
              <span className="badge neutral">
                <Lock aria-hidden />
                Read-only
              </span>
            </div>
          </div>
          <button
            type="button"
            className="btn"
            disabled={leaving}
            onClick={async () => {
              setLeaving(true);
              await signOut();
            }}
          >
            <LogOut aria-hidden />
            {leaving ? "Signing out…" : "Sign out"}
          </button>
        </section>

        <div className="grid-2">
          <Card title="Account" subtitle="From your signed-in session.">
            <dl className="props">
              <dt>Display name</dt>
              <dd>{user.display_name}</dd>
              <dt>Username</dt>
              <dd className="mono">{user.username}</dd>
              <dt>Email address</dt>
              <dd>
                <span className="faint">Not recorded.</span> Sentinel accounts are identified by username and hold no email address.
              </dd>
              <dt>Roles</dt>
              <dd>{roles.map(roleLabel).join(", ")}</dd>
              <dt>User ID</dt>
              <dd>
                <Hash value={user.id} length={13} />
              </dd>
            </dl>
            <div style={{ marginTop: 16 }}>
              <Notice tone="info" title="Profile details can't be edited here">
                Sentinel has no self-service profile or password change. An administrator manages names, roles and access.
                {has("ADMIN") && (
                  <>
                    {" "}
                    As an administrator, you can do this on the <Link to="/users">Users</Link> page.
                  </>
                )}
              </Notice>
            </div>
          </Card>

          <Card title="What your roles allow" subtitle="The server checks these on every request.">
            <div className="stack" style={{ gap: 16 }}>
              {roles.map((r) => {
                const info = ROLE_INFO[r];
                return (
                  <div key={r}>
                    <div className="row" style={{ gap: 8, marginBottom: 8 }}>
                      <span className="badge accent">{info?.label ?? r}</span>
                      <span className="muted" style={{ fontSize: 13.5 }}>
                        {info?.summary}
                      </span>
                    </div>
                    <ul className="req-list">
                      {(info?.can ?? []).map((c) => (
                        <li key={c}>
                          <CheckCircle2 aria-hidden />
                          {c}
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
              <p className="faint" style={{ fontSize: 13 }}>
                Nobody may decide their own waiver or approve their own review, whatever their roles.
              </p>
            </div>
          </Card>
        </div>

        <div className="grid-2">
          <Card title="Preferences" subtitle="Saved in this browser only.">
            <div className="field">
              <span className="field-label" id="theme-pref">
                Theme
              </span>
              <Segmented
                label="Theme"
                value={theme}
                onChange={setTheme}
                options={[
                  { value: "dark", label: "Dark" },
                  { value: "light", label: "Light" },
                ]}
              />
              <span className="field-hint">
                {theme === "dark" ? <Moon width={14} height={14} aria-hidden style={{ verticalAlign: -2 }} /> : <Sun width={14} height={14} aria-hidden style={{ verticalAlign: -2 }} />} The {theme} theme is on. It also applies on the sign-in screen in this browser.
              </span>
            </div>
          </Card>

          <Card
            title="Your recent activity"
            subtitle="Your own actions from the append-only audit trail."
            actions={
              <Link to="/audit" className="btn sm ghost">
                Audit trail
              </Link>
            }
            flush
          >
            {activity.loading && !activity.data ? (
              <Skeleton lines={4} />
            ) : activity.error ? (
              <div style={{ padding: 16 }}>
                <LoadError error={activity.error} onRetry={activity.reload} title="Your activity could not be loaded" />
              </div>
            ) : (activity.data ?? []).length === 0 ? (
              <Empty compact icon={Users} title="No recorded activity yet" />
            ) : (
              <div className="activity">
                {(activity.data ?? []).map((e) => {
                  const d = describeEvent(e);
                  return (
                    <div className="activity-item" key={e.id}>
                      <span className={`activity-icon ${d.tone ?? ""}`} aria-hidden>
                        <d.icon />
                      </span>
                      <div className="activity-text">
                        <strong>{d.text}</strong>
                        {d.detail && <span className="muted"> · {d.detail}</span>}
                        <div className="faint" style={{ fontSize: 13 }}>
                          {when(e.occurred_at)}
                        </div>
                      </div>
                      <span className="tl-time nowrap">{ago(e.occurred_at)}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
