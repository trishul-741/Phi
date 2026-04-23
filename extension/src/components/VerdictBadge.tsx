import type { Verdict } from "@phishguard/shared";
import { verdictLabel } from "@phishguard/shared";

export function VerdictBadge({ verdict, subtle = false }: { verdict: Verdict; subtle?: boolean }) {
  return (
    <span className={`phishguard-badge phishguard-badge-${verdict} ${subtle ? "phishguard-badge-subtle" : ""}`}>
      <span className="phishguard-badge-dot" aria-hidden="true" />
      {verdictLabel(verdict)}
    </span>
  );
}
