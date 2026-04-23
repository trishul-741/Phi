"use client";

import { SignalBarChart, TrendChart } from "../analytics-chart";
import { EmptyState } from "../empty-state";
import { Panel } from "../panel";
import { StatCard } from "../stat-card";
import { useDashboardData } from "../../lib/dashboard-data";

export function AnalyticsPageClient({ deviceId }: { deviceId?: string }) {
  const { analytics } = useDashboardData(deviceId);

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
        <StatCard label="Total scans" value={analytics.totals.total} />
        <StatCard label="Safe" value={analytics.totals.safe} tone="safe" />
        <StatCard label="Suspicious" value={analytics.totals.suspicious} tone="suspicious" />
        <StatCard label="Needs review" value={analytics.totals.needsReview} tone="needs_review" />
        <StatCard label="Malicious" value={analytics.totals.malicious} tone="malicious" />
        <StatCard label="Feedback" value={analytics.totals.feedback} />
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Risk trend" subtitle="Daily distribution of safe, suspicious, needs-review, and malicious outcomes.">
          {analytics.trend.length === 0 ? <EmptyState title="No trend data" body="Scans will populate the chart automatically." /> : <TrendChart data={analytics.trend} />}
        </Panel>

        <Panel title="Top triggered signals" subtitle="Most frequent grouped signals across recent scans.">
          {analytics.topSignals.length === 0 ? (
            <EmptyState title="No signal data" body="Triggered signals will appear after scans are stored." />
          ) : (
            <SignalBarChart data={analytics.topSignals} />
          )}
        </Panel>
      </div>
    </div>
  );
}
