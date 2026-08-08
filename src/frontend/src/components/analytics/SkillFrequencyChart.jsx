"use client";

import { useState, useEffect } from "react";
import { fetchSkillFrequency } from "@/lib/api";
import { normalizeSkill, skillLabel, getSkillIcon } from "@/lib/skills";
import {
  siPython,
  siJavascript,
  siTypescript,
  siNodedotjs,
  siReact,
  siNextdotjs,
  siPostgresql,
  siMysql,
  siMongodb,
  siAmazonwebservices,
  siGooglecloud,
  siDocker,
  siKubernetes,
  siGit,
  siGithub,
  siApachespark,
  siApachekafka,
  siApacheairflow,
  siTerraform,
  siSnowflake,
  siScikitlearn,
  siPytorch,
  siTensorflow,
  siOpenjdk,
  siGo,
  siRust,
  siRuby,
  siPhp,
  siSwift,
  siKotlin,
  siScala,
  siR,
} from "simple-icons";
import InsightCard from "./InsightCard";
import InsightState from "./InsightState";

// ---------------------------------------------------------------------------
// Icon map — real Simple Icons SVGs keyed by the iconSlug from skills.js
// ---------------------------------------------------------------------------
const SKILL_ICONS = {
  siPython,
  siJavascript,
  siTypescript,
  siNodedotjs,
  siReact,
  siNextdotjs,
  siPostgresql,
  siMysql,
  siMongodb,
  siAmazonwebservices,
  siGooglecloud,
  siDocker,
  siKubernetes,
  siGit,
  siGithub,
  siApachespark,
  siApachekafka,
  siApacheairflow,
  siTerraform,
  siSnowflake,
  siScikitlearn,
  siPytorch,
  siTensorflow,
  siOpenjdk,
  siGo,
  siRust,
  siRuby,
  siPhp,
  siSwift,
  siKotlin,
  siScala,
  siR,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatCount(n) {
  if (n == null) return "\u2014";
  return Number(n).toLocaleString("en-US");
}

function SkillRowIcon({ slug }) {
  const icon = SKILL_ICONS[slug];
  if (!icon) return null; // no placeholder — just empty cell
  return (
    <svg
      viewBox="0 0 24 24"
      width={16}
      height={16}
      fill="currentColor"
      aria-hidden="true"
      style={{ display: "block", flexShrink: 0, color: "#52525B" }}
    >
      <path d={icon.path} />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Shimmer / loading state
// ---------------------------------------------------------------------------
function Shimmer() {
  return (
    <InsightCard
      title="Most Requested Skills"
      description="Skills most frequently detected across analyzed job listings."
    >
      <div className="mt-4 space-y-3 animate-pulse">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="flex gap-3 items-center h-6">
            <div className="w-6 h-4 bg-[#E8E5E0] rounded" />
            <div className="flex-1 h-4 bg-[#E8E5E0] rounded max-w-[200px]" />
            <div className="w-12 h-4 bg-[#E8E5E0] rounded" />
          </div>
        ))}
      </div>
    </InsightCard>
  );
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const VISIBLE_DEFAULT = 15;
const VISIBLE_EXPANDED = 30;

// Grid column widths (pixels – the "1fr" for bar column is handled via flex).
const RANK_W = 28;
const ICON_W = 24;
const LABEL_W = 150;
const COUNT_W = 72;

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function SkillFrequencyChart() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      const result = await fetchSkillFrequency(VISIBLE_EXPANDED);
      if (!active) return;
      setLoading(false);
      if (!result || !result.items) {
        setError(true);
        return;
      }
      setData(result);
    })();
    return () => {
      active = false;
    };
  }, []);

  if (loading) return <Shimmer />;
  if (error)
    return (
      <InsightCard
        title="Most Requested Skills"
        description="Skills most frequently detected across analyzed job listings."
      >
        <InsightState
          state="error"
          message="Unable to load skill-demand analytics."
        />
      </InsightCard>
    );
  if (!data || !data.items || data.items.length === 0) {
    return (
      <InsightCard
        title="Most Requested Skills"
        description="Skills most frequently detected across analyzed job listings."
      >
        <InsightState
          state="empty"
          message="No skill extraction data is available yet. Run the skill extraction backfill to populate results."
        />
      </InsightCard>
    );
  }

  const visibleCount = expanded ? VISIBLE_EXPANDED : VISIBLE_DEFAULT;
  const sliced = data.items.slice(0, visibleCount);

  const rows = sliced.map((item, i) => {
    const canonical = normalizeSkill(item.skill);
    return {
      label: skillLabel(canonical),
      canonical,
      count: item.job_count,
      prevalence: item.prevalence,
      rank: i + 1,
      iconSlug: getSkillIcon(canonical),
    };
  });

  const maxCount = Math.max(...rows.map((r) => r.count), 1);

  const totalSkills = data.total_unique_skills_observed ?? data.items.length;
  const processedJobs = data.processed_canonical_jobs ?? 0;
  const coveragePct =
    data.skill_coverage != null ? Math.round(data.skill_coverage * 100) : 0;
  const withSkills = data.jobs_with_at_least_one_skill ?? 0;

  const evidenceItems = [
    {
      label: `Top ${visibleCount} of ${totalSkills} observed skills`,
      value: null,
      variant: "neutral",
    },
    {
      label: "Skill-processed listings",
      value: formatCount(processedJobs),
      variant: "neutral",
    },
    {
      label: "Skill coverage",
      value: `${coveragePct}%`,
      variant: "neutral",
    },
    {
      label: "Listings with skills",
      value: formatCount(withSkills),
      variant: "neutral",
    },
  ];

  const hasExpand = data.items.length > VISIBLE_DEFAULT;

  return (
    <div>
      <InsightCard
        title="Most Requested Skills"
        description="Skills most frequently detected across analyzed job listings."
        evidence={evidenceItems}
      >
        {/* ---------- scale reference ---------- */}
        <div
          style={{
            marginLeft: RANK_W + ICON_W + LABEL_W,
            marginRight: COUNT_W,
            marginBottom: 12,
            position: "relative",
            height: 18,
          }}
        >
          {[0, 25, 50, 75, 100].map((pct) => (
            <span
              key={pct}
              style={{
                position: "absolute",
                left: `${pct}%`,
                transform: "translateX(-50%)",
                fontSize: 10,
                fontFamily: "var(--font-geist-mono)",
                color: "#A1A1AA",
              }}
            >
              {Math.round((maxCount * pct) / 100)}
            </span>
          ))}
        </div>

        {/* ---------- rows ---------- */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {rows.map((row) => {
            const barPct = (row.count / maxCount) * 100;
            const prevalencePct =
              row.prevalence != null
                ? `${(row.prevalence * 100).toFixed(1)}%`
                : null;

            return (
              <div
                key={row.rank}
                style={{
                  display: "flex",
                  alignItems: "center",
                  height: 22,
                  position: "relative",
                }}
                title={
                  prevalencePct
                    ? `${row.label}: ${formatCount(row.count)} listings · ${prevalencePct} of skill-processed`
                    : `${row.label}: ${formatCount(row.count)} listings`
                }
              >
                {/* Rank */}
                <span
                  style={{
                    width: RANK_W,
                    flexShrink: 0,
                    fontSize: 11,
                    fontFamily: "var(--font-geist-mono)",
                    color: "#A1A1AA",
                    textAlign: "right",
                    paddingRight: 6,
                  }}
                >
                  {String(row.rank).padStart(2, "0")}
                </span>

                {/* Icon */}
                <span
                  style={{
                    width: ICON_W,
                    flexShrink: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <SkillRowIcon slug={row.iconSlug} />
                </span>

                {/* Skill label */}
                <span
                  style={{
                    width: LABEL_W,
                    flexShrink: 0,
                    fontSize: 13,
                    fontFamily: "var(--font-geist-sans)",
                    fontWeight: 500,
                    color: "#18181B",
                    paddingRight: 8,
                    textAlign: "right",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {row.label}
                </span>

                {/* Bar area */}
                <div
                  style={{
                    flex: 1,
                    height: "100%",
                    position: "relative",
                    minWidth: 0,
                  }}
                >
                  {/* Background grid lines */}
                  {[0, 25, 50, 75, 100].map((pct) => (
                    <div
                      key={pct}
                      style={{
                        position: "absolute",
                        left: `${pct}%`,
                        top: 0,
                        bottom: 0,
                        width: 1,
                        backgroundColor: "#F0EDE8",
                        zIndex: 0,
                      }}
                    />
                  ))}
                  {/* Bar */}
                  <div
                    style={{
                      position: "absolute",
                      left: 0,
                      top: 0,
                      height: "100%",
                      width: `${barPct}%`,
                      backgroundColor: "#1E3A5F",
                      borderRadius: "0 2px 2px 0",
                      zIndex: 1,
                      minWidth: barPct > 0 ? 2 : 0,
                    }}
                  />
                </div>

                {/* Count */}
                <span
                  style={{
                    width: COUNT_W,
                    flexShrink: 0,
                    fontSize: 12,
                    fontFamily: "var(--font-geist-mono)",
                    color: "#52525B",
                    textAlign: "right",
                    paddingLeft: 12,
                  }}
                >
                  {formatCount(row.count)}
                </span>
              </div>
            );
          })}
        </div>
      </InsightCard>

      {hasExpand && (
        <div className="flex justify-center mt-3">
          <button
            onClick={() => setExpanded((prev) => !prev)}
            aria-expanded={expanded}
            className="text-[13px] text-hirenovik-analytics-ink-secondary hover:text-hirenovik-analytics-ink px-3 py-1.5 rounded-md transition-colors hover:bg-hirenovik-analytics-surface-alt"
            style={{ fontFamily: "var(--font-geist-sans)" }}
          >
            {expanded ? "Show top 15" : "Show top 30"}
          </button>
        </div>
      )}
    </div>
  );
}
