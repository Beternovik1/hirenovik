import { fetchJob, fetchSearch, formatSalary, formatDate } from "@/lib/api";
import JobCard from "@/components/JobCard";
import Link from "next/link";
import { notFound } from "next/navigation";

export async function generateMetadata({ params }) {
  const { id } = await params;
  return {
    title: `Job #${id} — Hirenovik`,
    description: `Details for job listing ${id} in the Hirenovik LATAM tech jobs dataset.`,
  };
}

function DetailRow({ label, children }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4 py-3 border-b border-hirenovik-border last:border-0">
      <span className="text-hirenovik-text-secondary text-sm sm:w-40 shrink-0">
        {label}
      </span>
      <span className="text-hirenovik-text">{children}</span>
    </div>
  );
}

export default async function JobDetailPage({ params }) {
  const { id } = await params;
  const job = await fetchJob(id);

  if (!job) {
    notFound();
  }

  // Find similar jobs via semantic search on the job title.
  const searchData = await fetchSearch(job.title || "", 5);
  const similar =
    (searchData?.results || searchData?.jobs || searchData?.items || []).filter(
      (s) => String(s.id) !== String(id)
    );

  const salary = formatSalary(job.salary_min, job.salary_max, job.currency);

  return (
    <div className="space-y-8">
      <Link
        href="/jobs"
        className="text-hirenovik-link text-sm hover:underline"
      >
        ← Back to jobs
      </Link>

      <header className="bg-hirenovik-card rounded-lg p-6 border border-hirenovik-border">
        <h1 className="text-2xl font-bold text-hirenovik-text">
          {job.title || "Untitled role"}
        </h1>
        <p className="text-hirenovik-text-secondary mt-1">
          {job.company || "Empresa confidencial"}
        </p>
        {salary && (
          <p className="text-hirenovik-accent font-medium mt-2 text-lg">
            {salary}
          </p>
        )}
      </header>

      <section className="bg-hirenovik-card rounded-lg p-6 border border-hirenovik-border">
        <h2 className="text-lg font-semibold text-hirenovik-text mb-2">
          Details
        </h2>
        <DetailRow label="Location">{job.raw_location || "—"}</DetailRow>
        <DetailRow label="Country">{job.country || job.country_code || "—"}</DetailRow>
        <DetailRow label="State">{job.state || "—"}</DetailRow>
        <DetailRow label="Career">{job.career || "—"}</DetailRow>
        <DetailRow label="Job type">{job.job_type || "—"}</DetailRow>
        <DetailRow label="Site">{job.site || "—"}</DetailRow>
        <DetailRow label="Salary source">{job.salary_source || "—"}</DetailRow>
        <DetailRow label="Scraped by">{job.scraped_by || "—"}</DetailRow>
        <DetailRow label="Date posted">{job.date_posted || "—"}</DetailRow>
        <DetailRow label="Date scraped">{formatDate(job.date_scraped)}</DetailRow>
        <DetailRow label="Status">{job.status || "—"}</DetailRow>
      </section>

      {job.description && (
        <section className="bg-hirenovik-card rounded-lg p-6 border border-hirenovik-border">
          <h2 className="text-lg font-semibold text-hirenovik-text mb-3">
            Description
          </h2>
          <div className="text-hirenovik-text-secondary whitespace-pre-wrap text-sm leading-relaxed max-h-[600px] overflow-y-auto">
            {job.description}
          </div>
        </section>
      )}

      <section>
        <h2 className="text-lg font-semibold text-hirenovik-text mb-4">
          Similar jobs
        </h2>
        {similar.length === 0 ? (
          <p className="text-hirenovik-text-secondary">
            No similar jobs found.
          </p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {similar.map((s) => (
              <JobCard key={s.id} job={s} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
