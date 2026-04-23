"use client";

import type {
  FeedbackEvent,
  FlaggedPhishingRecord,
  LocalScanRecord,
  SafeReportedAsPhishingRecord,
  ScanRecord,
  TrustedDomainRecord,
} from "@phishguard/shared";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchFeedback, fetchHistory, fetchWhitelist } from "./api";
import { useExtensionSnapshot } from "./bridge";

function dedupeBy<T>(items: T[], getKey: (item: T) => string): T[] {
  const seen = new Set<string>();
  const result: T[] = [];
  for (const item of items) {
    const key = getKey(item);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(item);
  }
  return result;
}

function deriveFlaggedFromScans(scans: LocalScanRecord[]): FlaggedPhishingRecord[] {
  return scans
    .filter((scan) => scan.verdict === "malicious")
    .map((scan) => ({
      scanId: scan.scan_id,
      url: scan.url,
      verdict: "malicious",
      score: scan.final_score,
      reasons: scan.signals.filter_signals.map((item) => item.label),
      stage1Verdict: scan.stage1_verdict,
      stage2Verdict: scan.stage2_verdict,
      finalVerdict: scan.verdict,
      consistencyStatus: scan.consistency_status,
      rawScore: scan.raw_score,
      calibratedScore: scan.calibrated_score,
      finalScore: scan.final_score,
      threshold: scan.threshold,
      filterReason: scan.filter_reason,
      timestamp: scan.timestamp,
      source: scan.source,
      deviceId: scan.device_id,
    }));
}

function deriveSafeReported(
  feedback: FeedbackEvent[],
  scans: LocalScanRecord[],
): SafeReportedAsPhishingRecord[] {
  return feedback
    .filter((item) => item.user_action === "report_phishing" && item.previous_verdict === "safe")
    .map((item) => {
      const scan = scans.find((candidate) => candidate.scan_id === item.scan_id) ?? scans.find((candidate) => candidate.url === item.url);
      return {
        scanId: item.scan_id,
        url: item.url,
        originalVerdict: "safe",
        currentFeedbackStatus: "reported_phishing",
        finalVerdict: scan?.verdict,
        consistencyStatus: scan?.consistency_status,
        notes: item.notes,
        timestamp: item.timestamp,
        source: item.source,
        deviceId: scan?.device_id,
      };
    });
}

function mergeTrustedDomains(snapshotDomains: TrustedDomainRecord[], backendDomains: TrustedDomainRecord[]) {
  return dedupeBy([...snapshotDomains, ...backendDomains], (item) => `${item.device_id ?? "device"}:${item.domain}`);
}

export function useDashboardData(deviceId?: string) {
  const { snapshot, bridgeAvailable } = useExtensionSnapshot();

  const effectiveDeviceId = deviceId ?? snapshot?.deviceId;

  const historyQuery = useQuery({
    queryKey: ["history", effectiveDeviceId],
    queryFn: () => fetchHistory(effectiveDeviceId),
  });
  const feedbackQuery = useQuery({
    queryKey: ["feedback", effectiveDeviceId],
    queryFn: () => fetchFeedback(effectiveDeviceId),
  });
  const whitelistQuery = useQuery({
    queryKey: ["whitelist", effectiveDeviceId],
    queryFn: () => fetchWhitelist(effectiveDeviceId),
  });

  const scans = useMemo<LocalScanRecord[]>(() => {
    if (snapshot?.scanHistory?.length) {
      return snapshot.scanHistory;
    }
    return historyQuery.data?.items ?? [];
  }, [historyQuery.data?.items, snapshot?.scanHistory]);

  const feedback = feedbackQuery.data ?? [];

  const flaggedPhishingUrls = useMemo<FlaggedPhishingRecord[]>(() => {
    if (snapshot?.flaggedPhishingUrls?.length) {
      return snapshot.flaggedPhishingUrls;
    }
    return deriveFlaggedFromScans(scans);
  }, [scans, snapshot?.flaggedPhishingUrls]);

  const safeReportedAsPhishing = useMemo<SafeReportedAsPhishingRecord[]>(() => {
    if (snapshot?.safeReportedAsPhishing?.length) {
      return snapshot.safeReportedAsPhishing;
    }
    return deriveSafeReported(feedback, scans);
  }, [feedback, scans, snapshot?.safeReportedAsPhishing]);

  const conflictingScans = useMemo<LocalScanRecord[]>(() => {
    return scans.filter((scan) => scan.verdict === "needs_review" || scan.consistency_status === "conflict");
  }, [scans]);

  const trustedDomains = useMemo<TrustedDomainRecord[]>(() => {
    return mergeTrustedDomains(snapshot?.trustedDomains ?? [], whitelistQuery.data?.items ?? []);
  }, [snapshot?.trustedDomains, whitelistQuery.data?.items]);

  const analytics = useMemo(() => {
    const totals = {
      total: scans.length,
      safe: scans.filter((item) => item.verdict === "safe").length,
      suspicious: scans.filter((item) => item.verdict === "suspicious").length,
      needsReview: scans.filter((item) => item.verdict === "needs_review").length,
      malicious: scans.filter((item) => item.verdict === "malicious").length,
      feedback: (snapshot?.userFeedbackQueue?.length ?? 0) || feedback.length,
    };

    const signalFrequency = new Map<string, number>();
    for (const scan of scans) {
      const signals = [
        ...scan.signals.url_signals,
        ...scan.signals.content_signals,
        ...scan.signals.structural_signals,
        ...scan.signals.filter_signals,
      ];
      for (const signal of signals) {
        signalFrequency.set(signal.label, (signalFrequency.get(signal.label) ?? 0) + 1);
      }
    }

    const topSignals = [...signalFrequency.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([name, count]) => ({ name, count }));

    const trendMap = new Map<string, { safe: number; suspicious: number; needs_review: number; malicious: number }>();
    for (const scan of scans) {
      const key = new Date(scan.timestamp).toISOString().slice(0, 10);
      const bucket = trendMap.get(key) ?? { safe: 0, suspicious: 0, needs_review: 0, malicious: 0 };
      if (scan.verdict === "safe") {
        bucket.safe += 1;
      } else if (scan.verdict === "suspicious") {
        bucket.suspicious += 1;
      } else if (scan.verdict === "needs_review") {
        bucket.needs_review += 1;
      } else {
        bucket.malicious += 1;
      }
      trendMap.set(key, bucket);
    }
    const trend = [...trendMap.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .slice(-10)
      .map(([date, values]) => ({ date, ...values }));

    return { totals, topSignals, trend };
  }, [feedback.length, scans, snapshot?.userFeedbackQueue?.length]);

  return {
    bridgeAvailable,
    snapshot,
    deviceId: effectiveDeviceId,
    scans,
    feedback: snapshot?.userFeedbackQueue?.length ? snapshot.userFeedbackQueue : feedback,
    trustedDomains,
    flaggedPhishingUrls,
    safeReportedAsPhishing,
    conflictingScans,
    analytics,
    loading: historyQuery.isLoading || feedbackQuery.isLoading || whitelistQuery.isLoading,
    queries: {
      history: historyQuery,
      feedback: feedbackQuery,
      whitelist: whitelistQuery,
    },
  };
}
