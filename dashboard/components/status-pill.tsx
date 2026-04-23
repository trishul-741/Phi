import type { Verdict } from "@phishguard/shared";
import { verdictLabel } from "@phishguard/shared";

export function StatusPill({ verdict }: { verdict: Verdict }) {
  const tone =
    verdict === "safe"
      ? "bg-safe/15 text-emerald-200"
      : verdict === "suspicious"
        ? "bg-suspicious/15 text-amber-200"
        : verdict === "needs_review"
          ? "bg-sky-400/15 text-sky-200"
        : "bg-malicious/15 text-rose-200";

  return (
    <span className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] ${tone}`}>
      {verdictLabel(verdict)}
    </span>
  );
}
