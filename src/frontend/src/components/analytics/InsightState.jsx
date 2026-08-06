const STATE_CLASSES = {
  loading: "analytics-loading-shimmer rounded-[6px]",
  error: "bg-hirenovik-analytics-surface border-hirenovik-analytics-terracotta",
  empty: "text-hirenovik-analytics-ink-secondary",
  "low-evidence": "text-hirenovik-analytics-ink-secondary",
};

const STATE_DEFAULTS = {
  loading: "Loading…",
  error: "Unable to load this insight",
  empty: "No data available for this period",
  "low-evidence": "Insufficient data for reliable interpretation",
};

function sectionClass(state) {
  const base = "w-full border border-hirenovik-analytics-rule bg-hirenovik-analytics-surface rounded-[6px] px-5 py-8 sm:px-6 flex items-center justify-center";
  const extra = STATE_CLASSES[state] || "";
  return [base, extra].filter(Boolean).join(" ");
}

export default function InsightState({ state, message }) {
  const text = message || STATE_DEFAULTS[state] || "";

  return (
    <section className={sectionClass(state)}>
      <p className="text-sm leading-relaxed text-hirenovik-analytics-ink-secondary">
        {text}
      </p>
    </section>
  );
}
