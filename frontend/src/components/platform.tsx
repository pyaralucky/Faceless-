import { Instagram, Youtube } from "lucide-react";
import { cx } from "@/lib/format";
import type { Platform } from "@/lib/types";

export function PlatformIcon({ platform, className }: { platform: Platform | string; className?: string }) {
  if (platform === "youtube") return <Youtube className={cx("h-4 w-4 shrink-0 text-rose-400", className)} aria-label="YouTube" />;
  if (platform === "instagram") return <Instagram className={cx("h-4 w-4 shrink-0 text-fuchsia-400", className)} aria-label="Instagram" />;
  return <span className={cx("text-xs text-zinc-500", className)}>{platform}</span>;
}

export function platformLabel(p: string): string {
  return p === "youtube" ? "YouTube" : p === "instagram" ? "Instagram" : p;
}
