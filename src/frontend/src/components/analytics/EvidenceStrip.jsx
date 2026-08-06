const VARIANT_CLASSES = {
  strong: "text-hirenovik-analytics-forest",
  weak: "text-hirenovik-analytics-gold-dark",
  neutral: "text-hirenovik-analytics-ink-secondary",
};

export default function EvidenceStrip({ items }) {
  if (!items || items.length === 0) return null;

  return (
    <>
      <hr className="mt-4 mb-3 border-t border-hirenovik-analytics-rule" />
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
        {items.map((item, i) => (
          <span key={i} className="inline-flex items-baseline gap-1.5">
            <span className="text-hirenovik-analytics-ink-secondary">
              {item.label}
            </span>
            <span
              className={`font-medium ${VARIANT_CLASSES[item.variant] || VARIANT_CLASSES.neutral}`}
              style={{ fontFamily: "var(--font-geist-mono)" }}
            >
              {item.value}
            </span>
          </span>
        ))}
      </div>
    </>
  );
}
