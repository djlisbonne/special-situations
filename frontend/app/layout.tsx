import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";
import { ActivityPanel } from "@/components/ActivityPanel";

export const metadata: Metadata = {
  title: "Greenblatt",
  description: "Special-situations discovery in the Joel Greenblatt tradition",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-rule">
          <div className="max-w-[1400px] mx-auto px-6 py-4 flex items-baseline justify-between">
            <Link href="/" className="text-2xl tracking-tight">
              Greenblatt
              <span className="ml-2 text-sm text-muted sans">/ special situations</span>
            </Link>
            <nav className="sans text-sm space-x-6 text-muted">
              <Link href="/" className="hover:text-ink">Dashboard</Link>
              <Link href="/scan" className="hover:text-ink">Scan</Link>
              <a
                href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=10-12B&dateb=&owner=include&count=40"
                target="_blank" rel="noreferrer"
                className="hover:text-ink"
              >EDGAR ↗</a>
            </nav>
          </div>
        </header>
        <div className="max-w-[1400px] mx-auto px-6 py-8 flex gap-8">
          <main className="flex-1 min-w-0">{children}</main>
          <aside className="hidden lg:block w-72 shrink-0 border-l border-rule pl-6 sticky top-8 self-start h-[calc(100vh-6rem)]">
            <ActivityPanel />
          </aside>
        </div>
      </body>
    </html>
  );
}
