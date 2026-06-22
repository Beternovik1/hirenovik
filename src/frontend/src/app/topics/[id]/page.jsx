import {
  fetchTopic,
  fetchTopicExamples,
  fetchTrends,
  formatSalary,
} from "@/lib/api";
import SkillTag from "@/components/SkillTag";
import Link from "next/link";
import { notFound } from "next/navigation";

export async function generateMetadata({ params }) {
  const { id } = await params;
  return {
    title: `Topic #${id} — Hirenovik`,
    description: `Topic detail, example jobs, and weekly trends for BERTopic topic ${id}.`,
  };
}

export default async function TopicDetailPage({ params }) {
  const { id } = await params;

  const [topic, examplesData, trendsData] = await Promise.all([
    fetchTopic(id),
    fetchTopicExamples(id, 5),
    fetchTrends(id),
  ]);

  if (!topic) {
    notFound();
  }

  const keywords = topic.keywords || [];
  const examples = examplesData?.examples || [];
  const trends = trendsData?.items || [];
  const trendingIds = new Set(trendsData?.trending_topic_ids || []);
  const isTrending = trendingIds.has(Number(id));

  const count = topic.count ?? topic.job_count ?? 0;
  const coherence =
    topic.coherence !== undefined && topic.coherence !== null
      ? Math.round(Number(topic.coherence) * 100)
      : null;
  const avgSalary = formatSalary(topic.avg_salary, topic.avg_salary, "MXN");

  return (
    <div className="space-y-8">
      <Link
        href="/topics"
        className="text-hirenovik-link text-sm hover:underline"
      >
        ← Back to topics
      </Link>

      <header className="bg-hirenovik-card rounded-lg p-6 border border-hirenovik-border">
        <h1 className="text-2xl font-bold text-hirenovik-text">
          {topic.name || `Topic ${id}`}
        </h1>
        <div className="flex flex-wrap items-center gap-4 mt-3 text-sm">
          <span className="text-hirenovik-accent font-medium">
            {count} jobs
          </span>
          {coherence !== null && (
            <span className="text-hirenovik-text-secondary">
              Coherence: {coherence}%
            </span>
          )}
          {avgSalary && (
            <span className="text-hirenovik-text-secondary">
              Avg salary: {avgSalary}
            </span>
          )}
          {isTrending && (
            <span className="text-emerald-300 border border-emerald-800 rounded px-2 py-0.5 text-xs">
              ↗ Trending
            </span>
          )}
        </div>
      </header>

      {keywords.length > 0 && (
        <section className="bg-hirenovik-card rounded-lg p-6 border border-hirenovik-border">
          <h2 className="text-lg font-semibold text-hirenovik-text mb-3">
            Keywords
          </h2>
          <div className="flex flex-wrap gap-2">
            {keywords.map((kw) => (
              <SkillTag key={kw} skill={kw} />
            ))}
          </div>
        </section>
      )}

      {examples.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold text-hirenovik-text mb-4">
            Example jobs
          </h2>
          <div className="space-y-2">
            {examples.map((ex) => (
              <Link
                key={ex.job_id}
                href={`/jobs/${ex.job_id}`}
                className="flex items-center justify-between bg-hirenovik-card rounded-lg p-4 border border-hirenovik-border hover:border-hirenovik-link transition-colors"
              >
                <span className="text-hirenovik-text font-medium truncate mr-4">
                  {ex.title || `Job #${ex.job_id}`}
                </span>
                <span className="text-hirenovik-accent text-sm font-mono shrink-0">
                  {Math.round(Number(ex.score) * 100)}%
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}

      {trends.length > 0 && (
        <section className="bg-hirenovik-card rounded-lg p-6 border border-hirenovik-border">
          <h2 className="text-lg font-semibold text-hirenovik-text mb-4">
            Weekly trends
          </h2>
          <div className="space-y-2">
            {trends.map((t, i) => {
              const label = t.week || t.date || `Week ${i + 1}`;
              const freq = t.frequency ?? t.count ?? t.jobs ?? 0;
              const max = Math.max(1, ...trends.map((x) => x.frequency ?? x.count ?? x.jobs ?? 0));
              const width = Math.round((freq / max) * 100);
              return (
                <div key={i} className="flex items-center gap-3">
                  <span className="text-xs text-hirenovik-text-secondary w-24 shrink-0">
                    {label}
                  </span>
                  <div className="flex-1 h-6 bg-hirenovik-bg rounded overflow-hidden">
                    <div
                      className="h-full bg-hirenovik-accent rounded"
                      style={{ width: `${width}%` }}
                    />
                  </div>
                  <span className="text-xs text-hirenovik-text w-8 text-right">
                    {freq}
                  </span>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
