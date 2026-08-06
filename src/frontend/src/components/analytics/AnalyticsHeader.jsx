export default function AnalyticsHeader() {
  return (
    <header className="w-full">
      <div className="flex flex-col gap-[3px] mb-5">
        <hr className="border-t border-hirenovik-analytics-rule" />
        <hr className="border-t border-hirenovik-analytics-ink/20" />
        <hr className="border-t-[2px] border-hirenovik-analytics-accent" />
      </div>

      <h1
        className="text-[1.75rem] leading-tight font-bold text-hirenovik-analytics-ink tracking-tight"
        style={{ fontFamily: "var(--font-mexcellent)" }}
      >
        Market Intelligence
      </h1>

      <p className="mt-1.5 text-sm text-hirenovik-analytics-ink-secondary max-w-prose">
        Evidence-based summaries from the current jobs database
      </p>

      <hr className="mt-5 mb-0 border-t border-hirenovik-analytics-rule" />

      <p
        className="mt-2 text-xs text-hirenovik-analytics-ink-secondary"
        style={{ fontFamily: "var(--font-geist-mono)" }}
      >
        29,122 total jobs &middot; Mar &ndash; Jul 2026
      </p>
    </header>
  );
}
