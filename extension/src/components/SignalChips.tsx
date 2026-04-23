import type { GroupedSignals } from "@phishguard/shared";

function flattenSignals(signals: GroupedSignals) {
  return [
    ...signals.url_signals,
    ...signals.content_signals,
    ...signals.structural_signals,
    ...signals.filter_signals,
  ];
}

export function SignalChips({
  signals,
  limit = 4,
}: {
  signals: GroupedSignals;
  limit?: number;
}) {
  const items = flattenSignals(signals).slice(0, limit);

  if (items.length === 0) {
    return <span className="phishguard-muted">No elevated non-visual signals.</span>;
  }

  return (
    <div className="phishguard-chip-row">
      {items.map((signal) => (
        <span key={`${signal.key}-${signal.label}`} className={`phishguard-chip phishguard-chip-${signal.severity}`}>
          {signal.label}
        </span>
      ))}
    </div>
  );
}
