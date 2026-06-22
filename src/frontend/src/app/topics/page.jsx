import { fetchTopics } from "@/lib/api";
import TopicsExplorer from "@/components/TopicsExplorer";
import Pagination from "@/components/Pagination";

export const metadata = {
  title: "Topics — Hirenovik",
  description:
    "Browse BERTopic-discovered job market topics with coherence scores and average salaries.",
};

export default async function TopicsPage({ searchParams }) {
  const sp = await searchParams;
  const page = Number(sp.page) || 1;

  const data = await fetchTopics(page, 20);
  const topics = data?.items || data?.topics || [];
  const total = data?.total ?? topics.length;
  const totalPages = (data?.total_pages ?? Math.ceil(total / 20)) || 1;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold text-hirenovik-text">Topic Browser</h1>
        <p className="text-hirenovik-text-secondary mt-1">
          {total > 0
            ? `${total} topics discovered by BERTopic`
            : "No topics available"}
        </p>
      </header>

      <TopicsExplorer topics={topics} />

      <Pagination currentPage={page} totalPages={totalPages} />
    </div>
  );
}
