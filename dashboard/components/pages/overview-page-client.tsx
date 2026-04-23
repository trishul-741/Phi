"use client";

import { scoreToPercent, verdictLabel } from "@phishguard/shared";

import { EmptyState } from "../empty-state";
import { Panel } from "../panel";
import { QuickPrecheckCard } from "../quick-precheck-card";
import { ScanTable } from "../scan-table";
import { StatCard } from "../stat-card";
import { useDashboardData } from "../../lib/dashboard-data";

export function OverviewPageClient({ deviceId }: { deviceId?: string }) {
  const { analytics, bridgeAvailable, scans, deviceId: resolvedDeviceId } = useDashboardData(deviceId);

  const recent = scans.slice(0, 8);

  return (
    <div className="space-y-6">
      <section className="rounded-[32px] border border-line/70 bg-surface/85 p-6 shadow-glow">
        <div className="text-xs uppercase tracking-[0.24em] text-accent">PhishGuard Dashboard</div>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight text-white">Device-scoped phishing telemetry</h1>
        <p className="mt-3 max-w-3xl text-sm text-slate-400">
          Review URL, content, structural, calibration, and safe-filter outcomes for the current device. No screenshot,
          OCR, or visual-model branch is used anywhere in this workflow.
        </p>
        <div className="mt-4 text-xs uppercase tracking-[0.16em] text-slate-500">
          {bridgeAvailable
            ? `Local extension bridge active${resolvedDeviceId ? ` - ${resolvedDeviceId}` : ""}`
            : "Showing synced backend records"}
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
        <StatCard label="Total scans" value={analytics.totals.total} />
        <StatCard label="Safe" value={analytics.totals.safe} tone="safe" />
        <StatCard label="Suspicious" value={analytics.totals.suspicious} tone="suspicious" />
        <StatCard label="Needs review" value={analytics.totals.needsReview} tone="needs_review" />
        <StatCard label="Malicious" value={analytics.totals.malicious} tone="malicious" />
        <StatCard label="Feedback events" value={analytics.totals.feedback} />
      </div>

      <QuickPrecheckCard deviceId={resolvedDeviceId} />

      <div className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
        <Panel
          title="Recent activity"
          subtitle="Latest page visits processed by the extension or already synced from the backend."
        >
          {recent.length === 0 ? (
            <EmptyState
              title="No scan activity yet"
              body="Load the extension on a few pages or sync backend history to populate the dashboard."
            />
          ) : (
            <ScanTable rows={recent} deviceId={resolvedDeviceId} />
          )}
        </Panel>

        <Panel title="Recent risk activity" subtitle="Most recent suspicious or malicious outcomes.">
          <div className="space-y-3">
            {scans.filter((scan) => scan.verdict !== "safe").slice(0, 5).map((scan) => (
              <div key={scan.scan_id} className="rounded-[22px] border border-line/70 bg-white/5 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{verdictLabel(scan.verdict)}</div>
                <div className="mt-2 break-all text-sm font-semibold text-white">{scan.url}</div>
                <div className="mt-2 text-sm text-slate-400">
                  Score {scoreToPercent(scan.final_score)} - {scan.filter_reason.replaceAll("_", " ")}
                </div>
              </div>
            ))}
            {scans.every((scan) => scan.verdict === "safe") && (
              <EmptyState
                title="No elevated risk"
                body="Recent visits are currently staying below the action threshold."
              />
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}
