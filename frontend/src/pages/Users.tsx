import { UserPlus, Users as UsersIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError, api, type Page, type Role, type UserRow } from "../api";
import { useAuth } from "../auth";
import { ConfirmDialog, Dialog } from "../components/Dialog";
import { DataTable } from "../components/DataTable";
import { Badge, Card, Empty, ErrorNotice, Notice, PageHeader, Skeleton } from "../components/ui";
import { initials, toApiError, useLoad } from "../lib";

const ROLES: { role: Role; label: string; text: string }[] = [
  { role: "ANALYST", label: "Analyst", text: "Uploads, validates, requests waivers, submits for review" },
  { role: "APPROVER", label: "Approver", text: "Decides waivers and reviews" },
  { role: "ADMIN", label: "Administrator", text: "Manages users and configuration" },
];

const EMPTY = { username: "", display_name: "", password: "", roles: ["ANALYST"] as Role[] };

export function UsersPage() {
  const { session } = useAuth();
  const users = useLoad(() => api.get<Page<UserRow>>("/users"), []);
  const [form, setForm] = useState(EMPTY);
  const [creating, setCreating] = useState(false);
  const [toggling, setToggling] = useState<UserRow | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [formError, setFormError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function act(action: () => Promise<unknown>, done?: string) {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      await action();
      if (done) setNotice(done);
      users.reload();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    setBusy(true);
    try {
      await api.post("/users", form);
      setNotice(`${form.display_name} can now sign in as ${form.username}.`);
      setForm(EMPTY);
      setCreating(false);
      users.reload();
    } catch (err) {
      setFormError(toApiError(err));
    } finally {
      setBusy(false);
    }
  }

  function toggleRole(user: UserRow, role: Role) {
    const roles = user.roles.includes(role) ? user.roles.filter((r) => r !== role) : [...user.roles, role];
    void act(() => api.patch(`/users/${user.id}`, { roles }), `Roles updated for ${user.display_name}.`);
  }

  return (
    <>
      <PageHeader
        title="Users"
        subtitle="Users are deactivated, never deleted. A role change takes effect on the user's next request."
        actions={<button className="btn primary" onClick={() => setCreating(true)}><UserPlus aria-hidden />Create user</button>}
      />
      <div className="stack">
        <ErrorNotice error={error ?? users.error} />
        {notice && <Notice tone="ok" role="status">{notice}</Notice>}
        <Card title="All users" subtitle="Analysts and approvers must be different people: nobody can decide their own waiver or review." flush>
          {users.loading && !users.data && <Skeleton lines={4} />}
          {users.data && (
            <DataTable
              rows={users.data.items}
              rowKey={(u) => u.id}
              empty={<Empty icon={UsersIcon} title="No users" />}
              columns={[
                {
                  key: "user",
                  header: "User",
                  sort: (u) => u.username,
                  render: (u) => (
                    <span className="row" style={{ gap: 10, flexWrap: "nowrap" }}>
                      <span className="avatar" style={{ background: "var(--accent-soft)", color: "var(--accent-ink)" }} aria-hidden>{initials(u.display_name)}</span>
                      <span>
                        <strong style={{ color: "var(--ink)", fontWeight: 600 }}>{u.display_name}</strong>
                        <div className="faint mono" style={{ fontSize: 13 }}>{u.username}</div>
                      </span>
                    </span>
                  ),
                },
                {
                  key: "roles",
                  header: "Roles",
                  render: (u) => (
                    <div className="row" style={{ gap: 6 }}>
                      {ROLES.map(({ role, label }) => (
                        <label key={role} className="checkbox" style={{ marginRight: 6 }}>
                          <input type="checkbox" checked={u.roles.includes(role)} disabled={busy || !u.is_active} onChange={() => toggleRole(u, role)} />
                          <span>{label}</span>
                        </label>
                      ))}
                    </div>
                  ),
                },
                { key: "active", header: "Status", render: (u) => (u.is_active ? <Badge tone="ok" dot>Active</Badge> : <Badge tone="neutral" dot>Deactivated</Badge>) },
                {
                  key: "actions",
                  header: "",
                  align: "right",
                  render: (u) =>
                    u.id !== session?.user.id && (
                      <button className={`btn sm ${u.is_active ? "danger" : ""}`} onClick={() => setToggling(u)} disabled={busy}>
                        {u.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                    ),
                },
              ]}
            />
          )}
        </Card>
      </div>

      <Dialog
        open={creating}
        title="Create a user"
        icon={UserPlus}
        wide
        onClose={() => setCreating(false)}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setCreating(false)} disabled={busy}>Cancel</button>
            <button type="submit" form="create-user" className="btn primary" disabled={busy || form.roles.length === 0}>{busy ? "Creating…" : "Create user"}</button>
          </>
        }
      >
        <form id="create-user" className="stack" onSubmit={create}>
          <ErrorNotice error={formError} />
          <div className="grid-2" style={{ gap: 12 }}>
            <div className="field">
              <label className="field-label" htmlFor="new-username">Username</label>
              <input id="new-username" className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required autoComplete="off" />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="new-name">Display name</label>
              <input id="new-name" className="input" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} required />
            </div>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="new-password">Password</label>
            <input id="new-password" className="input" type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
            <span className="field-hint">At least 12 characters.</span>
          </div>
          <fieldset className="stack-sm" style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="field-label" style={{ marginBottom: 6 }}>Roles</legend>
            {ROLES.map(({ role, label, text }) => (
              <label key={role} className="checkbox">
                <input type="checkbox" checked={form.roles.includes(role)} onChange={() => setForm({ ...form, roles: form.roles.includes(role) ? form.roles.filter((r) => r !== role) : [...form.roles, role] })} />
                <span><strong style={{ fontWeight: 600, color: "var(--ink)" }}>{label}</strong> <span className="muted">· {text}</span></span>
              </label>
            ))}
          </fieldset>
        </form>
      </Dialog>

      <ConfirmDialog
        open={toggling !== null}
        title={toggling?.is_active ? `Deactivate ${toggling.display_name}?` : `Reactivate ${toggling?.display_name ?? ""}?`}
        confirmLabel={toggling?.is_active ? "Deactivate" : "Reactivate"}
        danger={toggling?.is_active}
        busy={busy}
        onClose={() => setToggling(null)}
        onConfirm={() => {
          const user = toggling;
          if (!user) return;
          void act(() => api.patch(`/users/${user.id}`, { is_active: !user.is_active }), `${user.display_name} ${user.is_active ? "deactivated" : "reactivated"}.`).then(() => setToggling(null));
        }}
      >
        <p>{toggling?.is_active ? "They are signed out and can no longer sign in. Their history stays in the audit trail." : "They can sign in again with their existing password and roles."}</p>
      </ConfirmDialog>
    </>
  );
}
