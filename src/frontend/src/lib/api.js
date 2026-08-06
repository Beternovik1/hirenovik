// Centralized fetch wrapper for the Hirenovik FastAPI backend.
// All functions return parsed JSON or null on failure.
//
// API_BASE differs between server and client:
// - SSR (server-side inside Docker): uses http://api:8000 via Docker network
// - Client (browser): uses http://localhost:8000 via host port mapping
export const API_BASE =
  typeof window === "undefined"
    ? process.env.NEXT_PUBLIC_API_URL || "http://api:8000"
    : "http://localhost:8000";

// Small artificial delay so loading states are perceptible on fast networks.
function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function getJSON(path, { revalidate = 30 } = {}) {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { Accept: "application/json" },
      // Server-side: cache briefly to avoid hammering the API during navigation.
      next: { revalidate },
    });
    if (!res.ok) {
      console.error(`API GET ${path} failed: ${res.status} ${res.statusText}`);
      return null;
    }
    return await res.json();
  } catch (err) {
    console.error(`API GET ${path} error:`, err.message);
    return null;
  }
}

async function postJSON(path, payload) {
  try {
    await delay(250);
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      console.error(`API POST ${path} failed: ${res.status} ${res.statusText}`);
      return null;
    }
    return await res.json();
  } catch (err) {
    console.error(`API POST ${path} error:`, err.message);
    return null;
  }
}

// --- GET endpoints ---

export function fetchHealth() {
  return getJSON("/");
}

export function fetchJobs({
  page = 1,
  size = 20,
  career = "",
  country_code = "",
  job_type = "",
} = {}) {
  const params = new URLSearchParams();
  params.set("page", String(page));
  params.set("size", String(size));
  if (career) params.set("career", career);
  if (country_code) params.set("country_code", country_code);
  if (job_type) params.set("job_type", job_type);
  return getJSON(`/jobs?${params.toString()}`);
}

export function fetchJob(id) {
  return getJSON(`/jobs/${id}`);
}

export function fetchTopics(page = 1, size = 20) {
  const params = new URLSearchParams();
  params.set("page", String(page));
  params.set("size", String(size));
  return getJSON(`/topics?${params.toString()}`);
}

export function fetchTopic(id) {
  return getJSON(`/topics/${id}`);
}

export function fetchTopicExamples(id, k = 5) {
  return getJSON(`/topics/${id}/examples?k=${k}`);
}

export function fetchTrends(topicId) {
  return getJSON(`/trends?topic_id=${topicId}`);
}

export function fetchSalaryByRole() {
  return getJSON("/analytics/salary-by-role");
}

export function fetchAnalyticsHealth() {
  return getJSON("/analytics/health");
}

// --- POST endpoints ---

export function fetchSearch(text, k = 10) {
  return postJSON("/search", { query: text, k });
}

export function fetchExpand(seed, rounds = 3) {
  return postJSON("/topics/expand", { seed_text: seed, rounds });
}

export function fetchPredict({ skills, seniority = 1, modality = 2, years_experience = 2 }) {
  return postJSON("/predict/salary", { skills, seniority, modality, years_experience });
}

export function fetchSkills(text) {
  return postJSON("/skills/extract", { text });
}

// --- Formatting helpers (shared by multiple components) ---

export function formatSalary(min, max, currency = "MXN") {
  const cur = currency || "MXN";
  const fmt = (n) => {
    if (n === null || n === undefined || Number.isNaN(Number(n))) return null;
    return Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 });
  };
  const lo = fmt(min);
  const hi = fmt(max);
  if (lo !== null && hi !== null) return `$${lo} – $${hi} ${cur}`;
  if (lo !== null) return `$${lo} ${cur}`;
  if (hi !== null) return `$${hi} ${cur}`;
  return null;
}

export function formatDate(dateStr) {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return String(dateStr);
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function relativeDate(dateStr) {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return formatDate(dateStr);
  const diffMs = Date.now() - d.getTime();
  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return formatDate(dateStr);
}
