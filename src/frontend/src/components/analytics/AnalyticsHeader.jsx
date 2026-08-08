"use client";

import { useState, useEffect } from "react";
import { fetchSkillFrequency } from "@/lib/api";

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function formatDateRange(start, end) {
  if (!start) return null;
  const s = new Date(start + "T00:00:00");
  const e = end ? new Date(end + "T00:00:00") : s;
  const sm = MONTHS[s.getMonth()];
  const em = MONTHS[e.getMonth()];
  const sy = s.getFullYear();
  const ey = e.getFullYear();

  if (sy === ey && sm === em) return `${sm} ${sy}`;
  if (sy === ey) return `${sm} \u2013 ${em} ${sy}`;
  return `${sm} ${sy} \u2013 ${em} ${ey}`;
}

export default function AnalyticsHeader() {
  const [summary, setSummary] = useState(null);

  useEffect(() => {
    let active = true;
    (async () => {
      const result = await fetchSkillFrequency(1);
      if (!active) return;
      setSummary(result);
    })();
    return () => { active = false; };
  }, []);

  const canonicalTotal = summary?.canonical_jobs_total;
  const dateLabel = summary
    ? formatDateRange(summary.dataset_start_date, summary.dataset_end_date)
    : null;

  return (
    <header className="w-full">
      <div className="flex flex-col gap-[3px] mb-5">
        <hr className="border-t border-hirenovik-analytics-rule" />
        <hr className="border-t border-hirenovik-analytics-ink/20" />
        <hr className="border-t-[2px] border-hirenovik-analytics-accent" />
      </div>

      <h1
        className="text-[1.75rem] leading-tight font-bold text-hirenovik-analytics-ink tracking-tight"
        style={{ fontFamily: "var(--font-mexcellent)" }}
      >
        Market Intelligence
      </h1>

      <p className="mt-1.5 text-sm text-hirenovik-analytics-ink-secondary max-w-prose">
        Evidence-based summaries from the current canonical jobs database
      </p>

      <hr className="mt-5 mb-0 border-t border-hirenovik-analytics-rule" />

      <p
        className="mt-2 text-xs text-hirenovik-analytics-ink-secondary"
        style={{ fontFamily: "var(--font-geist-mono)" }}
      >
        {canonicalTotal != null
          ? `${canonicalTotal.toLocaleString()} canonical listings`
          : "\u2014"}
        {dateLabel ? ` \u00b7 ${dateLabel}` : null}
      </p>
    </header>
  );
}
