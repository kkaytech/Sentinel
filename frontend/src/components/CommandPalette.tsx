import { CalendarRange, CornerDownLeft, FileCheck2, FileUp, LayoutDashboard, ScrollText, Search, UserRound, Users, type LucideIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { DATASET, api, type Page, type PeriodRow, type Publication } from "../api";
import { useAuth } from "../auth";

interface Item {
  id: string;
  group: string;
  label: string;
  meta?: string;
  to: string;
  icon: LucideIcon;
}

// Jump to any screen, period, version or publication. Opens with Ctrl+K or Cmd+K.
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { has } = useAuth();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [records, setRecords] = useState<Item[]>([]);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    window.setTimeout(() => input.current?.focus(), 0);
    let live = true;
    Promise.all([api.get<Page<PeriodRow>>(`/datasets/${DATASET}/periods`), api.get<Page<Publication>>("/publications")])
      .then(([periods, publications]) => {
        if (!live) return;
        const items: Item[] = [];
        for (const p of periods.items) {
          items.push({ id: `p-${p.period}`, group: "Reporting periods", label: `Period ${p.period}`, meta: p.derived_state.replace(/_/g, " ").toLowerCase(), to: `/periods/${p.period}`, icon: CalendarRange });
          if (p.current_version) items.push({ id: `v-${p.current_version.id}`, group: "Versions", label: p.current_version.label, meta: "current version", to: `/versions/${p.current_version.id}`, icon: CalendarRange });
        }
        for (const pub of publications.items) items.push({ id: `pub-${pub.publication_ref}`, group: "Publications", label: pub.publication_ref, meta: pub.period, to: `/publications/${pub.publication_ref}`, icon: FileCheck2 });
        setRecords(items);
      })
      .catch(() => live && setRecords([]));
    return () => {
      live = false;
    };
  }, [open]);

  const items = useMemo(() => {
    const pages: Item[] = [
      { id: "overview", group: "Pages", label: "Overview", to: "/", icon: LayoutDashboard },
      ...(has("ANALYST") ? [{ id: "upload", group: "Pages", label: "Upload data", to: "/periods#upload", icon: FileUp }] : []),
      { id: "periods", group: "Pages", label: "Reporting periods", to: "/periods", icon: CalendarRange },
      { id: "publications", group: "Pages", label: "Publications", to: "/publications", icon: FileCheck2 },
      { id: "audit", group: "Pages", label: "Audit trail", to: "/audit", icon: ScrollText },
      ...(has("ADMIN") ? [{ id: "users", group: "Pages", label: "Users", to: "/users", icon: Users }] : []),
      { id: "profile", group: "Pages", label: "Profile and settings", to: "/profile", icon: UserRound },
    ];
    const q = query.trim().toLowerCase();
    return [...pages, ...records].filter((i) => !q || i.label.toLowerCase().includes(q) || i.meta?.toLowerCase().includes(q) || i.group.toLowerCase().includes(q));
  }, [query, records, has]);

  if (!open) return null;
  const go = (item: Item | undefined) => {
    if (!item) return;
    onClose();
    navigate(item.to);
  };
  const groups = Array.from(new Set(items.map((i) => i.group)));

  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="cmdk" role="dialog" aria-modal="true" aria-label="Jump to">
        <div className="cmdk-input">
          <Search aria-hidden />
          <input
            ref={input}
            value={query}
            placeholder="Jump to a page, period, version or publication…"
            aria-label="Search"
            aria-controls="cmdk-list"
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((a) => Math.min(a + 1, items.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((a) => Math.max(a - 1, 0));
              } else if (e.key === "Enter") {
                go(items[active]);
              } else if (e.key === "Escape") {
                onClose();
              }
            }}
          />
          <span className="kbd">Esc</span>
        </div>
        <div className="cmdk-list" id="cmdk-list" role="listbox">
          {items.length === 0 && <div className="empty compact">Nothing matches “{query}”.</div>}
          {groups.map((group) => (
            <div key={group}>
              <div className="cmdk-group">{group}</div>
              {items
                .filter((i) => i.group === group)
                .map((item) => {
                  const index = items.indexOf(item);
                  return (
                    <button
                      key={item.id}
                      type="button"
                      role="option"
                      className="cmdk-item"
                      aria-selected={index === active}
                      onMouseEnter={() => setActive(index)}
                      onClick={() => go(item)}
                    >
                      <item.icon aria-hidden />
                      {item.label}
                      {item.meta && <span className="meta">{item.meta}</span>}
                      {index === active && <CornerDownLeft aria-hidden style={{ marginLeft: item.meta ? 8 : "auto" }} />}
                    </button>
                  );
                })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
