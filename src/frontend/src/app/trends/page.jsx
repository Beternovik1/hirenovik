"use client";

import { useState, useEffect } from "react";
import { fetchTopics, fetchTrends, formatSalary } from "@/lib/api";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  LineChart,
  Line,
} from "recharts";

export default function TrendsPage() {
  const [topics, setTopics] = useState([]);
  const [selected, setSelected] = useState("");
  const [trends, setTrends] = useState(null);
  const [loadingTopics, setLoadingTopics] = useState(true);
  const [loadingTrends, setLoadingTrends] = useState(false);
  const [error, setError] = useState(null);

  // Load topic list once on mount.
  useEffect(() => {
    let active = true;
    (async () => {
      setLoadingTopics(true);
      const data = await fetchTopics(1, 100);
      if (!active) return;
      const list = data?.items || data?.topics || [];
      setTopics(list);
      setLoadingTopics(false);
      // Auto-select the first topic for an immediate chart.
      if (list.length > 0 && !selected) {
        const firstId = list[0].id ?? list[0].topic_id;
        setSelected(String(firstId));
      }
    })();
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fetch trends whenever the selection changes.
  useEffect(() => {
    if (!selected) return;
    let active = true;
    (async () => {
      setLoadingTrends(true);
      setError(null);
      const data = await fetchTrends(selected);
      if (!active) return;
      setLoadingTrends(false);
      if (!data) {
        setError(
          "Could not load trends. Make sure the backend is running and trends have been computed."
        );
        setTrends(null);
        return;
      }
      setTrends(data);
    })();
    return () => {
      active = false;
    };
  }, [selected]);

  const allItems = trends?.items || [];
  // Filter client-side: backend returns all topics, we show only selected.
  const weekly = allItems.filter(
    (t) => String(t.topic_id) === String(selected)
  );
  const trendingIds = new Set(trends?.trending_topic_ids || []);
  const isTrending = trendingIds.has(Number(selected));

  const chartData = weekly.map((t, i) => ({
    name: t.week || `W${i + 1}`,
    frequency: t.count ?? 0,
    avgSalary: t.avg_salary != null ? Math.round(Number(t.avg_salary)) : null,
  }));

  const selectedTopic = topics.find(
    (t) => String(t.id ?? t.topic_id) === String(selected)
  );

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold text-hirenovik-text">Market Trends</h1>
        <p className="text-hirenovik-text-secondary mt-2">
          Weekly job-posting frequency and average salary per topic. Select a
          topic to see how demand evolves over time.
        </p>
      </header>

      {/* Topic selector */}
      <div className="flex items-center gap-3">
        <label className="text-sm text-hirenovik-text-secondary">Topic:</label>
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          disabled={loadingTopics}
          className="bg-hirenovik-card text-hirenovik-text border border-hirenovik-border rounded-md px-3 py-2 text-sm focus:outline-none focus:border-hirenovik-link min-w-[240px]"
        >
          {loadingTopics && <option>Loading topics…</option>}
          {!loadingTopics && topics.length === 0 && (
            <option value="">No topics available</option>
          )}
          {topics.map((t) => (
            <option
              key={t.id ?? t.topic_id}
              value={String(t.id ?? t.topic_id)}
            >
              {t.name || `Topic ${t.id ?? t.topic_id}`}
            </option>
          ))}
        </select>
        {trends && (
          <span
            className={`text-sm border rounded px-2 py-0.5 ${
              isTrending
                ? "text-emerald-300 border-emerald-800"
                : "text-hirenovik-text-secondary border-hirenovik-border"
            }`}
          >
            {isTrending ? "↗ Trending up" : "→ Flat"}
          </span>
        )}
      </div>

      {error && (
        <div className="bg-red-900/20 border border-red-800 text-red-300 rounded-lg p-4 text-sm">
          {error}
        </div>
      )}

      {loadingTrends && !error && (
        <p className="text-hirenovik-text-secondary">Loading trends…</p>
      )}

      {!loadingTrends && !error && chartData.length === 0 && (
        <p className="text-hirenovik-text-secondary">
          No trend data available for this topic.
        </p>
      )}

      {/* Frequency bar chart */}
      {chartData.length > 0 && !error && (
        <section className="bg-hirenovik-card rounded-lg p-6 border border-hirenovik-border">
          <h2 className="text-lg font-semibold text-hirenovik-text mb-4">
            Weekly posting frequency
            {selectedTopic?.name && (
              <span className="text-hirenovik-text-secondary font-normal text-sm">
                {" "}
                — {selectedTopic.name}
              </span>
            )}
          </h2>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="name" stroke="#94a3b8" fontSize={12} />
              <YAxis stroke="#94a3b8" fontSize={12} allowDecimals={false} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#0f172a",
                  border: "1px solid #1e293b",
                  borderRadius: "8px",
                  color: "#f1f5f9",
                }}
              />
              <Bar
                dataKey="frequency"
                fill="#34d399"
                radius={[4, 4, 0, 0]}
                name="Jobs"
              />
            </BarChart>
          </ResponsiveContainer>
        </section>
      )}

      {/* Salary line chart */}
      {chartData.length > 0 &&
        !error &&
        chartData.some((d) => d.avgSalary !== null) && (
          <section className="bg-hirenovik-card rounded-lg p-6 border border-hirenovik-border">
            <h2 className="text-lg font-semibold text-hirenovik-text mb-4">
              Average salary trend (MXN)
            </h2>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="name" stroke="#94a3b8" fontSize={12} />
                <YAxis
                  stroke="#94a3b8"
                  fontSize={12}
                  tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0f172a",
                    border: "1px solid #1e293b",
                    borderRadius: "8px",
                    color: "#f1f5f9",
                  }}
                  formatter={(v) => formatSalary(v, v, "MXN")}
                />
                <Line
                  type="monotone"
                  dataKey="avgSalary"
                  stroke="#0ea5e9"
                  strokeWidth={2}
                  dot={{ fill: "#0ea5e9", r: 3 }}
                  name="Avg salary"
                  connectNulls
                />
              </LineChart>
            </ResponsiveContainer>
          </section>
        )}
    </div>
  );
}
