"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Overview" },
  { href: "/analytics", label: "Analytics" },
  { href: "/history/phishing", label: "Phishing History" },
  { href: "/history/review", label: "Needs Review" },
  { href: "/history/reported", label: "Safe Reported" },
  { href: "/whitelist", label: "Whitelist" },
  { href: "/feedback", label: "Feedback" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sticky top-0 flex h-screen w-full max-w-[280px] flex-col border-r border-line/70 bg-[#091321]/90 px-6 py-8 backdrop-blur xl:w-[280px]">
      <div className="mb-10">
        <div className="text-xs uppercase tracking-[0.3em] text-accent">PhishGuard</div>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">Non-Visual Defense</h1>
        <p className="mt-3 text-sm text-slate-400">
          URL, content, structural, calibration, and safe-filter telemetry for device-scoped phishing review.
        </p>
      </div>

      <nav className="flex flex-col gap-2">
        {links.map((link) => {
          const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`rounded-2xl px-4 py-3 text-sm font-medium transition ${
                active
                  ? "bg-white/10 text-white shadow-glow"
                  : "text-slate-400 hover:bg-white/5 hover:text-white"
              }`}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto rounded-3xl border border-line/70 bg-white/5 p-4 text-sm text-slate-300">
        <div className="font-semibold text-white">Architecture</div>
        <p className="mt-2 text-slate-400">non_visual_multimodal_fusion</p>
      </div>
    </aside>
  );
}
