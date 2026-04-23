import type { GroupedSignals } from "@phishguard/shared";

const groups = [
  { key: "url_signals", label: "URL Signals" },
  { key: "content_signals", label: "Content Signals" },
  { key: "structural_signals", label: "Structural Signals" },
  { key: "filter_signals", label: "Filter Signals" },
] as const;

export function SignalGroups({ signals }: { signals: GroupedSignals }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {groups.map((group) => {
        const items = signals[group.key];
        return (
          <div key={group.key} className="rounded-[24px] border border-line/70 bg-white/5 p-4">
            <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-400">{group.label}</h3>
            <div className="mt-4 space-y-3">
              {items.length === 0 ? (
                <p className="text-sm text-slate-500">No elevated signals in this category.</p>
              ) : (
                items.map((item) => (
                  <div key={`${group.key}-${item.key}`} className="rounded-2xl border border-line/60 bg-night/60 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-white">{item.label}</div>
                      <span className="text-xs uppercase tracking-[0.16em] text-slate-500">{item.severity}</span>
                    </div>
                    <div className="mt-2 text-sm text-slate-400">{item.description}</div>
                    <div className="mt-2 text-xs text-slate-500">Value: {String(item.value)}</div>
                  </div>
                ))
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
