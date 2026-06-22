export default function Loading() {
  return (
    <div className="space-y-6">
      <div className="h-8 w-48 bg-hirenovik-card rounded animate-pulse" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="h-40 bg-hirenovik-card border border-hirenovik-border rounded-lg animate-pulse"
          />
        ))}
      </div>
    </div>
  );
}
