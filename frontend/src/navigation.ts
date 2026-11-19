// Navigation memory for contextual Back buttons and scroll restoration.
//
// - Each path's last address (with its filters, search and page) is remembered, so Back to a
//   list returns to the list as it was left.
// - When the user arrived by following a link from that exact address, Back steps back in the
//   browser history instead of pushing a new entry, so the browser's own Back and Forward stay
//   in step with the button.
// - Scroll positions are kept per history entry and restored on Back and Forward.
import { useEffect, useLayoutEffect } from "react";
import { useLocation, useNavigationType } from "react-router-dom";

const lastSeen = new Map<string, string>();
const scrolls = new Map<string, number>();
let current: string | null = null;
let previous: string | null = null;
let currentKey = "";

export function rememberedUrl(path: string): string {
  return lastSeen.get(path) ?? path;
}

// True when the entry just behind this one in the history is `url`.
export function arrivedFrom(url: string): boolean {
  return previous === url;
}

export function useNavigationMemory(): void {
  const location = useLocation();
  const type = useNavigationType();
  const url = location.pathname + location.search;
  // The first render for a new location runs before the old page leaves the screen, so this is
  // the old page's true position, whatever started the navigation (a link, Back or Forward).
  if (currentKey && location.key !== currentKey) scrolls.set(currentKey, window.scrollY);

  useLayoutEffect(() => {
    if (url !== current) {
      // Only a push puts the page we came from directly behind us in the history.
      previous = type === "PUSH" ? current : type === "REPLACE" ? previous : null;
      current = url;
    }
    lastSeen.set(location.pathname, url);
    currentKey = location.key;

    if (type === "POP") {
      // Restore once the page has rendered enough content to scroll to.
      // A short timer rather than animation frames, which pause in background tabs.
      const target = scrolls.get(location.key) ?? 0;
      const started = performance.now();
      let timer = 0;
      const attempt = () => {
        const reachable = document.documentElement.scrollHeight - window.innerHeight >= target;
        if (reachable || performance.now() - started > 2000) window.scrollTo(0, target);
        else timer = window.setTimeout(attempt, 40);
      };
      attempt();
      return () => window.clearTimeout(timer);
    }
    if (type === "PUSH" && !location.hash) window.scrollTo(0, 0);
    return undefined;
  }, [location.key, location.pathname, location.hash, url, type]);

  // Also record the position as the user scrolls, for the entry currently shown.
  useEffect(() => {
    const save = () => scrolls.set(currentKey, window.scrollY);
    window.addEventListener("scroll", save, { passive: true });
    return () => window.removeEventListener("scroll", save);
  }, []);
}
