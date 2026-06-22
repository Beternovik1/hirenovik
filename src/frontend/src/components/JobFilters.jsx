"use client";

import { useState } from "react";

const CAREERS = [
  "Data Engineer",
  "Data Analyst",
  "Analytics Engineer",
  "Cloud Engineer",
  "DevOps Engineer",
  "Python Developer",
  "React Developer",
  "Cybersecurity Engineer",
  "Business Intelligence",
  "Desarrollador Backend",
];

const COUNTRIES = [
  { code: "MX", label: "Mexico" },
  { code: "CO", label: "Colombia" },
  { code: "PE", label: "Peru" },
  { code: "CL", label: "Chile" },
  { code: "AR", label: "Argentina" },
];

const JOB_TYPES = ["remoto", "hibrido", "presencial"];

// Client-side filter bar. Calls onFilterChange with the new filter object.
export default function JobFilters({ onFilterChange, initialFilters = {} }) {
  const [career, setCareer] = useState(initialFilters.career || "");
  const [countryCode, setCountryCode] = useState(
    initialFilters.country_code || ""
  );
  const [jobType, setJobType] = useState(initialFilters.job_type || "");

  function apply() {
    onFilterChange({ career, country_code: countryCode, job_type: jobType });
  }

  function clear() {
    setCareer("");
    setCountryCode("");
    setJobType("");
    onFilterChange({ career: "", country_code: "", job_type: "" });
  }

  const selectClass =
    "bg-hirenovik-bg text-hirenovik-text border border-hirenovik-border rounded-md px-3 py-2 text-sm focus:outline-none focus:border-hirenovik-link";

  return (
    <div className="bg-hirenovik-card border border-hirenovik-border rounded-lg p-4 flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1">
        <span className="text-xs text-hirenovik-text-secondary">Career</span>
        <select
          value={career}
          onChange={(e) => setCareer(e.target.value)}
          className={selectClass}
        >
          <option value="">All careers</option>
          {CAREERS.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs text-hirenovik-text-secondary">Country</span>
        <select
          value={countryCode}
          onChange={(e) => setCountryCode(e.target.value)}
          className={selectClass}
        >
          <option value="">All countries</option>
          {COUNTRIES.map((c) => (
            <option key={c.code} value={c.code}>
              {c.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs text-hirenovik-text-secondary">Job type</span>
        <select
          value={jobType}
          onChange={(e) => setJobType(e.target.value)}
          className={selectClass}
        >
          <option value="">All types</option>
          {JOB_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={apply}
          className="bg-hirenovik-link hover:opacity-90 text-white rounded-md px-4 py-2 text-sm font-medium transition-opacity"
        >
          Apply filters
        </button>
        <button
          type="button"
          onClick={clear}
          className="border border-hirenovik-border text-hirenovik-text-secondary hover:text-hirenovik-text rounded-md px-4 py-2 text-sm transition-colors"
        >
          Clear
        </button>
      </div>
    </div>
  );
}
