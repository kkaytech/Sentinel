import { CalendarRange, FileCheck2, LayoutDashboard, LogOut, Menu, ScrollText, ShieldCheck, Users, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import { initials } from "../lib";

const ROLE_LABELS: Record<string, string> = { ANALYST: "Analyst", APPROVER: "Approver", ADMIN: "Administrator" };

export function BrandMark({ size = 16 }: { size?: number }) {
  return (
    <span className="brand-mark" aria-hidden>
      <ShieldCheck width={size} height={size} strokeWidth={2.2} />
    </span>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { session, signOut, has } = useAuth();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);
  if (!session) return null;
  const name = session.user.display_name;

  return (
    <div className={`shell ${open ? "nav-open" : ""}`}>
      <aside className="sidebar" aria-label="Main navigation">
        <Link to="/" className="brand">
          <BrandMark />
          <div>
            <div className="brand-name">Sentinel</div>
            <div className="brand-sub">Data quality gate</div>
          </div>
        </Link>
        <nav className="nav">
          <div className="nav-label">Workspace</div>
          <NavLink to="/" end>
            <LayoutDashboard aria-hidden />
            Overview
          </NavLink>
          <NavLink to="/periods">
            <CalendarRange aria-hidden />
            Reporting periods
          </NavLink>
          <NavLink to="/publications">
            <FileCheck2 aria-hidden />
            Publications
          </NavLink>
          <div className="nav-label">Governance</div>
          <NavLink to="/audit">
            <ScrollText aria-hidden />
            Audit trail
          </NavLink>
          {has("ADMIN") && (
            <NavLink to="/users">
              <Users aria-hidden />
              Users
            </NavLink>
          )}
        </nav>
        <div className="sidebar-foot">
          <div className="user-chip">
            <span className="avatar" aria-hidden>
              {initials(name)}
            </span>
            <div className="user-meta">
              <div className="user-name" title={name}>
                {name}
              </div>
              <div className="user-roles">{session.roles.map((r) => ROLE_LABELS[r] ?? r).join(" · ")}</div>
            </div>
            <button type="button" className="icon-btn" aria-label="Sign out" title="Sign out" onClick={() => void signOut()}>
              <LogOut />
            </button>
          </div>
        </div>
      </aside>
      <div className="scrim" onClick={() => setOpen(false)} aria-hidden />
      <div className="workspace">
        <div className="mobile-bar">
          <button type="button" className="icon-btn" aria-label={open ? "Close navigation" : "Open navigation"} onClick={() => setOpen(!open)}>
            {open ? <X /> : <Menu />}
          </button>
          <Link to="/" className="brand">
            <BrandMark size={14} />
            <span className="brand-name">Sentinel</span>
          </Link>
        </div>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
