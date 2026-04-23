"use client";

import type { ScanRecord } from "@phishguard/shared";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchReport, fetchReportByUrl } from "./api";
import { useDashboardData } from "./dashboard-data";

export function useScanReport(scanId: string, deviceId?: string) {
  const data = useDashboardData(deviceId);
  const localMatch = useMemo(
    () => data.scans.find((scan) => scan.scan_id === scanId),
    [data.scans, scanId],
  );
  const feedbackEvents = useMemo(
    () =>
      data.feedback.filter((item) => item.scan_id === scanId || (localMatch ? item.url === localMatch.url : false)),
    [data.feedback, localMatch, scanId],
  );

  const query = useQuery({
    queryKey: ["report", scanId],
    queryFn: () => fetchReport(scanId),
    enabled: !localMatch,
  });

  return {
    report: (localMatch as ScanRecord | undefined) ?? query.data,
    loading: data.loading || query.isLoading,
    bridgeAvailable: data.bridgeAvailable,
    feedbackEvents,
  };
}

export function useScanReportByUrl(url: string, deviceId?: string) {
  const data = useDashboardData(deviceId);
  const localMatch = useMemo(
    () => data.scans.find((scan) => scan.url === url),
    [data.scans, url],
  );
  const feedbackEvents = useMemo(
    () =>
      data.feedback.filter((item) => item.url === url || (localMatch ? item.scan_id === localMatch.scan_id : false)),
    [data.feedback, localMatch, url],
  );

  const query = useQuery({
    queryKey: ["report-by-url", url, deviceId],
    queryFn: () => fetchReportByUrl(url, deviceId),
    enabled: Boolean(url) && !localMatch,
  });

  return {
    report: (localMatch as ScanRecord | undefined) ?? query.data,
    loading: data.loading || query.isLoading,
    bridgeAvailable: data.bridgeAvailable,
    feedbackEvents,
  };
}
