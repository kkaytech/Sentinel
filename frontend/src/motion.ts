// Motion helpers built on requestAnimationFrame and CSS variables. No animation library.
import { useEffect, useRef, useState } from "react";

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

// Counts from the previous value to the new one with an ease-out curve.
export function useCountUp(target: number, duration = 900): number {
  const [value, setValue] = useState(prefersReducedMotion() ? target : 0);
  const from = useRef(prefersReducedMotion() ? target : 0);
  useEffect(() => {
    if (prefersReducedMotion() || !Number.isFinite(target)) {
      setValue(target);
      from.current = target;
      return;
    }
    const start = performance.now();
    const origin = from.current;
    let frame = 0;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(origin + (target - origin) * eased);
      if (t < 1) frame = requestAnimationFrame(step);
      else from.current = target;
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, duration]);
  return value;
}

// One document-level pointer listener drives the spotlight and tilt effects of every card,
// so cards need no handlers of their own.
export function usePointerEffects(): void {
  useEffect(() => {
    if (prefersReducedMotion() || window.matchMedia?.("(hover: none)").matches) return;
    let tilted: HTMLElement | null = null;
    const reset = (el: HTMLElement | null) => {
      if (!el) return;
      for (const name of ["--rx", "--ry", "--px", "--py"]) el.style.removeProperty(name);
    };
    const onMove = (event: PointerEvent) => {
      const target = event.target as Element | null;
      const spot = target?.closest?.<HTMLElement>(".spotlight");
      if (spot) {
        const r = spot.getBoundingClientRect();
        spot.style.setProperty("--mx", `${event.clientX - r.left}px`);
        spot.style.setProperty("--my", `${event.clientY - r.top}px`);
      }
      const tilt = target?.closest?.<HTMLElement>(".tilt") ?? null;
      if (tilt !== tilted) {
        reset(tilted);
        tilted = tilt;
      }
      if (tilt) {
        const r = tilt.getBoundingClientRect();
        const x = (event.clientX - r.left) / r.width - 0.5;
        const y = (event.clientY - r.top) / r.height - 0.5;
        tilt.style.setProperty("--rx", `${(-y * 7).toFixed(2)}deg`);
        tilt.style.setProperty("--ry", `${(x * 8).toFixed(2)}deg`);
        // Parallax: inner layers drift toward the pointer, so the value reads as nearer than the card.
        tilt.style.setProperty("--px", `${(x * 6).toFixed(1)}px`);
        tilt.style.setProperty("--py", `${(y * 4).toFixed(1)}px`);
      }
    };
    const onLeave = () => {
      reset(tilted);
      tilted = null;
    };
    document.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("pointerleave", onLeave);
    return () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerleave", onLeave);
    };
  }, []);
}
