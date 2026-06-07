"use client";

import { usePathname } from "next/navigation";
import { ActivityPanel } from "./ActivityPanel";

// Event detail pages own the full width — they render their own right-side
// panel (filing viewer + chat), so the global Activity sidebar is hidden there.
export function ConditionalActivity() {
  const pathname = usePathname() || "";
  if (pathname.startsWith("/events/")) return null;
  return (
    <aside className="hidden lg:block w-72 shrink-0 border-l border-rule pl-6 sticky top-8 self-start h-[calc(100vh-6rem)]">
      <ActivityPanel />
    </aside>
  );
}
