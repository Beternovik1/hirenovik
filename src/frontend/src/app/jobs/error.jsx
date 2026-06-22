"use client";

import { useEffect } from "react";
import Link from "next/link";

export default function Error({ error, unstable_retry }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center py-24 gap-4 text-center">
      <h2 className="text-xl font-semibold text-hirenovik-text">
        Could not load jobs
      </h2>
      <p className="text-hirenovik-text-secondary text-sm max-w-md">
        {error?.message ||
          "The jobs API may be offline. Please try again or check the backend."}
      </p>
      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => unstable_retry()}
          className="bg-hirenovik-link hover:opacity-90 text-white rounded-md px-5 py-2 text-sm font-medium transition-opacity"
        >
          Try again
        </button>
        <Link
          href="/"
          className="border border-hirenovik-border text-hirenovik-text-secondary hover:text-hirenovik-text rounded-md px-5 py-2 text-sm transition-colors"
        >
          Go home
        </Link>
      </div>
    </div>
  );
}
