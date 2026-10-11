"use client";

import { Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

type Theme = "light" | "dark";
const EVENT = "ng-theme";

function subscribe(onChange: () => void) {
  window.addEventListener(EVENT, onChange);
  return () => window.removeEventListener(EVENT, onChange);
}

const read = (): Theme => (document.documentElement.dataset.theme === "dark" ? "dark" : "light");

/** The active theme, kept in sync with the toggle (for components that theme themselves). */
export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, read, () => "light" as Theme);
}

/** Light is the default; the choice is stored per browser (ng_theme). */
export function ThemeToggle({ className }: { className?: string }) {
  const theme = useTheme();
  const next: Theme = theme === "dark" ? "light" : "dark";
  const label = `Switch to ${next} theme`;
  return (
    <button
      type="button"
      onClick={() => {
        document.documentElement.dataset.theme = next;
        try {
          localStorage.setItem("ng_theme", next);
        } catch {
          // Storage unavailable (private mode): the theme still applies for this page view.
        }
        window.dispatchEvent(new Event(EVENT));
      }}
      aria-label={label}
      title={label}
      className={cn(
        "grid size-9 shrink-0 place-items-center rounded-full border text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground",
        className,
      )}
    >
      {theme === "dark" ? <Moon className="size-4" aria-hidden /> : <Sun className="size-4" aria-hidden />}
    </button>
  );
}

/** Applied before first paint so the stored theme never flashes. */
export const THEME_INIT_SCRIPT =
  "try{document.documentElement.dataset.theme=localStorage.getItem('ng_theme')==='dark'?'dark':'light'}catch(e){document.documentElement.dataset.theme='light'}";
