"use client";

import { consistencyStatusLabel, formatTimestamp, scoreToPercent, verdictLabel } from "@phishguard/shared";

import { EmptyState } from "../empty-state";
import { Panel } from "../panel";
import { SignalGroups } from "../signal-groups";
import { StatCard } from "../stat-card";
import { StatusPill } from "../status-pill";
import { useScanReport } from "../../lib/report-hooks";

export function ReportPageClient({
  scanId,
  deviceId,
}: {
  scanId: string;
  deviceId?: string;
}) {
  const { report, loading, bridgeAvailable, feedbackEvents } = useScanReport(scanId, deviceId);

  if (loading) {
    return <div className="text-slate-400">Loading report...</div>;
  }

  if (!report) {
    return (
      <EmptyState
        title="Report not found"
        body="The scan was not available in local extension storage or the synced backend history."
      />
    );
  }

  return (
    <div className="space-y-6">
      <section className="rounded-[32px] border border-line/70 bg-surface/85 p-6 shadow-glow">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-accent">Detailed scan report</div>
            <h1 className="mt-2 text-3xl font-semibold text-white">{report.url}</h1>
            <p className="mt-2 text-sm text-slate-400">
              Architecture: {report.architecture} {bridgeAvailable ? "- local bridge available" : "- backend view"}
            </p>
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

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Panel title="Signals" subtitle="Grouped non-visual signals from URL, content, structural, and safe-filter analysis.">
          <SignalGroups signals={report.signals} />
        </Panel>

        <Panel title="Decision trace" subtitle="Stage-by-stage review showing how the final decision was shaped.">
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
              <dd className="mt-1 text-white">
                {report.stage1_verdict ? verdictLabel(report.stage1_verdict) : "Not stored"}
                {typeof report.stage1_score === "number" ? ` - ${scoreToPercent(report.stage1_score)}` : ""}
              </dd>
              {report.stage1_reason ? <dd className="mt-1 text-slate-400">{report.stage1_reason}</dd> : null}
            </div>
            <div>
              <dt className="text-slate-500">Stage 2 full scan</dt>
              <dd className="mt-1 text-white">{report.stage2_verdict ? verdictLabel(report.stage2_verdict) : "Not stored"}</dd>
            </div>
            {report.consistency_reason ? (
              <div>
                <dt className="text-slate-500">Consistency reason</dt>
                <dd className="mt-1 text-white">{report.consistency_reason.replaceAll("_", " ")}</dd>
              </div>
            ) : null}
          </dl>
        </Panel>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <Panel title="Report metadata" subtitle="Stored fields returned by the backend inference path.">
          <dl className="space-y-4 text-sm">
            <div>
              <dt className="text-slate-500">Timestamp</dt>
              <dd className="mt-1 text-white">{formatTimestamp(report.timestamp)}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Filter reason</dt>
              <dd className="mt-1 text-white">{report.filter_reason}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Recommendation</dt>
              <dd className="mt-1 text-white">{report.recommendation}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Source</dt>
              <dd className="mt-1 text-white">{report.source}</dd>
            </div>
          </dl>
        </Panel>

        <Panel title="Feedback state" subtitle="Manual actions already recorded for this scan or URL.">
          {feedbackEvents.length === 0 ? (
            <div className="text-sm text-slate-500">No manual feedback recorded yet.</div>
          ) : (
            <div className="space-y-3 text-sm">
              {feedbackEvents.map((item) => (
                <div key={item.feedback_id} className="rounded-2xl border border-line/60 bg-white/5 p-3">
                  <div className="font-medium text-white">{item.user_action.replaceAll("_", " ")}</div>
                  <div className="mt-1 text-slate-400">Previous verdict: {verdictLabel(item.previous_verdict)}</div>
                  <div className="mt-1 text-slate-400">{formatTimestamp(item.timestamp)}</div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
