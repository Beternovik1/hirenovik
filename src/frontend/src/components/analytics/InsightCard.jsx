import EvidenceStrip from "./EvidenceStrip";

export default function InsightCard({ title, description, children, evidence }) {
  return (
    <section className="w-full border border-hirenovik-analytics-rule bg-hirenovik-analytics-surface rounded-[6px] px-5 py-5 sm:px-6">
      <h3 className="text-lg font-bold text-hirenovik-analytics-ink leading-snug">
        {title}
      </h3>

      {description && (
        <p className="mt-2 text-sm text-hirenovik-analytics-ink-secondary leading-relaxed max-w-prose">
          {description}
        </p>
      )}

      {children && <div className="mt-4">{children}</div>}

      {evidence && evidence.length > 0 && <EvidenceStrip items={evidence} />}
    </section>
  );
}
