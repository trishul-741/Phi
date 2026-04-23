"use client";

import { EmptyState } from "../empty-state";
import { Panel } from "../panel";
import { ScanTable } from "../scan-table";
import { useDashboardData } from "../../lib/dashboard-data";

export function PhishingHistoryPageClient({ deviceId }: { deviceId?: string }) {
  const { flaggedPhishingUrls, deviceId: resolvedDeviceId } = useDashboardData(deviceId);

  return (
    <Panel
      title="Local phishing history"
      subtitle="All URLs flagged as phishing on this device whenever they were visited."
    >
      {flaggedPhishingUrls.length === 0 ? (
        <EmptyState
          title="No phishing history yet"
          body="Malicious detections from the extension will appear here once pages are scanned."
        />
      ) : (
        <ScanTable rows={flaggedPhishingUrls} deviceId={resolvedDeviceId} />
      )}
    </Panel>
  );
}
