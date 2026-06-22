import { fetchHealth, fetchTopics, fetchJobs } from "@/lib/api";
import TopicCard from "@/components/TopicCard";
import JobCard from "@/components/JobCard";
import Link from "next/link";

export const metadata = {
  title: "Hirenovik — Dashboard",
  description:
    "Live overview of LATAM tech job market: model status, trending topics, and recent listings.",
};

function StatCard({ label, value, accent }) {
  return (
    <div className="bg-hirenovik-card rounded-lg p-6 border border-hirenovik-border">
      <p className="text-hirenovik-text-secondary text-sm">{label}</p>
      <p
        className={`text-2xl font-bold mt-1 ${
          accent ? "text-hirenovik-accent" : "text-hirenovik-text"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

export default async function DashboardPage() {
  const [health, topicsData, jobsData] = await Promise.all([
    fetchHealth(),
    fetchTopics(1, 6),
    fetchJobs({ page: 1, size: 5 }),
  ]);

  const topics = topicsData?.items || topicsData?.topics || [];
  const jobs = jobsData?.items || jobsData?.jobs || [];
  const totalTopics = topicsData?.total ?? topicsData?.total_topics ?? null;
  const totalJobs = jobsData?.total ?? null;

  const modelStatus = health?.models || health?.status || "unknown";
  const modelBadge =
    modelStatus === "ready" || modelStatus?.nlp === "ready"
      ? "text-hirenovik-accent"
      : "text-hirenovik-text-secondary";

  return (
    <div className="space-y-10">
      {/* Hero */}
      <section className="text-center sm:text-left">
        <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-hirenovik-text">
          Hirenovik
        </h1>
        <p className="mt-3 text-lg text-hirenovik-text-secondary max-w-2xl">
          LATAM Tech Jobs Analytics — ML-powered salary prediction and job
          market intelligence.
        </p>
      </section>

      {/* Stats */}
      <section className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Model status"
          value={typeof modelStatus === "object" ? "Live" : String(modelStatus)}
          accent
        />
        <StatCard
          label="Topics discovered"
          value={totalTopics !== null ? totalTopics : topics.length}
        />
        <StatCard
          label="Jobs indexed"
          value={totalJobs !== null ? totalJobs.toLocaleString() : "—"}
        />
      </section>

      {/* Recent topics */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-hirenovik-text">
            Trending topics
          </h2>
          <Link
            href="/topics"
            className="text-hirenovik-link text-sm hover:underline"
          >
            View all →
          </Link>
        </div>
        {topics.length === 0 ? (
          <p className="text-hirenovik-text-secondary">
            No topics available. Run the NLP pipeline to populate this section.
          </p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {topics.map((t) => (
              <TopicCard key={t.id ?? t.topic_id} topic={t} />
            ))}
          </div>
        )}
      </section>

      {/* Recent jobs */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-hirenovik-text">
            Recent jobs
          </h2>
          <Link
            href="/jobs"
            className="text-hirenovik-link text-sm hover:underline"
          >
            View all →
          </Link>
        </div>
        {jobs.length === 0 ? (
          <p className="text-hirenovik-text-secondary">
            No jobs available. The API may be offline.
          </p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {jobs.map((j) => (
              <JobCard key={j.id} job={j} />
            ))}
          </div>
        )}
      </section>

      {/* Model availability footer */}
      {health && typeof health.models === "object" && (
        <section className="text-sm text-hirenovik-text-secondary">
          <p>
            NLP:{" "}
            <span className={modelBadge}>
              {health.models.nlp || "unknown"}
            </span>{" "}
            · ML:{" "}
            <span className={modelBadge}>
              {health.models.ml || "unknown"}
            </span>
          </p>
        </section>
      )}
    </div>
  );
}
