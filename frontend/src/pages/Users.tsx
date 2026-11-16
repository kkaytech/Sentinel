import { useState, type FormEvent } from "react";
import { ApiError, api, type Page, type Role, type UserRow } from "../api";
import { useAuth } from "../auth";
import { Card, ErrorBox, Loading, toApiError, useLoad } from "../ui";

const ROLES: Role[] = ["ANALYST", "APPROVER", "ADMIN"];

export function UsersPage() {
  const { session } = useAuth();
  const users = useLoad(() => api.get<Page<UserRow>>("/users"), []);
  const [form, setForm] = useState({ username: "", display_name: "", password: "", roles: ["ANALYST"] as Role[] });
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function act(action: () => Promise<unknown>, done?: string) {
    setError(null);
    setNotice(null);
    try {
      await action();
      if (done) setNotice(done);
      users.reload();
    } catch (err) {
      setError(toApiError(err));
    }
  }

  function create(event: FormEvent) {
    event.preventDefault();
    void act(async () => {
      await api.post("/users", form);
      setForm({ username: "", display_name: "", password: "", roles: ["ANALYST"] });
    }, "User created.");
  }

  function toggleRole(user: UserRow, role: Role) {
    const roles = user.roles.includes(role) ? user.roles.filter((r) => r !== role) : [...user.roles, role];
    void act(() => api.patch(`/users/${user.id}`, { roles }));
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Users</h1>
          <p className="muted">Users are deactivated, never deleted. A role change takes effect on the user's next request.</p>
        </div>
      </div>
      <ErrorBox error={error ?? users.error} />
      {notice && <div className="alert ok">{notice}</div>}
      <Card title="Create a user">
        <form onSubmit={create}>
          <div className="row">
            <div className="field">
              <label htmlFor="new-username">Username</label>
              <input id="new-username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required />
            </div>
            <div className="field">
              <label htmlFor="new-name">Display name</label>
              <input id="new-name" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} required />
            </div>
            <div className="field">
              <label htmlFor="new-password">Password (12 characters or more)</label>
              <input id="new-password" type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
            </div>
            <div className="field">
              <label>Roles</label>
              {ROLES.map((role) => (
                <label key={role} style={{ display: "inline-block", marginRight: 10, color: "inherit" }}>
                  <input
                    type="checkbox"
                    checked={form.roles.includes(role)}
                    onChange={() => setForm({ ...form, roles: form.roles.includes(role) ? form.roles.filter((r) => r !== role) : [...form.roles, role] })}
                  />{" "}
                  {role}
                </label>
              ))}
            </div>
            <div className="field">
              <button className="primary" type="submit">
                Create
              </button>
            </div>
          </div>
        </form>
      </Card>
      <Card title="All users">
        {users.loading && !users.data && <Loading />}
        {users.data && (
          <table>
            <thead>
              <tr>
                <th>Username</th>
                <th>Display name</th>
                <th>Roles</th>
                <th>Active</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {users.data.items.map((u) => (
                <tr key={u.id}>
                  <td className="mono">{u.username}</td>
                  <td>{u.display_name}</td>
                  <td>
                    {ROLES.map((role) => (
                      <label key={role} style={{ display: "inline-block", marginRight: 10, color: "inherit" }}>
                        <input type="checkbox" checked={u.roles.includes(role)} onChange={() => toggleRole(u, role)} /> {role}
                      </label>
                    ))}
                  </td>
                  <td>{u.is_active ? "Yes" : "No"}</td>
                  <td>
                    {u.id !== session?.user.id && (
                      <button onClick={() => void act(() => api.patch(`/users/${u.id}`, { is_active: !u.is_active }))}>
                        {u.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
