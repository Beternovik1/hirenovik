import Link from "next/link";
import { formatSalary } from "@/lib/api";

// Reusable card for a single BERTopic topic. Server component (no hooks).
export default function TopicCard({ topic }) {
  if (!topic) return null;

  const id = topic.id ?? topic.topic_id;
  const name = topic.name || `Topic ${id}`;
  const keywords = topic.keywords || [];
  const count = topic.count ?? topic.job_count ?? 0;
  const coherence =
    topic.coherence !== undefined && topic.coherence !== null
      ? Math.round(Number(topic.coherence) * 100)
      : null;
  const avgSalary = formatSalary(topic.avg_salary, topic.avg_salary, "MXN");

  return (
    <Link
      href={`/topics/${id}`}
      className="block bg-hirenovik-card rounded-lg p-6 border border-hirenovik-border hover:border-hirenovik-link transition-colors"
    >
      <h3 className="font-semibold text-hirenovik-text line-clamp-2">
        {name}
      </h3>

      {keywords.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {keywords.slice(0, 5).map((kw) => (
            <span
              key={kw}
              className="bg-slate-800 text-slate-300 rounded px-2 py-0.5 text-xs"
            >
              {kw}
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center gap-4 mt-4 text-sm">
        <span className="text-hirenovik-accent font-medium">
          {count} jobs
        </span>
        {avgSalary && (
          <span className="text-hirenovik-text-secondary">{avgSalary}</span>
        )}
      </div>

      {coherence !== null && (
        <div className="mt-3">
          <div className="flex items-center justify-between text-xs text-hirenovik-text-secondary mb-1">
            <span>Coherence</span>
            <span>{coherence}%</span>
          </div>
          <div className="h-1.5 w-full bg-hirenovik-bg rounded-full overflow-hidden">
            <div
              className="h-full bg-hirenovik-accent rounded-full"
              style={{ width: `${Math.min(100, Math.max(0, coherence))}%` }}
            />
          </div>
        </div>
      )}
    </Link>
  );
}
