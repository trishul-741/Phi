"use client";

import { consistencyStatusLabel, formatTimestamp, scoreToPercent, verdictLabel } from "@phishguard/shared";

import { EmptyState } from "../empty-state";
import { Panel } from "../panel";
import { SignalGroups } from "../signal-groups";
import { StatCard } from "../stat-card";
import { StatusPill } from "../status-pill";
import { useScanReportByUrl } from "../../lib/report-hooks";

export function ReportByUrlPageClient({
  url,
  deviceId,
}: {
  url: string;
  deviceId?: string;
}) {
  const { report, loading, feedbackEvents } = useScanReportByUrl(url, deviceId);

  if (!url) {
    return <EmptyState title="Missing URL" body="Add a `url` query parameter to open a fallback report route." />;
  }

  if (loading) {
    return <div className="text-slate-400">Loading report...</div>;
  }

  if (!report) {
    return <EmptyState title="No report found" body="No local or synced report was available for this URL." />;
  }

  return (
    <div className="space-y-6">
      <section className="rounded-[32px] border border-line/70 bg-surface/85 p-6 shadow-glow">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-accent">URL fallback report</div>
            <h1 className="mt-2 text-3xl font-semibold text-white">{report.url}</h1>
          </div>
          <StatusPill verdict={report.verdict} />
        </div>
      </section>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Raw score" value={scoreToPercent(report.raw_score)} />
        <StatCard label="Calibrated score" value={scoreToPercent(report.calibrated_score)} />
        <StatCard label="Final score" value={scoreToPercent(report.final_score)} tone={report.verdict} />
        <StatCard label="Threshold" value={scoreToPercent(report.threshold)} />
      </div>
      <div className="grid gap-6 xl:grid-cols-[1.3fr_1fr]">
        <Panel title="Signals" subtitle="Latest grouped signals for this URL.">
          <SignalGroups signals={report.signals} />
        </Panel>
        <Panel title="Decision trace" subtitle="Stored stage results for this URL.">
          <dl className="space-y-4 text-sm">
            <div>
              <dt className="text-slate-500">Final verdict</dt>
              <dd className="mt-1 text-white">{verdictLabel(report.verdict)}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Consistency status</dt>
              <dd className="mt-1 text-white">{consistencyStatusLabel(report.consistency_status ?? "consistent")}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Stage 1 pre-check</dt>
              <dd className="mt-1 text-white">{report.stage1_verdict ? verdictLabel(report.stage1_verdict) : "Not stored"}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Stage 2 full scan</dt>
              <dd className="mt-1 text-white">{report.stage2_verdict ? verdictLabel(report.stage2_verdict) : "Not stored"}</dd>
            </div>
          </dl>
        </Panel>
      </div>
      <Panel title="Feedback state" subtitle="Manual actions recorded for this URL.">
        {feedbackEvents.length === 0 ? (
          <div className="text-sm text-slate-500">No feedback recorded yet.</div>
        ) : (
          <div className="space-y-3 text-sm">
            {feedbackEvents.map((item) => (
                <div key={item.feedback_id} className="rounded-2xl border border-line/60 bg-white/5 p-3 text-slate-300">
                  <div className="font-medium text-white">{item.user_action.replaceAll("_", " ")}</div>
                  <div className="mt-1">{formatTimestamp(item.timestamp)}</div>
                </div>
              ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
