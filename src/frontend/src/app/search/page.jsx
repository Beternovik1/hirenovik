"use client";

import { useState } from "react";
import { fetchSearch, fetchExpand } from "@/lib/api";
import Link from "next/link";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expanding, setExpanding] = useState(false);
  const [expandInfo, setExpandInfo] = useState(null);
  const [error, setError] = useState(null);
  const [searched, setSearched] = useState(false);

  async function search(e) {
    e?.preventDefault?.();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setExpandInfo(null);
    setSearched(true);
    const data = await fetchSearch(query, 10);
    setLoading(false);
    setResults(data);
    if (!data) {
      setError(
        "Could not reach the search API. Make sure the FastAPI backend is running and the FAISS index is loaded."
      );
    }
  }

  async function expand() {
    if (!query.trim()) return;
    setExpanding(true);
    setError(null);
    setExpandInfo(null);
    const data = await fetchExpand(query, 3);
    setExpanding(false);
    if (!data) {
      setError(
        "Query expansion failed. The backend may be offline or the expansion endpoint unavailable."
      );
      return;
    }
    setExpandInfo(data);
    // After expansion, re-run the search to surface updated results.
    setLoading(true);
    const refreshed = await fetchSearch(query, 10);
    setLoading(false);
    setResults(refreshed);
  }

  const jobs =
    results?.results || results?.jobs || results?.items || [];

  return (
    <div className="space-y-8 max-w-4xl mx-auto">
      <header>
        <h1 className="text-3xl font-bold text-hirenovik-text">
          Semantic Search
        </h1>
        <p className="text-hirenovik-text-secondary mt-2">
          Search job descriptions by meaning, not keywords. Powered by FAISS
          cosine similarity over 384-dimensional sentence embeddings. Use
          query expansion to iteratively refine the concept.
        </p>
      </header>

      <form onSubmit={search} className="flex flex-col sm:flex-row gap-3">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. data engineering with cloud and streaming"
          className="flex-1 bg-hirenovik-card text-hirenovik-text border border-hirenovik-border rounded-md px-4 py-2.5 text-sm focus:outline-none focus:border-hirenovik-link"
        />
        <button
          type="submit"
          disabled={loading}
          className="bg-hirenovik-link hover:opacity-90 text-white rounded-md px-6 py-2.5 text-sm font-medium disabled:opacity-50 transition-opacity"
        >
          {loading ? "Searching…" : "Search"}
        </button>
        <button
          type="button"
          onClick={expand}
          disabled={expanding || !query.trim()}
          className="border border-hirenovik-border text-hirenovik-text-secondary hover:text-hirenovik-text rounded-md px-6 py-2.5 text-sm font-medium disabled:opacity-50 transition-colors"
        >
          {expanding ? "Expanding…" : "Expand query"}
        </button>
      </form>

      {error && (
        <div className="bg-red-900/20 border border-red-800 text-red-300 rounded-lg p-4 text-sm">
          {error}
        </div>
      )}

      {/* Expansion result */}
      {expandInfo && (
        <section className="bg-hirenovik-card rounded-lg p-6 border border-hirenovik-border">
          <h2 className="text-lg font-semibold text-hirenovik-text mb-2">
            Query expansion result
          </h2>
          <p className="text-sm text-hirenovik-text-secondary">
            Ran {expandInfo.rounds ?? "?"} expansion rounds from seed &ldquo;{expandInfo.seed_text ?? query}&rdquo; — found {expandInfo.count ?? expandInfo.results?.length ?? 0} results.
          </p>
        </section>
      )}

      {/* Results */}
      {!searched && !loading && !error && (
        <p className="text-hirenovik-text-secondary text-center py-10">
          Enter a query above to search the job corpus by semantic similarity.
        </p>
      )}

      {searched && !loading && !error && jobs.length === 0 && (
        <p className="text-hirenovik-text-secondary text-center py-10">
          No matching jobs found. Try a different query or use query expansion.
        </p>
      )}

      {loading && (
        <p className="text-hirenovik-text-secondary text-center py-10">
          Searching the corpus…
        </p>
      )}

      {jobs.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold text-hirenovik-text mb-4">
            {jobs.length} results
          </h2>
          <div className="space-y-2">
            {jobs.map((r) => {
              const jobId = r.job_id ?? r.id;
              const score = r.score;
              const pct = score !== undefined && score !== null
                ? `${Math.round(Number(score) * 100)}%`
                : null;
              return (
                <Link
                  key={jobId}
                  href={`/jobs/${jobId}`}
                  className="flex items-center justify-between bg-hirenovik-card rounded-lg p-4 border border-hirenovik-border hover:border-hirenovik-link transition-colors"
                >
                  <span className="text-hirenovik-text font-medium">
                    Job #{jobId}
                  </span>
                  <span className="text-hirenovik-accent text-sm font-mono">
                    {pct ?? "—"}
                  </span>
                </Link>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
