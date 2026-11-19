import { CalendarRange, FileCheck2, FileUp, LayoutDashboard, Menu, ScrollText, Search, ShieldCheck, Users, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import { usePointerEffects } from "../motion";
import { useNavigationMemory } from "../navigation";
import { AccountMenu } from "./AccountMenu";
import { CommandPalette } from "./CommandPalette";


export function BrandMark({ size = 17 }: { size?: number }) {
  return (
    <span className="brand-mark" aria-hidden>
      <ShieldCheck width={size} height={size} strokeWidth={2.2} />
    </span>
  );
}

export function Atmosphere() {
  return (
    <div className="atmosphere" aria-hidden>
      <div className="atmosphere-aurora" />
      <div className="atmosphere-grid" />
    </div>
  );
}

// Live API and database status from the public health endpoint.
export function useSystemStatus(): { ok: boolean | null; checked: Date | null } {
  const [state, setState] = useState<{ ok: boolean | null; checked: Date | null }>({ ok: null, checked: null });
  useEffect(() => {
    let live = true;
    const check = () =>
      fetch("/health", { credentials: "same-origin" })
        .then((r) => r.json())
        .then((body: { status?: string; db?: string }) => live && setState({ ok: body.status === "ok" && body.db === "ok", checked: new Date() }))
        .catch(() => live && setState({ ok: false, checked: new Date() }));
    void check();
    const timer = window.setInterval(check, 60_000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);
  return state;
}

export function StatusPill() {
  const { ok } = useSystemStatus();
  return (
    <span className="status-pill" role="status">
      <span className={`pulse ${ok === false ? "bad" : ""}`} aria-hidden />
      {ok === null ? "Checking systems…" : ok ? "All systems operational" : "API or database unavailable"}
    </span>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { session, has } = useAuth();
  const [open, setOpen] = useState(false);
  const [palette, setPalette] = useState(false);
  const location = useLocation();
  const nav = useRef<HTMLElement>(null);
  usePointerEffects();
  useNavigationMemory();
  // One indicator glides to the active navigation item.
  useLayoutEffect(() => {
    const el = nav.current;
    if (!el) return;
    const place = () => {
      const active = el.querySelector<HTMLElement>("a.active");
      el.classList.toggle("has-indicator", !!active);
      if (active) {
        el.style.setProperty("--nav-y", `${active.offsetTop}px`);
        el.style.setProperty("--nav-h", `${active.offsetHeight}px`);
      }
    };
    place();
    // Glide between items, but appear in place on first paint.
    const frame = requestAnimationFrame(() => el.setAttribute("data-ready", ""));
    window.addEventListener("resize", place);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", place);
    };
  }, [location.pathname]);
  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  if (!session) return null;
  const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

  return (
    <div className={`shell ${open ? "nav-open" : ""}`}>
      <aside className="sidebar" aria-label="Main navigation">
        <Link to="/" className="brand">
          <BrandMark />
          <div>
            <div className="brand-name">Sentinel</div>
            <div className="brand-sub">Financial data intelligence</div>
          </div>
        </Link>
        <nav className="nav" ref={nav}>
          <span className="nav-indicator" aria-hidden style={{ transform: "translateY(var(--nav-y, 0))", height: "var(--nav-h, 0)" }} />
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
        <div className="sidebar-status">
          <div className="faint" style={{ fontSize: 11.5, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>Gate policy</div>
          <div className="muted" style={{ lineHeight: 1.45 }}>One approval by a second person · no self-approval · one publication per period</div>
        </div>
        <div className="sidebar-foot">
          <AccountMenu />
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
          <span className="spacer" />
          {has("ANALYST") && (
            <Link className="icon-btn" to="/periods#upload" aria-label="Upload data">
              <FileUp />
            </Link>
          )}
          <button type="button" className="icon-btn" aria-label="Search" onClick={() => setPalette(true)}>
            <Search />
          </button>
        </div>
        <header className="topbar">
          <button type="button" className="cmdk-trigger" onClick={() => setPalette(true)} aria-label="Search and jump to">
            <Search aria-hidden />
            Search periods, versions, publications…
            <span className="kbd">{mac ? "⌘" : "Ctrl"} K</span>
          </button>
          <span className="spacer" />
          <div className="topbar-actions">
            <StatusPill />
            {has("ANALYST") && location.pathname !== "/periods" && (
              <Link className="btn primary upload-cta" to="/periods#upload">
                <FileUp aria-hidden />
                Upload data
              </Link>
            )}
          </div>
        </header>
        <main className="content">
          <div key={location.pathname} className="page-enter">
            {children}
          </div>
        </main>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
    </div>
  );
}
