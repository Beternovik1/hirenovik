"use client";

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

export default function NavBar() {
  const pathname = usePathname();

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
      <div className="flex flex-wrap items-center gap-1 sm:gap-4">
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
    </nav>
  );
}
