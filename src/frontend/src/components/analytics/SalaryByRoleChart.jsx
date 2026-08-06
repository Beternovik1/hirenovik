"use client";

import { useState, useEffect } from "react";
import { fetchSalaryByRole } from "@/lib/api";
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
import InsightCard from "./InsightCard";
import InsightState from "./InsightState";

// ── Product-facing role labels ──
const ROLE_LABELS = {
  "data analyst": "Data Analytics",
  "data engineer": "Data Engineering",
  "data science/ml": "Data Science / ML",
  "software engineer": "Software Engineering",
  backend: "Backend",
  frontend: "Frontend",
  fullstack: "Full-Stack",
  "devops/cloud": "DevOps / Cloud",
  "qa/testing": "QA / Testing",
  security: "Security",
  "industrial/maintenance": "Industrial & Maintenance",
  other: "Other / Unclassified",
};

function roleLabel(key) {
  return ROLE_LABELS[key] || key;
}

// ── Formatting ──
function formatCompactMXN(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  if (v >= 1_000_000) return `MX$${(v / 1_000_000).toFixed(1)}M`;
  return `MX$${(v / 1000).toFixed(1)}k`;
}

function formatCount(n) {
  if (n == null) return "—";
  return Number(n).toLocaleString("en-US");
}

// ── X-axis tick (compact) ──
function axisTick(v) {
  if (v === 0) return "0";
  return `${(v / 1000).toFixed(0)}k`;
}

// ── Custom Y-axis tick with low-evidence indicator ──
function YAxisTick(props) {
  const { x, y, payload, chartData } = props;
  const entry = chartData.find((d) => d.name === payload.value);
  const isLowEvidence = entry && !entry.interpretationReady;

  return (
    <g transform={`translate(${x},${y})`}>
      <text
        x={0}
        y={0}
        dy={4}
        textAnchor="end"
        fill="var(--hirenovik-analytics-ink)"
        fontSize={12}
        style={{ fontFamily: "var(--font-geist-sans)" }}
      >
        {payload.value}
      </text>
      {isLowEvidence && (
        <circle cx={6} cy={-6} r={3} fill="var(--hirenovik-analytics-gold)" />
      )}
    </g>
  );
}

// ── Custom tooltip ──
function ChartTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const entry = payload[0].payload;
  const salary = entry.salary;
  const isLowEvidence = !entry.interpretationReady;

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
        {entry.name}
      </p>
      <p
        style={{
          margin: "4px 0 0",
          fontSize: 13,
          color: "#1E3A5F",
          fontFamily: "var(--font-geist-mono)",
          fontWeight: 500,
        }}
      >
        {salary != null ? formatCompactMXN(salary) : "—"}
      </p>
      <p
        style={{
          margin: "2px 0 0",
          fontSize: 11,
          color: "#71717A",
          fontFamily: "var(--font-geist-sans)",
        }}
      >
        {formatCount(entry.validRows)} valid salaries
        {isLowEvidence && (
          <span style={{ color: "#8B6914", marginLeft: 6 }}>· Limited coverage</span>
        )}
      </p>
    </div>
  );
}

// ── Bar value label (rendered at end of each bar) ──
function BarLabel(props) {
  const { x, y, width, value } = props;
  if (value == null) return null;
  return (
    <text
      x={x + width + 6}
      y={y + 14}
      fill="var(--hirenovik-analytics-ink-secondary)"
      fontSize={12}
      style={{ fontFamily: "var(--font-geist-mono)", fontWeight: 500 }}
    >
      {formatCompactMXN(value)}
    </text>
  );
}

// ── Main component ──
export default function SalaryByRoleChart() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      const result = await fetchSalaryByRole();
      if (!active) return;
      setLoading(false);
      if (!result || !result.items) {
        setError(true);
        return;
      }
      setData(result);
    })();
    return () => { active = false; };
  }, []);

  if (loading) return <InsightState state="loading" />;
  if (error) return <InsightState state="error" />;
  if (!data || !data.items || data.items.length === 0) {
    return <InsightState state="empty" />;
  }

  const sorted = [...data.items].sort(
    (a, b) => (b.median_salary_midpoint ?? 0) - (a.median_salary_midpoint ?? 0)
  );

  const chartData = sorted.map((item) => ({
    name: roleLabel(item.role_family),
    salary: item.median_salary_midpoint,
    listings: item.listings,
    validRows: item.valid_salary_rows,
    interpretationReady: item.interpretation_ready,
  }));

  const totalValid = data.total_valid_salary_rows;
  const totalListings = data.total_listings;
  const coverageValue =
    totalValid && totalListings
      ? ((totalValid / totalListings) * 100).toFixed(1)
      : null;

  const hasLowEvidence = chartData.some((d) => !d.interpretationReady);

  const evidenceItems = [
    { label: "Salary sample", value: formatCount(totalValid), variant: "neutral" },
    {
      label: "Coverage",
      value: coverageValue !== null ? `${coverageValue}%` : "—",
      variant: "neutral",
    },
    { label: "Dataset", value: "Mar – Jul 2026", variant: "neutral" },
  ];

  const chartHeight = Math.max(sorted.length * 38, 250);

  return (
    <InsightCard
      title="Salary by Role Family"
      description={
        hasLowEvidence
          ? "Median monthly salary in MXN across role families. Roles marked with an amber dot have limited sample size."
          : "Median monthly salary in MXN across role families."
      }
      evidence={evidenceItems}
    >
      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 4, right: 80, left: 10, bottom: 4 }}
        >
          <CartesianGrid
            horizontal={false}
            stroke="var(--hirenovik-analytics-rule)"
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
            tick={(props) => <YAxisTick {...props} chartData={chartData} />}
            width={140}
            interval={0}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip content={<ChartTooltip />} cursor={{ fill: "#F4F2EF" }} />
          <Bar
            dataKey="salary"
            fill="var(--hirenovik-analytics-accent)"
            radius={[0, 2, 2, 0]}
            isAnimationActive={false}
          >
            <LabelList dataKey="salary" content={<BarLabel />} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </InsightCard>
  );
}
