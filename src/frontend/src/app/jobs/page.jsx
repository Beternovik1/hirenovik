import { fetchJobs } from "@/lib/api";
import JobCard from "@/components/JobCard";
import JobsFilterBar from "@/components/JobsFilterBar";
import Pagination from "@/components/Pagination";

export const metadata = {
  title: "Jobs — Hirenovik",
  description: "Explore scraped LATAM tech job listings with filtering.",
};

export default async function JobsPage({ searchParams }) {
  const sp = await searchParams;
  const page = Number(sp.page) || 1;
  const career = sp.career || "";
  const countryCode = sp.country_code || "";
  const jobType = sp.job_type || "";

  const data = await fetchJobs({
    page,
    size: 20,
    career,
    country_code: countryCode,
    job_type: jobType,
  });

  const jobs = data?.items || data?.jobs || [];
  const total = data?.total ?? 0;
  const totalPages = (data?.total_pages ?? Math.ceil(total / 20)) || 1;

  const activeFilters = { career, country_code: countryCode, job_type: jobType };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold text-hirenovik-text">Job Explorer</h1>
        <p className="text-hirenovik-text-secondary mt-1">
          {total > 0
            ? `${total.toLocaleString()} jobs found`
            : "No jobs matched the current filters"}
        </p>
      </header>

      <JobsFilterBar initialFilters={activeFilters} />

      {jobs.length === 0 ? (
        <div className="bg-hirenovik-card border border-hirenovik-border rounded-lg p-10 text-center">
          <p className="text-hirenovik-text-secondary">
            No jobs found. Try adjusting the filters or check that the API is
            online.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {jobs.map((j) => (
            <JobCard key={j.id} job={j} />
          ))}
        </div>
      )}

      <Pagination
        currentPage={page}
        totalPages={totalPages}
        params={activeFilters}
      />
    </div>
  );
}
