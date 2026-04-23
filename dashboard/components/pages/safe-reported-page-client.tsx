"use client";

import { EmptyState } from "../empty-state";
import { Panel } from "../panel";
import { ScanTable } from "../scan-table";
import { useDashboardData } from "../../lib/dashboard-data";

export function SafeReportedPageClient({ deviceId }: { deviceId?: string }) {
  const { safeReportedAsPhishing, deviceId: resolvedDeviceId } = useDashboardData(deviceId);

  return (
    <Panel
      title="Safe but user-reported phishing"
      subtitle="Websites predicted safe by the system but manually reported by the user as phishing."
    >
      {safeReportedAsPhishing.length === 0 ? (
        <EmptyState
          title="No safe-but-reported cases"
          body="If a safe page is manually reported as phishing, the corrected record will appear here."
        />
      ) : (
        <ScanTable rows={safeReportedAsPhishing} deviceId={resolvedDeviceId} />
      )}
    </Panel>
  );
}
