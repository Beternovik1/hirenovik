export default function Loading() {
  return (
    <div className="flex flex-col items-center justify-center py-24 gap-4">
      <div className="h-10 w-10 border-2 border-hirenovik-border border-t-hirenovik-accent rounded-full animate-spin" />
      <p className="text-hirenovik-text-secondary text-sm">Loading…</p>
    </div>
  );
}
