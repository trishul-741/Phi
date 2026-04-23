import type { ConsistencyStatus, StageVerdict } from "@phishguard/shared";
import { consistencyStatusLabel, verdictLabel } from "@phishguard/shared";

function StagePill({ label, verdict }: { label: string; verdict?: StageVerdict }) {
  const tone = verdict ?? "unknown";

  return (
    <div className="phishguard-stage-block">
      <span className="phishguard-stage-label">{label}</span>
      <span className={`phishguard-stage-pill phishguard-stage-pill-${tone}`}>
        {verdict ? verdictLabel(verdict) : "Unavailable"}
      </span>
    </div>
  );
}

export function ScanStageTrace({
  stage1Verdict,
  stage2Verdict,
  consistencyStatus,
  compact = false,
  title = "Decision path",
}: {
  stage1Verdict?: StageVerdict;
  stage2Verdict?: StageVerdict;
  consistencyStatus?: ConsistencyStatus;
  compact?: boolean;
  title?: string;
}) {
  if (!stage1Verdict && !stage2Verdict && !consistencyStatus) {
    return null;
  }

  return (
    <div className={`phishguard-trace ${compact ? "phishguard-trace-compact" : ""}`}>
      <div className="phishguard-trace-header">
        <span className="phishguard-section-title">{title}</span>
        {consistencyStatus ? (
          <span className={`phishguard-consistency-pill phishguard-consistency-pill-${consistencyStatus}`}>
            {consistencyStatusLabel(consistencyStatus)}
          </span>
        ) : null}
      </div>
      <div className="phishguard-stage-row">
        <StagePill label="Stage 1 precheck" verdict={stage1Verdict} />
        <StagePill label="Stage 2 full scan" verdict={stage2Verdict} />
      </div>
    </div>
  );
}
