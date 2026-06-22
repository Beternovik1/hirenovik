import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center py-24 gap-4 text-center">
      <h1 className="text-6xl font-bold text-hirenovik-text">404</h1>
      <p className="text-hirenovik-text-secondary">
        The page you requested could not be found.
      </p>
      <Link
        href="/"
        className="bg-hirenovik-link hover:opacity-90 text-white rounded-md px-5 py-2 text-sm font-medium transition-opacity"
      >
        Return home
      </Link>
    </div>
  );
}
