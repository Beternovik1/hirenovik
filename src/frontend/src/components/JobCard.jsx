import Link from "next/link";
import { formatSalary, relativeDate } from "@/lib/api";

const JOB_TYPE_STYLES = {
  remoto: "bg-sky-900/30 text-sky-300 border-sky-800",
  hibrido: "bg-amber-900/30 text-amber-300 border-amber-800",
  presencial: "bg-slate-800 text-slate-300 border-slate-700",
};

// Reusable card for a single job listing. Server component (no hooks).
export default function JobCard({ job }) {
  if (!job) return null;

  const salary = formatSalary(job.salary_min, job.salary_max, job.currency);
  const jobType = job.job_type || "";
  const typeStyle = JOB_TYPE_STYLES[jobType] || JOB_TYPE_STYLES.presencial;

  return (
    <Link
      href={`/jobs/${job.id}`}
      className="block bg-hirenovik-card rounded-lg p-5 border border-hirenovik-border hover:border-hirenovik-link transition-colors"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold text-hirenovik-text truncate">
            {job.title || "Untitled role"}
          </h3>
          <p className="text-hirenovik-text-secondary text-sm mt-0.5">
            {job.company || "Empresa confidencial"}
          </p>
        </div>
        {job.site && (
          <span className="shrink-0 text-xs uppercase tracking-wide text-hirenovik-text-secondary border border-hirenovik-border rounded px-1.5 py-0.5">
            {job.site}
          </span>
        )}
      </div>

      {job.raw_location && (
        <p className="text-hirenovik-text-secondary text-sm mt-2 flex items-center gap-1">
          <span aria-hidden>📍</span>
          <span className="truncate">{job.raw_location}</span>
        </p>
      )}

      {salary && (
        <p className="text-hirenovik-accent font-medium text-sm mt-2">{salary}</p>
      )}

      <div className="flex flex-wrap items-center gap-2 mt-3">
        {job.career && (
          <span className="text-xs bg-hirenovik-bg/60 text-hirenovik-text-secondary border border-hirenovik-border rounded px-2 py-0.5">
            {job.career}
          </span>
        )}
        {jobType && (
          <span
            className={`text-xs border rounded px-2 py-0.5 ${typeStyle}`}
          >
            {jobType}
          </span>
        )}
        {job.date_scraped && (
          <span className="text-xs text-hirenovik-text-secondary ml-auto">
            {relativeDate(job.date_scraped)}
          </span>
        )}
      </div>
    </Link>
  );
}
