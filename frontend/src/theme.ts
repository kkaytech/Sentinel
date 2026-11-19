// Light and dark themes. Dark is the default; the choice is a per-browser preference kept in
// localStorage, and the page still renders correctly when storage is unavailable. One shared
// store keeps every theme control (top bar, profile menu, profile page) in step.
import { useSyncExternalStore } from "react";

export type Theme = "dark" | "light";
const KEY = "sentinel-theme";
const listeners = new Set<() => void>();

function stored(): Theme {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

let theme: Theme = stored();

export function applyStoredTheme(): void {
  document.documentElement.dataset.theme = theme;
}

export function setTheme(next: Theme): void {
  theme = next;
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem(KEY, next);
  } catch {
    // Storage blocked: the theme still applies for this page view.
  }
  listeners.forEach((l) => l());
}

export function useTheme(): [Theme, () => void, (t: Theme) => void] {
  const value = useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => theme,
  );
  return [value, () => setTheme(value === "dark" ? "light" : "dark"), setTheme];
}
