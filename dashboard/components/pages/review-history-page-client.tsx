"use client";

import { EmptyState } from "../empty-state";
import { Panel } from "../panel";
import { ScanTable } from "../scan-table";
import { useDashboardData } from "../../lib/dashboard-data";

export function ReviewHistoryPageClient({ deviceId }: { deviceId?: string }) {
  const { conflictingScans, deviceId: resolvedDeviceId } = useDashboardData(deviceId);

  return (
    <Panel
      title="Needs review"
      subtitle="Scans where Stage 1 looked safe but the full scan escalated enough to require a manual review state."
    >
      {conflictingScans.length === 0 ? (
        <EmptyState
          title="No conflicting scans"
          body="If Stage 1 and Stage 2 diverge sharply, the review state will appear here instead of forcing a hard malicious block."
        />
      ) : (
        <ScanTable rows={conflictingScans} deviceId={resolvedDeviceId} />
      )}
    </Panel>
  );
}
