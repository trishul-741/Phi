import type { ConsistencyStatus, Verdict } from "./contracts";
import type { ExtensionSettings, ScanCacheEntry } from "./storage";

export const DEFAULT_EXTENSION_SETTINGS: ExtensionSettings = {
  apiBaseUrl: "http://127.0.0.1:8000",
  dashboardBaseUrl: "http://localhost:3000",
  safeCacheTtlMs: 30 * 60 * 1000,
  riskyCacheTtlMs: 5 * 60 * 1000,
  showSafeIndicator: true,
  allowContinueOnMalicious: false,
  rescanDebounceMs: 350,
  contentReadyTimeoutMs: 4000,
  contentStabilityDelayMs: 750,
  contentStabilityTimeoutMs: 3000,
  maxVisibleTextChars: 12000,
  maxRawHtmlChars: 60000,
};

export function normalizeUrlKey(url: string): string {
  try {
    const parsed = new URL(url);
    parsed.hash = "";
    return parsed.toString();
  } catch {
    return url.trim().toLowerCase();
  }
}

export function getHostname(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return "";
  }
}

export function getDomainLabel(url: string): string {
  const hostname = getHostname(url);
  return hostname || url;
}

export function scoreToPercent(score: number): string {
  return `${Math.round(score * 100)}%`;
}

export function verdictLabel(verdict: Verdict): string {
  if (verdict === "safe") {
    return "Safe";
  }
  if (verdict === "suspicious") {
    return "Suspicious";
  }
  if (verdict === "needs_review") {
    return "Needs Review";
  }
  return "Malicious";
}

export function verdictAccent(verdict: Verdict): string {
  if (verdict === "safe") {
    return "emerald";
  }
  if (verdict === "suspicious") {
    return "amber";
  }
  if (verdict === "needs_review") {
    return "sky";
  }
  return "red";
}

export function isRiskyVerdict(verdict: Verdict): boolean {
  return verdict === "suspicious" || verdict === "malicious" || verdict === "needs_review";
}

export function isBlockingVerdict(verdict: Verdict): boolean {
  return verdict === "malicious";
}

export function consistencyStatusLabel(status: ConsistencyStatus): string {
  return status === "conflict" ? "Conflict detected" : "Consistent";
}

export function buildDashboardReportUrl(
  dashboardBaseUrl: string,
  scanId?: string,
  url?: string,
  deviceId?: string,
): string {
  if (scanId) {
    const reportUrl = new URL(`/report/${scanId}`, dashboardBaseUrl);
    if (deviceId) {
      reportUrl.searchParams.set("device_id", deviceId);
    }
    return reportUrl.toString();
  }

  const fallback = new URL("/report/url", dashboardBaseUrl);
  if (url) {
    fallback.searchParams.set("url", url);
  }
  if (deviceId) {
    fallback.searchParams.set("device_id", deviceId);
  }
  return fallback.toString();
}

export function getCacheTtlMs(verdict: Verdict, settings: ExtensionSettings): number {
  return verdict === "safe" ? settings.safeCacheTtlMs : settings.riskyCacheTtlMs;
}

export function isCacheEntryFresh(entry: ScanCacheEntry | undefined, now = Date.now()): boolean {
  if (!entry) {
    return false;
  }
  return new Date(entry.expiresAt).getTime() > now;
}

export function formatTimestamp(iso: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export function nowIso(): string {
  return new Date().toISOString();
}
