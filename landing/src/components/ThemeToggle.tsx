"use client";

/*
  Flips the `data-theme` attribute that the inline script in the root layout
  sets before first paint, and remembers the choice. The icon is chosen by
  CSS from the attribute, so the markup is identical on server and client.
*/
export function ThemeToggle() {
  function toggle() {
    const root = document.documentElement;
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try {
      window.localStorage.setItem("delphi-theme", next);
    } catch {
      // Storage unavailable; the choice lasts for this page view.
    }
  }

  return (
    <button type="button" className="theme-toggle" onClick={toggle} aria-label="Switch color theme">
      <svg className="icon-sun" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <g stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
          <path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8" />
        </g>
      </svg>
      <svg className="icon-moon" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}
