"use client";

import { useRouter } from "next/navigation";

// URL-driven pagination. Pushes ?page=N (preserving other query params).
export default function Pagination({
  currentPage = 1,
  totalPages = 1,
  params = {},
}) {
  const router = useRouter();
  const total = Math.max(1, Number(totalPages) || 1);
  const page = Math.min(Math.max(1, Number(currentPage) || 1), total);

  function buildUrl(nextPage) {
    const search = new URLSearchParams({
      ...params,
      page: String(nextPage),
    });
    // Drop empty values to keep URLs clean.
    for (const [k, v] of [...search.entries()]) {
      if (!v) search.delete(k);
    }
    return `?${search.toString()}`;
  }

  function go(nextPage) {
    if (nextPage < 1 || nextPage > total || nextPage === page) return;
    router.push(buildUrl(nextPage));
  }

  if (total <= 1) return null;

  return (
    <div className="flex items-center justify-center gap-4 mt-8">
      <button
        type="button"
        onClick={() => go(page - 1)}
        disabled={page <= 1}
        className="border border-hirenovik-border text-hirenovik-text-secondary hover:text-hirenovik-text rounded-md px-4 py-2 text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        ← Prev
      </button>
      <span className="text-sm text-hirenovik-text-secondary">
        Page <span className="text-hirenovik-text font-medium">{page}</span> of{" "}
        {total}
      </span>
      <button
        type="button"
        onClick={() => go(page + 1)}
        disabled={page >= total}
        className="border border-hirenovik-border text-hirenovik-text-secondary hover:text-hirenovik-text rounded-md px-4 py-2 text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        Next →
      </button>
    </div>
  );
}
