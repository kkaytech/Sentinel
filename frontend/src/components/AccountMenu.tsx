import { Check, ChevronsUpDown, LogOut, Moon, Sun, UserRound } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import { initials } from "../lib";
import { roleLabel } from "../roles";
import { useTheme } from "../theme";

// The signed-in user's menu at the foot of the sidebar. Identity and roles come from the
// authenticated session (GET /session); nothing here is stored or invented in the browser.
export function AccountMenu() {
  const { session, signOut } = useAuth();
  const [theme, , setTheme] = useTheme();
  const [open, setOpen] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const location = useLocation();

  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    // Focus the first item when the menu opens.
    box.current?.querySelector<HTMLElement>('[role^="menuitem"]')?.focus({ preventScroll: true });
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  if (!session) return null;
  const { user, roles } = session;

  const items = () => [...(box.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? [])];
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      setOpen(false);
      trigger.current?.focus();
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Home" && e.key !== "End") return;
    e.preventDefault();
    const list = items();
    const at = list.indexOf(document.activeElement as HTMLElement);
    const next = e.key === "Home" ? 0 : e.key === "End" ? list.length - 1 : (at + (e.key === "ArrowDown" ? 1 : -1) + list.length) % list.length;
    list[next]?.focus({ preventScroll: true });
  };

  async function leave() {
    setLeaving(true);
    await signOut();
  }

  return (
    <div className="account" ref={box} onKeyDown={onKey}>
      {open && (
        <div className="account-menu" role="menu" aria-label="Account">
          <div className="account-head">
            <span className="avatar lg" aria-hidden>
              {initials(user.display_name)}
            </span>
            <div style={{ minWidth: 0 }}>
              <div className="account-name" title={user.display_name}>
                {user.display_name}
              </div>
              <div className="account-meta mono">@{user.username}</div>
              <div className="account-meta" title="Sentinel accounts have no email address">No email on record</div>
              <div className="pill-list" style={{ marginTop: 6 }}>
                {roles.map((r) => (
                  <span key={r} className="badge accent">
                    {roleLabel(r)}
                  </span>
                ))}
              </div>
            </div>
          </div>
          <div className="account-sep" role="separator" />
          <Link to="/profile" role="menuitem" className="account-item" onClick={() => setOpen(false)}>
            <UserRound aria-hidden />
            Profile and settings
          </Link>
          <div className="account-sep" role="separator" />
          <div className="account-label" id="theme-label">
            Theme
          </div>
          <div role="group" aria-labelledby="theme-label">
            {(["dark", "light"] as const).map((t) => (
              <button key={t} type="button" role="menuitemradio" aria-checked={theme === t} className="account-item" onClick={() => setTheme(t)}>
                {t === "dark" ? <Moon aria-hidden /> : <Sun aria-hidden />}
                {t === "dark" ? "Dark" : "Light"}
                {theme === t && <Check className="account-check" aria-hidden />}
              </button>
            ))}
          </div>
          <div className="account-sep" role="separator" />
          <button type="button" role="menuitem" className="account-item danger" onClick={() => void leave()} disabled={leaving}>
            <LogOut aria-hidden />
            {leaving ? "Signing out…" : "Sign out"}
          </button>
        </div>
      )}
      <button
        ref={trigger}
        type="button"
        className={`user-chip ${open ? "open" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${user.display_name}`}
        onClick={() => setOpen(!open)}
      >
        <span className="avatar" aria-hidden>
          {initials(user.display_name)}
        </span>
        <span className="user-meta">
          <span className="user-name">{user.display_name}</span>
          <span className="user-roles">{roles.map(roleLabel).join(" · ")}</span>
        </span>
        <ChevronsUpDown className="user-chevron" aria-hidden />
      </button>
    </div>
  );
}
