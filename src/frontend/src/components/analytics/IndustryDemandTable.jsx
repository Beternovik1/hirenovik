"use client";

import { useState, useEffect } from "react";
import { fetchIndustryDemand } from "@/lib/api";
import InsightCard from "./InsightCard";
import InsightState from "./InsightState";

// ── Product-facing label maps ──
const NICHE_LABELS = {
  "Ingeniería de Datos": "Data Engineering",
  "Infraestructura Cloud": "Cloud Infrastructure",
  "Analítica de Datos": "Data Analytics",
  "Desarrollo de Software": "Software Development",
  "Inteligencia Artificial": "Artificial Intelligence",
  "Industrial Bajío": "Industrial Bajío",
  Ciberseguridad: "Cybersecurity",
  Software: "Software",
  Industrial: "Industrial",
  Datos: "Data",
};

const MODALITY_LABELS = {
  remoto: "Remote",
  híbrido: "Hybrid",
  presencial: "On-site",
  hibrido: "Hybrid",
};

const SOURCE_LABELS = {
  indeed: "Indeed",
  linkedin: "LinkedIn",
  occ: "OCC",
  computrabajo: "Computrabajo",
  occmundial: "OCC",
};

function nicheLabel(raw) {
  if (!raw || raw === "Unknown") return "Unspecified";
  return NICHE_LABELS[raw] || raw;
}

function modalityLabel(raw) {
  if (!raw || raw === "Unknown") return "Not specified";
  return MODALITY_LABELS[raw.toLowerCase()] || raw;
}

function sourceLabel(raw) {
  if (!raw || raw === "Unknown") return "Unspecified";
  return SOURCE_LABELS[raw.toLowerCase()] || raw;
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

// ── Tooltip ──
function RowTooltip({ entry }) {
  if (!entry) return null;
  const isLimited = !entry.interpretationReady;
  return (
    <div className="bg-white border border-[#E6E3DE] rounded-md px-3.5 py-2.5 text-xs shadow-sm">
      <p className="font-semibold text-[#18181B] text-[13px] mb-1 leading-snug">
        {entry.niche}
      </p>
      <p className="text-[#71717A] mb-0.5">
        {formatCount(entry.listings)} listings
      </p>
      <p className="text-[#1E3A5F] font-medium mb-0.5" style={{ fontFamily: "var(--font-geist-mono)" }}>
        {entry.salary != null ? formatCompactMXN(entry.salary) : "—"}
      </p>
      <p className="text-[#71717A]">
        {formatCount(entry.validRows)} valid salaries
        {isLimited && (
          <span className="text-[#8B6914] ml-1.5">· Limited coverage</span>
        )}
      </p>
    </div>
  );
}

// ── Loading shimmer ──
function TableShimmer() {
  return (
    <InsightCard title="Demand Segments" description="Top job-market segments ranked by listing volume.">
      <div className="mt-4 space-y-2 animate-pulse">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="flex gap-3 items-center h-8">
            <div className="w-6 h-3 bg-[#E8E5E0] rounded" />
            <div className="flex-1 h-3 bg-[#E8E5E0] rounded" />
            <div className="w-20 h-3 bg-[#E8E5E0] rounded" />
            <div className="w-24 h-3 bg-[#E8E5E0] rounded" />
            <div className="w-16 h-3 bg-[#E8E5E0] rounded hidden sm:block" />
            <div className="w-16 h-3 bg-[#E8E5E0] rounded hidden sm:block" />
          </div>
        ))}
      </div>
    </InsightCard>
  );
}

// ── Desktop row ──
function DesktopRow({ entry, rank }) {
  const isLimited = !entry.interpretationReady;
  const hasSalary = entry.salary != null;

  return (
    <tr className="border-b border-[#E8E5E0] last:border-b-0 hover:bg-[#FAFAF9]/50 transition-colors">
      <td className="py-2.5 pr-2 text-xs text-[#71717A] w-10" style={{ fontFamily: "var(--font-geist-mono)" }}>
        {String(rank).padStart(2, "0")}
      </td>
      <td className="py-2.5 pr-3 text-sm font-medium text-[#18181B] max-w-[220px] truncate">
        {entry.niche}
      </td>
      <td className="py-2.5 pr-3 text-sm text-[#18181B] max-w-[180px] truncate">
        {entry.career}
      </td>
      <td className="py-2.5 pr-3 text-right text-sm text-[#18181B] tabular-nums" style={{ fontFamily: "var(--font-geist-mono)" }}>
        {formatCount(entry.listings)}
      </td>
      <td className="py-2.5 pr-3 text-right text-sm tabular-nums" style={{ fontFamily: "var(--font-geist-mono)", color: hasSalary ? "#18181B" : "#71717A" }}>
        {hasSalary ? formatCompactMXN(entry.salary) : "—"}
        {isLimited && <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#D4A017] ml-1.5 align-middle" title="Limited salary coverage" />}
      </td>
      <td className="py-2.5 pr-3 text-xs text-[#71717A] hidden sm:table-cell">
        {entry.modality}
      </td>
      <td className="py-2.5 text-xs text-[#71717A] hidden md:table-cell">
        {entry.source}
      </td>
    </tr>
  );
}

// ── Mobile card ──
function MobileCard({ entry, rank }) {
  const isLimited = !entry.interpretationReady;
  const hasSalary = entry.salary != null;

  return (
    <div className="border border-[#E8E5E0] rounded-[6px] p-4 bg-white">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="min-w-0">
          <span className="text-xs text-[#71717A] mr-2" style={{ fontFamily: "var(--font-geist-mono)" }}>
            {String(rank).padStart(2, "0")}
          </span>
          <span className="text-sm font-semibold text-[#18181B]">{entry.niche}</span>
        </div>
      </div>
      <p className="text-xs text-[#71717A] mb-2.5">{entry.career}</p>
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="text-[#18181B] tabular-nums" style={{ fontFamily: "var(--font-geist-mono)" }}>
          {formatCount(entry.listings)}
        </span>
        <span className="tabular-nums" style={{ fontFamily: "var(--font-geist-mono)", color: hasSalary ? "#18181B" : "#71717A" }}>
          {hasSalary ? formatCompactMXN(entry.salary) : "—"}
          {isLimited && <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#D4A017] ml-1.5 align-middle" />}
        </span>
      </div>
      <div className="flex gap-3 mt-2 text-xs text-[#71717A]">
        <span>{entry.modality}</span>
        <span>{entry.source}</span>
      </div>
    </div>
  );
}

// ── Main component ──
export default function IndustryDemandTable() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      const result = await fetchIndustryDemand();
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

  if (loading) return <TableShimmer />;
  if (error) return <InsightState state="error" />;
  if (!data || !data.items || data.items.length === 0) {
    return <InsightState state="empty" />;
  }

  // Top 15 by listing count, stable secondary sort
  const segments = [...data.items]
    .sort((a, b) => b.listings - a.listings || (a.industry_niche || "").localeCompare(b.industry_niche || ""))
    .slice(0, 15)
    .map((item, i) => ({
      rank: i + 1,
      niche: nicheLabel(item.industry_niche),
      career: item.career && item.career !== "Unknown" ? item.career : "Unspecified",
      modality: modalityLabel(item.job_type),
      source: sourceLabel(item.site),
      listings: item.listings,
      salary: item.median_salary_midpoint,
      validRows: item.valid_salary_rows,
      interpretationReady: item.interpretation_ready,
    }));

  const totalSegments = data.total_groups ?? data.items.length;
  const totalListings = data.total_listings;
  const totalValid = data.total_valid_salary_rows;
  const salaryCoverage =
    totalValid && totalListings ? ((totalValid / totalListings) * 100).toFixed(1) : null;

  return (
    <InsightCard
      title="Demand Segments"
      description="Top job-market segments ranked by listing volume."
      evidence={[
        { label: `Top ${segments.length} of ${totalSegments} segments`, value: null, variant: "neutral" },
        { label: "Listings analyzed", value: formatCount(totalListings), variant: "neutral" },
        { label: "Valid salaries", value: formatCount(totalValid), variant: "neutral" },
        salaryCoverage !== null
          ? { label: "Salary coverage", value: `${salaryCoverage}%`, variant: "neutral" }
          : null,
      ].filter(Boolean)}
    >
      {/* ── Desktop table ── */}
      <div className="hidden sm:block mt-3">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-[#E8E5E0]">
              <th className="sticky top-[var(--hirenovik-navbar-height)] z-10 py-2 pr-2 text-xs font-medium text-[#71717A] w-10 bg-white">#</th>
              <th className="sticky top-[var(--hirenovik-navbar-height)] z-10 py-2 pr-3 text-xs font-medium text-[#71717A] bg-white">Segment</th>
              <th className="sticky top-[var(--hirenovik-navbar-height)] z-10 py-2 pr-3 text-xs font-medium text-[#71717A] bg-white">Role</th>
              <th className="sticky top-[var(--hirenovik-navbar-height)] z-10 py-2 pr-3 text-xs font-medium text-[#71717A] text-right bg-white">Listings</th>
              <th className="sticky top-[var(--hirenovik-navbar-height)] z-10 py-2 pr-3 text-xs font-medium text-[#71717A] text-right bg-white">Median</th>
              <th className="sticky top-[var(--hirenovik-navbar-height)] z-10 py-2 pr-3 text-xs font-medium text-[#71717A] hidden sm:table-cell bg-white">Work Mode</th>
              <th className="sticky top-[var(--hirenovik-navbar-height)] z-10 py-2 text-xs font-medium text-[#71717A] hidden md:table-cell bg-white">Source</th>
            </tr>
          </thead>
          <tbody>
            {segments.map((entry) => (
              <DesktopRow key={`${entry.rank}-${entry.niche}-${entry.career}`} entry={entry} rank={entry.rank} />
            ))}
          </tbody>
        </table>
      </div>

      {/* ── Mobile cards ── */}
      <div className="sm:hidden mt-4 space-y-3">
        {segments.map((entry) => (
          <MobileCard key={`${entry.rank}-${entry.niche}-${entry.career}`} entry={entry} rank={entry.rank} />
        ))}
      </div>
    </InsightCard>
  );
}
