"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "dark";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    setTheme(
      (document.documentElement.getAttribute("data-theme") as Theme | null) ||
        "dark",
    );
  }, []);

  function toggle() {
    const next: Theme = theme === "light" ? "dark" : "light";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("delphi-theme", next);
    } catch {}
  }

  const nextTheme = theme === "light" ? "Dark" : "Light";

  return (
    <button
      aria-label={`Switch to ${nextTheme.toLowerCase()} theme`}
      className="theme-toggle"
      onClick={toggle}
      type="button"
    >
      {nextTheme}
    </button>
  );
}
