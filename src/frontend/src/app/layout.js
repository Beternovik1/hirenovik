import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import NavBar from "@/components/NavBar";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata = {
  title: "Hirenovik — LATAM Tech Jobs Analytics",
  description:
    "ML-powered salary prediction and job market intelligence for LATAM tech jobs. BERTopic topic discovery, FAISS semantic search, and XGBoost salary modeling.",
};

export default function RootLayout({ children }) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        {/* Inline script: sets theme class BEFORE first paint — no flash */}
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  var saved = localStorage.getItem('hirenovik-theme');
                  var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                  if (saved === 'light' || (!saved && !prefersDark)) {
                    document.documentElement.classList.add('light');
                  }
                } catch (e) {}
              })();
            `,
          }}
        />
      </head>
      <body className="bg-hirenovik-bg text-hirenovik-text min-h-screen flex flex-col">
        <NavBar />
        <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {children}
        </main>
        <footer className="border-t border-hirenovik-border py-6 text-center text-sm text-hirenovik-text-secondary">
          Hirenovik — LATAM Tech Jobs Analytics · Powered by BERTopic + FAISS + XGBoost
        </footer>
      </body>
    </html>
  );
}
