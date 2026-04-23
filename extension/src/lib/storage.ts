import type {
  ExtensionSettings,
  ExtensionStorageState,
  FeedbackQueueItem,
  FlaggedPhishingRecord,
  LocalDashboardSnapshot,
  LocalScanRecord,
  SafeReportedAsPhishingRecord,
  ScanCacheEntry,
  TrustedDomainRecord,
  Verdict,
} from "@phishguard/shared";
import {
  DEFAULT_EXTENSION_SETTINGS,
  getCacheTtlMs,
  isCacheEntryFresh,
  normalizeUrlKey,
  nowIso,
} from "@phishguard/shared";

const STORAGE_KEYS = [
  "scanHistory",
  "flaggedPhishingUrls",
  "safeReportedAsPhishing",
  "userFeedbackQueue",
  "trustedDomains",
  "scanCache",
  "settings",
  "deviceId",
] as const;

function storageGet<T>(keys: string[] | string): Promise<T> {
  return chrome.storage.local.get(keys) as Promise<T>;
}

function storageSet(value: object): Promise<void> {
  return chrome.storage.local.set(value);
}

export async function ensureStorageState(): Promise<ExtensionStorageState> {
  const current = (await storageGet<Record<string, unknown>>(STORAGE_KEYS as unknown as string[])) || {};
  const nextState: ExtensionStorageState = {
    scanHistory: Array.isArray(current.scanHistory) ? (current.scanHistory as LocalScanRecord[]) : [],
    flaggedPhishingUrls: Array.isArray(current.flaggedPhishingUrls)
      ? (current.flaggedPhishingUrls as FlaggedPhishingRecord[])
      : [],
    safeReportedAsPhishing: Array.isArray(current.safeReportedAsPhishing)
      ? (current.safeReportedAsPhishing as SafeReportedAsPhishingRecord[])
      : [],
    userFeedbackQueue: Array.isArray(current.userFeedbackQueue)
      ? (current.userFeedbackQueue as FeedbackQueueItem[])
      : [],
    trustedDomains: Array.isArray(current.trustedDomains)
      ? (current.trustedDomains as TrustedDomainRecord[])
      : [],
    scanCache:
      current.scanCache && typeof current.scanCache === "object"
        ? (current.scanCache as Record<string, ScanCacheEntry>)
        : {},
    settings:
      current.settings && typeof current.settings === "object"
        ? ({ ...DEFAULT_EXTENSION_SETTINGS, ...(current.settings as Partial<ExtensionSettings>) })
        : DEFAULT_EXTENSION_SETTINGS,
    deviceId:
      typeof current.deviceId === "string" && current.deviceId.length > 0
        ? current.deviceId
        : crypto.randomUUID(),
  };

  await storageSet(nextState);
  return nextState;
}

export async function getSettings(): Promise<ExtensionSettings> {
  return (await ensureStorageState()).settings;
}

export async function saveSettings(settings: ExtensionSettings): Promise<ExtensionSettings> {
  await ensureStorageState();
  await storageSet({ settings });
  return settings;
}

export async function getDeviceId(): Promise<string> {
  return (await ensureStorageState()).deviceId;
}

export async function getScanHistory(): Promise<LocalScanRecord[]> {
  return (await ensureStorageState()).scanHistory;
}

export async function getLatestScanForUrl(url: string): Promise<LocalScanRecord | undefined> {
  const normalized = normalizeUrlKey(url);
  const scanHistory = await getScanHistory();
  return scanHistory.find((record) => normalizeUrlKey(record.url) === normalized);
}

export async function appendScanHistory(record: LocalScanRecord): Promise<void> {
  const state = await ensureStorageState();
  const nextHistory = [record, ...state.scanHistory.filter((item) => item.scan_id !== record.scan_id)].slice(0, 250);
  await storageSet({ scanHistory: nextHistory });
}

export async function upsertCacheEntry(
  url: string,
  verdict: Verdict,
  finalScore: number,
  reason: string,
  stage: "precheck" | "full",
  scanId: string | undefined,
  manualDisposition?: ScanCacheEntry["manualDisposition"],
): Promise<ScanCacheEntry> {
  const state = await ensureStorageState();
  const normalizedUrl = normalizeUrlKey(url);
  const entry: ScanCacheEntry = {
    url,
    normalizedUrl,
    verdict,
    finalScore,
    reason,
    stage,
    scanId,
    manualDisposition,
    cachedAt: nowIso(),
    expiresAt: new Date(Date.now() + getCacheTtlMs(verdict, state.settings)).toISOString(),
  };
  await storageSet({
    scanCache: {
      ...state.scanCache,
      [normalizedUrl]: entry,
    },
  });
  return entry;
}

export async function getFreshCacheEntry(url: string): Promise<ScanCacheEntry | undefined> {
  const state = await ensureStorageState();
  const normalizedUrl = normalizeUrlKey(url);
  const entry = state.scanCache[normalizedUrl];
  if (!isCacheEntryFresh(entry)) {
    if (entry) {
      const nextCache = { ...state.scanCache };
      delete nextCache[normalizedUrl];
      await storageSet({ scanCache: nextCache });
    }
    return undefined;
  }
  return entry;
}

export async function clearCacheForUrl(url: string): Promise<void> {
  const state = await ensureStorageState();
  const normalizedUrl = normalizeUrlKey(url);
  if (!state.scanCache[normalizedUrl]) {
    return;
  }
  const nextCache = { ...state.scanCache };
  delete nextCache[normalizedUrl];
  await storageSet({ scanCache: nextCache });
}

export async function markManualDisposition(
  url: string,
  manualDisposition: ScanCacheEntry["manualDisposition"],
): Promise<void> {
  const state = await ensureStorageState();
  const normalizedUrl = normalizeUrlKey(url);
  const current = state.scanCache[normalizedUrl];
  if (!current) {
    return;
  }
  await storageSet({
    scanCache: {
      ...state.scanCache,
      [normalizedUrl]: {
        ...current,
        manualDisposition,
        expiresAt: new Date(Date.now() + state.settings.riskyCacheTtlMs).toISOString(),
      },
    },
  });
}

export async function recordFlaggedPhishing(record: FlaggedPhishingRecord): Promise<void> {
  const state = await ensureStorageState();
  const nextItems = [
    record,
    ...state.flaggedPhishingUrls.filter((item) => item.scanId !== record.scanId),
  ].slice(0, 250);
  await storageSet({ flaggedPhishingUrls: nextItems });
}

export async function recordSafeReportedAsPhishing(record: SafeReportedAsPhishingRecord): Promise<void> {
  const state = await ensureStorageState();
  const nextItems = [
    record,
    ...state.safeReportedAsPhishing.filter((item) => item.scanId !== record.scanId),
  ].slice(0, 250);
  await storageSet({ safeReportedAsPhishing: nextItems });
}

export async function queueFeedback(item: Omit<FeedbackQueueItem, "feedback_id" | "sync_status" | "retryCount">): Promise<FeedbackQueueItem> {
  const state = await ensureStorageState();
  const queuedItem: FeedbackQueueItem = {
    ...item,
    feedback_id: crypto.randomUUID(),
    retryCount: 0,
    sync_status: "pending",
  };
  await storageSet({
    userFeedbackQueue: [queuedItem, ...state.userFeedbackQueue].slice(0, 500),
  });
  return queuedItem;
}

export async function updateFeedbackQueue(
  feedbackId: string,
  patch: Partial<FeedbackQueueItem>,
): Promise<void> {
  const state = await ensureStorageState();
  await storageSet({
    userFeedbackQueue: state.userFeedbackQueue.map((item) =>
      item.feedback_id === feedbackId ? { ...item, ...patch } : item,
    ),
  });
}

export async function getFeedbackQueue(): Promise<FeedbackQueueItem[]> {
  return (await ensureStorageState()).userFeedbackQueue;
}

export async function getTrustedDomains(): Promise<TrustedDomainRecord[]> {
  return (await ensureStorageState()).trustedDomains;
}

export async function addTrustedDomainLocal(record: TrustedDomainRecord): Promise<void> {
  const state = await ensureStorageState();
  const normalized = record.domain.toLowerCase();
  const nextItems = [
    { ...record, domain: normalized },
    ...state.trustedDomains.filter((item) => item.domain.toLowerCase() !== normalized),
  ].slice(0, 250);
  await storageSet({ trustedDomains: nextItems });
}

export async function removeTrustedDomainLocal(domain: string): Promise<void> {
  const state = await ensureStorageState();
  const target = domain.toLowerCase();
  await storageSet({
    trustedDomains: state.trustedDomains.filter((item) => item.domain.toLowerCase() !== target),
  });
}

export async function buildLocalSnapshot(): Promise<LocalDashboardSnapshot> {
  const state = await ensureStorageState();
  return {
    deviceId: state.deviceId,
    collectedAt: nowIso(),
    scanHistory: state.scanHistory,
    flaggedPhishingUrls: state.flaggedPhishingUrls,
    safeReportedAsPhishing: state.safeReportedAsPhishing,
    userFeedbackQueue: state.userFeedbackQueue,
    trustedDomains: state.trustedDomains,
    settings: state.settings,
  };
}
