"use client";

import { useRouter } from "next/navigation";
import JobFilters from "@/components/JobFilters";

// Thin client wrapper that translates JobFilters' onFilterChange into a URL
// navigation so the server page re-fetches with the new filters.
export default function JobsFilterBar({ initialFilters = {} }) {
  const router = useRouter();

  function handleFilterChange(filters) {
    const search = new URLSearchParams();
    if (filters.career) search.set("career", filters.career);
    if (filters.country_code) search.set("country_code", filters.country_code);
    if (filters.job_type) search.set("job_type", filters.job_type);
    // Reset to page 1 when filters change.
    const qs = search.toString();
    router.push(qs ? `/jobs?${qs}` : "/jobs");
  }

  return <JobFilters onFilterChange={handleFilterChange} initialFilters={initialFilters} />;
}
