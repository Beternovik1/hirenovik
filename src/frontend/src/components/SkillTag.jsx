"use client";

// Small removable skill chip. Used in the predict page and topic detail.
export default function SkillTag({ skill, onRemove, size = "sm" }) {
  const sizing =
    size === "md"
      ? "px-3 py-1 text-sm"
      : "px-2 py-0.5 text-xs";
  return (
    <span
      className={`inline-flex items-center gap-1 bg-emerald-900/30 text-emerald-300 border border-emerald-800 rounded-full ${sizing}`}
    >
      {skill}
      {onRemove && (
        <button
          type="button"
          onClick={() => onRemove(skill)}
          aria-label={`Remove ${skill}`}
          className="text-emerald-400 hover:text-emerald-200 leading-none"
        >
          ×
        </button>
      )}
    </span>
  );
}
