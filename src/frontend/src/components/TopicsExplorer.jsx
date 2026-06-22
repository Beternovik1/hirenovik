"use client";

import { useState } from "react";
import TopicCard from "@/components/TopicCard";

const SORT_OPTIONS = [
  { value: "count", label: "Job count" },
  { value: "coherence", label: "Coherence" },
  { value: "salary", label: "Avg salary" },
];

// Client wrapper that sorts a page of topics without re-fetching.
export default function TopicsExplorer({ topics = [] }) {
  const [sort, setSort] = useState("count");

  const sorted = [...topics].sort((a, b) => {
    if (sort === "coherence") {
      return (b.coherence ?? 0) - (a.coherence ?? 0);
    }
    if (sort === "salary") {
      return (b.avg_salary ?? 0) - (a.avg_salary ?? 0);
    }
    return (b.count ?? b.job_count ?? 0) - (a.count ?? a.job_count ?? 0);
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-sm text-hirenovik-text-secondary">Sort by:</span>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          className="bg-hirenovik-bg text-hirenovik-text border border-hirenovik-border rounded-md px-3 py-1.5 text-sm focus:outline-none focus:border-hirenovik-link"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      {sorted.length === 0 ? (
        <p className="text-hirenovik-text-secondary">
          No topics available. Run the NLP pipeline to discover topics.
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {sorted.map((t) => (
            <TopicCard key={t.id ?? t.topic_id} topic={t} />
          ))}
        </div>
      )}
    </div>
  );
}
