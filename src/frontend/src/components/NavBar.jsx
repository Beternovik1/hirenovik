"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/jobs", label: "Jobs" },
  { href: "/topics", label: "Topics" },
  { href: "/search", label: "Search" },
  { href: "/trends", label: "Trends" },
  { href: "/predict", label: "Predict" },
];

function useTheme() {
  const [theme, setTheme] = useState("dark");

  useEffect(() => {
    // Read initial theme from the DOM (set by inline script)
    const isLight = document.documentElement.classList.contains("light");
    setTheme(isLight ? "light" : "dark");
    // Allow CSS transitions now that JS has settled
    document.documentElement.classList.add("theme-ready");
  }, []);

  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.classList.toggle("light", next === "light");
    try {
      localStorage.setItem("hirenovik-theme", next);
    } catch (e) {
      // localStorage unavailable (private browsing, etc.)
    }
  }

  return [theme, toggle];
}

export default function NavBar() {
  const pathname = usePathname();
  const [theme, toggleTheme] = useTheme();

  const isActive = (href) => {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(`${href}/`);
  };

  return (
    <nav className="bg-hirenovik-card border-b border-hirenovik-border px-4 sm:px-6 lg:px-8 py-4 flex flex-wrap items-center gap-6 sticky top-0 z-50">
      <Link
        href="/"
        className="text-hirenovik-text font-bold text-xl tracking-tight"
      >
        Hirenovik
      </Link>

      <div className="flex flex-wrap items-center gap-1 sm:gap-4 flex-1">
        {NAV_LINKS.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
              isActive(link.href)
                ? "text-hirenovik-accent font-medium bg-hirenovik-bg/40"
                : "text-hirenovik-text-secondary hover:text-hirenovik-text hover:bg-hirenovik-bg/20"
            }`}
          >
            {link.label}
          </Link>
        ))}
      </div>

      {/* Theme toggle */}
      <button
        onClick={toggleTheme}
        className="theme-toggle ml-auto"
        aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        title={theme === "dark" ? "Light mode" : "Dark mode"}
      >
        {theme === "dark" ? (
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="5" />
            <line x1="12" y1="1" x2="12" y2="3" />
            <line x1="12" y1="21" x2="12" y2="23" />
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
            <line x1="1" y1="12" x2="3" y2="12" />
            <line x1="21" y1="12" x2="23" y2="12" />
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
          </svg>
        ) : (
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        )}
      </button>
    </nav>
  );
}
