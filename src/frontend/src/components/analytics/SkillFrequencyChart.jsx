"use client";

import { useState, useEffect } from "react";
import { fetchSkillFrequency } from "@/lib/api";
import { normalizeSkill, skillLabel, getSkillIcon } from "@/lib/skills";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  LabelList,
} from "recharts";
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

function SkillIcon({ slug, size = 16 }) {
  const Icon = SKILL_ICONS[slug];
  if (!Icon) {
    return (
      <div
        style={{
          width: size,
          height: size,
          borderRadius: 3,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: size * 0.6,
          fontWeight: 700,
          color: "var(--hirenovik-analytics-ink-secondary)",
          backgroundColor: "var(--hirenovik-analytics-surface-alt)",
          lineHeight: 1,
          flexShrink: 0,
        }}
        aria-hidden="true"
      />
    );
  }
  return (
    <Icon
      size={size}
      color="currentColor"
      aria-hidden="true"
      style={{ flexShrink: 0, display: "block" }}
    />
  );
}

function formatCount(n) {
  if (n == null) return "—";
  return Number(n).toLocaleString("en-US");
}

function axisTick(v) {
  if (v === 0) return "0";
  return String(v);
}

function YAxisTick(props) {
  const { x, y, payload } = props;
  const { rank, iconSlug, name } = payload || {};
  const rankText = rank != null ? String(rank).padStart(2, "0") : "";
  const Icon = iconSlug ? SKILL_ICONS[iconSlug] : null;
  const label = name || "";

  return (
    <g transform={`translate(${x},${y})`}>
      <text
        x={20}
        y={0}
        dy={4}
        textAnchor="end"
        fill="var(--hirenovik-analytics-ink-secondary)"
        fontSize={12}
        style={{ fontFamily: "var(--font-geist-mono)" }}
      >
        {rankText}
      </text>
      {Icon ? (
        <g
          transform="translate(24, -8)"
          color="var(--hirenovik-analytics-ink-secondary)"
        >
          <Icon size={16} color="currentColor" aria-hidden="true" />
        </g>
      ) : (
        <rect
          x={24}
          y={-8}
          width={16}
          height={16}
          rx={3}
          fill="var(--hirenovik-analytics-surface-alt)"
        />
      )}
      <text
        x={44}
        y={0}
        dy={4}
        textAnchor="start"
        fill="var(--hirenovik-analytics-ink)"
        fontSize={13}
        style={{ fontFamily: "var(--font-geist-sans)", fontWeight: 500 }}
      >
        {label}
      </text>
    </g>
  );
}

function BarLabel(props) {
  const { x, y, width, value, payload } = props;
  const displayName = payload?.name || "";
  if (value == null) return null;
  return (
    <text
      x={x + width + 8}
      y={y + 13.5}
      fill="var(--hirenovik-analytics-ink-secondary)"
      fontSize={12}
      style={{ fontFamily: "var(--font-geist-sans)", fontWeight: 500 }}
    >
      <tspan style={{ fontFamily: "var(--font-geist-sans)" }}>{displayName}</tspan>
      <tspan fill="var(--hirenovik-analytics-ink-secondary)" dx={4}>
        ·
      </tspan>
      <tspan
        dx={4}
        style={{ fontFamily: "var(--font-geist-mono)" }}
      >
        {formatCount(value)}
      </tspan>
    </text>
  );
}

function ChartTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const entry = payload[0].payload;
  const pct = entry.prevalence != null
    ? `${(entry.prevalence * 100).toFixed(1)}%`
    : "—";

  return (
    <div
      style={{
        backgroundColor: "#FFFFFF",
        border: "1px solid #E6E3DE",
        borderRadius: "6px",
        padding: "10px 14px",
        boxShadow: "0 2px 8px rgba(0,0,0,0.06)",
      }}
    >
      <p
        style={{
          margin: 0,
          fontSize: 13,
          fontWeight: 600,
          color: "#18181B",
          fontFamily: "var(--font-geist-sans)",
        }}
      >
        {entry.name} — {formatCount(entry.count)} listings
      </p>
      <p
        style={{
          margin: "4px 0 0",
          fontSize: 12,
          color: "#71717A",
          fontFamily: "var(--font-geist-sans)",
        }}
      >
        Appears in {pct} of skill-processed listings · Rank #{entry.rank}
      </p>
    </div>
  );
}

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

const VISIBLE_DEFAULT = 15;
const VISIBLE_EXPANDED = 30;

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
      <InsightCard title="Most Requested Skills" description="Skills most frequently detected across analyzed job listings.">
        <InsightState
          state="error"
          message="Unable to load skill-demand analytics."
        />
      </InsightCard>
    );
  if (!data || !data.items || data.items.length === 0) {
    return (
      <InsightCard title="Most Requested Skills" description="Skills most frequently detected across analyzed job listings.">
        <InsightState
          state="empty"
          message="No skill extraction data is available yet. Run the skill extraction backfill to populate results."
        />
      </InsightCard>
    );
  }

  const visibleCount = expanded ? VISIBLE_EXPANDED : VISIBLE_DEFAULT;
  const sliced = data.items.slice(0, visibleCount);

  const chartData = sliced.map((item, i) => {
    const canonical = normalizeSkill(item.skill);
    return {
      name: skillLabel(canonical),
      canonical,
      count: item.job_count,
      prevalence: item.prevalence,
      rank: i + 1,
      iconSlug: getSkillIcon(canonical),
    };
  });

  const totalSkills = data.total_unique_skills_observed ?? data.items.length;
  const processedJobs = data.processed_canonical_jobs ?? 0;
  const coveragePct = data.skill_coverage != null
    ? Math.round(data.skill_coverage * 100)
    : 0;
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
      label: `Skill coverage`,
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
  const barSize = 20;
  const chartHeight = Math.max(chartData.length * (barSize + 12), 200);

  return (
    <div>
      <InsightCard
        title="Most Requested Skills"
        description="Skills most frequently detected across analyzed job listings."
        evidence={evidenceItems}
      >
        <ResponsiveContainer width="100%" height={chartHeight}>
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 4, right: 170, left: 120, bottom: 4 }}
          >
            <CartesianGrid
              horizontal={false}
              stroke="#E8E5E0"
              strokeDasharray="3 3"
            />
            <XAxis
              type="number"
              stroke="var(--hirenovik-analytics-ink-secondary)"
              fontSize={11}
              tickFormatter={axisTick}
              style={{ fontFamily: "var(--font-geist-mono)" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              dataKey="name"
              type="category"
              tick={(props) => <YAxisTick {...props} />}
              width={120}
              interval={0}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              content={<ChartTooltip />}
              cursor={{ fill: "#F4F2EF" }}
            />
            <Bar
              dataKey="count"
              fill="#1E3A5F"
              radius={[0, 2, 2, 0]}
              barSize={barSize}
              isAnimationActive={false}
            >
              <LabelList dataKey="count" content={<BarLabel />} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
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
