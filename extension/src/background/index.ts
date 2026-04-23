import type {
  FeedbackQueueItem,
  LocalScanRecord,
  PrecheckResponse,
  TrustedDomainRecord,
  UserAction,
} from "@phishguard/shared";
import {
  buildDashboardReportUrl,
  getHostname,
  isRiskyVerdict,
  nowIso,
  normalizeUrlKey,
} from "@phishguard/shared";

import { addTrustedDomain, deleteTrustedDomain, postFeedback, postPrecheck, postScan } from "../lib/api";
import type { PageContentPayload, RuntimeMessage } from "../lib/messages";
import {
  addTrustedDomainLocal,
  appendScanHistory,
  buildLocalSnapshot,
  clearCacheForUrl,
  ensureStorageState,
  getDeviceId,
  getFeedbackQueue,
  getFreshCacheEntry,
  getLatestScanForUrl,
  getScanHistory,
  getSettings,
  getTrustedDomains,
  markManualDisposition,
  queueFeedback,
  recordFlaggedPhishing,
  recordSafeReportedAsPhishing,
  removeTrustedDomainLocal,
  saveSettings,
  updateFeedbackQueue,
  upsertCacheEntry,
} from "../lib/storage";

const ongoingScans = new Map<string, Promise<void>>();
const PRECHECK_FULL_SCAN_THRESHOLD = 0.25;

function emptySignals() {
  return {
    url_signals: [],
    content_signals: [],
    structural_signals: [],
    filter_signals: [],
  };
}

function buildPrecheckRecord(url: string, precheck: PrecheckResponse, deviceId: string): LocalScanRecord {
  return {
    stage: "precheck",
    scan_id: `local-${crypto.randomUUID()}`,
    url,
    title: "",
    verdict: precheck.stage1_verdict,
    final_verdict: precheck.stage1_verdict,
    raw_score: precheck.stage1_score,
    calibrated_score: precheck.stage1_score,
    final_score: precheck.stage1_score,
    threshold: PRECHECK_FULL_SCAN_THRESHOLD,
    signals: emptySignals(),
    filter_reason: precheck.reason,
    recommendation:
      precheck.stage1_verdict === "safe"
        ? "Continue browsing. Stage 1 did not find enough risk to trigger a full scan."
        : "The URL triggered a fast lexical review before full content analysis.",
    timestamp: precheck.timestamp,
    architecture: "non_visual_multimodal_fusion",
    source: "browser_extension_precheck",
    device_id: deviceId,
    synced: false,
    stage1_verdict: precheck.stage1_verdict,
    stage1_score: precheck.stage1_score,
    stage1_reason: precheck.reason,
    consistency_status: "consistent",
    consistency_reason: "precheck_only",
  };
}

function isDashboardOrApiUrl(url: string, apiBaseUrl: string, dashboardBaseUrl: string): boolean {
  try {
    const page = new URL(url);
    const api = new URL(apiBaseUrl);
    const dashboard = new URL(dashboardBaseUrl);
    const origins = new Set<string>([api.origin, dashboard.origin]);
    if (api.port === "8000") {
      origins.add(`http://127.0.0.1:${api.port}`);
      origins.add(`http://localhost:${api.port}`);
    }
    if (dashboard.port === "3000") {
      origins.add(`http://127.0.0.1:${dashboard.port}`);
      origins.add(`http://localhost:${dashboard.port}`);
    }
    return origins.has(page.origin);
  } catch {
    return false;
  }
}

function isScannableUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

async function sendTabMessage(tabId: number, message: RuntimeMessage): Promise<unknown> {
  return chrome.tabs.sendMessage(tabId, message);
}

async function requestPageContent(
  tabId: number,
  maxVisibleTextChars: number,
  maxRawHtmlChars: number,
  readyTimeoutMs: number,
  stabilityDelayMs: number,
  stabilityTimeoutMs: number,
): Promise<PageContentPayload> {
  const response = (await sendTabMessage(tabId, {
    type: "REQUEST_PAGE_CONTENT",
    payload: {
      maxVisibleTextChars,
      maxRawHtmlChars,
      readyTimeoutMs,
      stabilityDelayMs,
      stabilityTimeoutMs,
    },
  })) as PageContentPayload | undefined;

  if (!response) {
    throw new Error("PhishGuard could not read page content from the current tab.");
  }
  return response;
}

function logScanConflict(record: LocalScanRecord) {
  if (record.consistency_status !== "conflict") {
    return;
  }

  console.warn("[PhishGuard] Stage conflict detected", {
    url: record.url,
    stage1_verdict: record.stage1_verdict,
    stage2_verdict: record.stage2_verdict,
    raw_score: record.raw_score,
    calibrated_score: record.calibrated_score,
    final_score: record.final_score,
    threshold: record.threshold,
    filter_reason: record.filter_reason,
    signals: record.signals,
    consistency_status: record.consistency_status,
  });
}

async function showSafeIndicator(tabId: number, record: LocalScanRecord, reason: string) {
  const settings = await getSettings();
  await sendTabMessage(tabId, { type: "CLEAR_PAGE_UI" });
  if (!settings.showSafeIndicator) {
    return;
  }
  const score = record.verdict === "safe" ? Math.min(record.final_score, 0.12) : record.final_score;
  await sendTabMessage(tabId, {
    type: "SHOW_SAFE_INDICATOR",
    payload: {
      url: record.url,
      verdict: record.verdict,
      score,
      reason,
    },
  });
}

async function showOverlay(tabId: number, scan: LocalScanRecord) {
  const settings = await getSettings();
  await sendTabMessage(tabId, {
    type: "SHOW_OVERLAY",
    payload: {
      scan,
      allowContinueOnMalicious: settings.allowContinueOnMalicious,
    },
  });
}

async function openDashboard(url: string, scanId?: string) {
  const settings = await getSettings();
  const deviceId = await getDeviceId();
  const dashboardUrl = buildDashboardReportUrl(settings.dashboardBaseUrl, scanId, url, deviceId);
  await chrome.tabs.create({ url: dashboardUrl });
}

async function syncFeedback(queueItem: FeedbackQueueItem) {
  try {
    await postFeedback({
      scan_id: queueItem.scan_id,
      url: queueItem.url,
      user_action: queueItem.user_action,
      previous_verdict: queueItem.previous_verdict,
      notes: queueItem.notes,
      timestamp: queueItem.timestamp,
      source: queueItem.source,
      device_id: queueItem.device_id,
    });
    await updateFeedbackQueue(queueItem.feedback_id, {
      sync_status: "synced",
      retryCount: queueItem.retryCount,
      lastAttemptAt: nowIso(),
    });
  } catch {
    await updateFeedbackQueue(queueItem.feedback_id, {
      sync_status: "pending",
      retryCount: queueItem.retryCount + 1,
      lastAttemptAt: nowIso(),
    });
  }
}

async function flushPendingFeedback() {
  const queue = await getFeedbackQueue();
  for (const item of queue.filter((entry) => entry.sync_status !== "synced")) {
    await syncFeedback(item);
  }
}

async function handleManualAction(
  tabId: number | undefined,
  action: UserAction,
  url: string,
  scan?: LocalScanRecord,
) {
  if (!scan) {
    return;
  }

  const deviceId = await getDeviceId();
  const queued = await queueFeedback({
    scan_id: scan.scan_id,
    url,
    user_action: action,
    previous_verdict: scan.verdict,
    notes: "",
    timestamp: nowIso(),
    source: "browser_extension",
    device_id: deviceId,
  });
  await syncFeedback(queued);

  if (action === "report_phishing" && scan.verdict === "safe") {
    await recordSafeReportedAsPhishing({
      scanId: scan.scan_id,
      url,
      originalVerdict: "safe",
      currentFeedbackStatus: "reported_phishing",
      finalVerdict: scan.verdict,
      consistencyStatus: scan.consistency_status,
      notes: "",
      timestamp: nowIso(),
      source: "browser_extension",
      deviceId,
    });
  }

  if (action === "mark_safe") {
    await markManualDisposition(url, "marked_safe");
  }
  if (action === "continue_browsing") {
    await markManualDisposition(url, "continued");
  }
  if (tabId && (action === "mark_safe" || action === "continue_browsing")) {
    await sendTabMessage(tabId, { type: "CLEAR_PAGE_UI" });
    await showSafeIndicator(tabId, { ...scan, verdict: "safe" }, action);
  }
}

async function handleWhitelist(url: string, scan?: LocalScanRecord) {
  const deviceId = await getDeviceId();
  const hostname = getHostname(url);
  if (!hostname) {
    return;
  }
  const localRecord: TrustedDomainRecord = {
    domain: hostname,
    device_id: deviceId,
    added_at: nowIso(),
    source: "browser_extension",
    note: scan ? `Whitelisted from ${scan.verdict} review` : "Whitelisted from overlay",
  };
  await addTrustedDomainLocal(localRecord);
  try {
    await addTrustedDomain({
      domain: hostname,
      device_id: deviceId,
      source: "browser_extension",
      note: localRecord.note,
    });
  } catch {
    // Local-first whitelist stays available even if sync fails.
  }
  await markManualDisposition(url, "whitelisted");
}

async function resolveScanForUrl(url: string, scanId?: string): Promise<LocalScanRecord | undefined> {
  const history = await getScanHistory();
  if (scanId) {
    const byId = history.find((item) => item.scan_id === scanId);
    if (byId) {
      return byId;
    }
  }
  return history.find((item) => normalizeUrlKey(item.url) === normalizeUrlKey(url));
}

async function runTwoStageScan(tabId: number, url: string, title: string, force = false) {
  const scanKey = `${tabId}:${normalizeUrlKey(url)}`;
  if (ongoingScans.has(scanKey)) {
    return ongoingScans.get(scanKey);
  }

  const work = (async () => {
    const settings = await getSettings();
    if (!isScannableUrl(url) || isDashboardOrApiUrl(url, settings.apiBaseUrl, settings.dashboardBaseUrl)) {
      await sendTabMessage(tabId, { type: "CLEAR_PAGE_UI" });
      return;
    }

    if (!force) {
      const cached = await getFreshCacheEntry(url);
      if (cached) {
        const cachedScan = await getLatestScanForUrl(url);
        if (cached.manualDisposition || cached.verdict === "safe") {
          if (cachedScan) {
            await showSafeIndicator(tabId, { ...cachedScan, verdict: "safe" }, cached.manualDisposition ?? cached.reason);
          }
          return;
        }
        if (cachedScan) {
          await showOverlay(tabId, cachedScan);
          return;
        }
      }
    }

    const deviceId = await getDeviceId();
    let precheck: PrecheckResponse;
    try {
      precheck = await postPrecheck({
        url,
        hostname: getHostname(url),
        device_id: deviceId,
      });
    } catch (error) {
      await sendTabMessage(tabId, {
        type: "SHOW_SCAN_ERROR",
        payload: {
          message: error instanceof Error ? error.message : "Stage 1 precheck failed.",
        },
      });
      return;
    }

    if (!precheck.should_run_full_scan && !force) {
      const localRecord = buildPrecheckRecord(url, precheck, deviceId);
      await appendScanHistory(localRecord);
      await upsertCacheEntry(url, "safe", precheck.stage1_score, precheck.reason, "precheck", localRecord.scan_id);
      await showSafeIndicator(tabId, localRecord, precheck.reason);
      return;
    }

    try {
      const content = await requestPageContent(
        tabId,
        settings.maxVisibleTextChars,
        settings.maxRawHtmlChars,
        settings.contentReadyTimeoutMs,
        settings.contentStabilityDelayMs,
        settings.contentStabilityTimeoutMs,
      );
      const scan = await postScan({
        url,
        title: title || content.title,
        text_clean: content.text_clean,
        text_raw: content.text_raw,
        source: "browser_extension",
        device_id: deviceId,
        tab_id: tabId,
      });
      const record: LocalScanRecord = {
        ...scan,
        stage: scan.stage ?? "full_scan",
        source: "browser_extension",
        device_id: deviceId,
        tab_id: tabId,
        synced: true,
        final_verdict: scan.verdict,
        stage1_verdict: scan.stage1_verdict ?? precheck.stage1_verdict,
        stage1_score: scan.stage1_score ?? precheck.stage1_score,
        stage1_reason: scan.stage1_reason ?? precheck.reason,
        stage2_verdict: scan.stage2_verdict ?? (scan.verdict === "needs_review" ? "malicious" : scan.verdict),
        consistency_status: scan.consistency_status,
        consistency_reason: scan.consistency_reason,
      };
      logScanConflict(record);
      await appendScanHistory(record);
      await upsertCacheEntry(url, record.verdict, record.final_score, record.filter_reason, "full", record.scan_id);
      if (record.verdict === "malicious") {
        await recordFlaggedPhishing({
          scanId: record.scan_id,
          url: record.url,
          verdict: "malicious",
          score: record.final_score,
          reasons: record.signals.filter_signals.map((item) => item.label),
          stage1Verdict: record.stage1_verdict,
          stage2Verdict: record.stage2_verdict,
          finalVerdict: record.verdict,
          consistencyStatus: record.consistency_status,
          rawScore: record.raw_score,
          calibratedScore: record.calibrated_score,
          finalScore: record.final_score,
          threshold: record.threshold,
          filterReason: record.filter_reason,
          timestamp: record.timestamp,
          source: record.source,
          deviceId,
        });
      }
      if (isRiskyVerdict(record.verdict)) {
        await showOverlay(tabId, record);
      } else {
        await showSafeIndicator(tabId, record, record.filter_reason);
      }
    } catch (error) {
      await sendTabMessage(tabId, {
        type: "SHOW_SCAN_ERROR",
        payload: {
          message: error instanceof Error ? error.message : "Full scan failed.",
        },
      });
    }
  })()
    .finally(() => ongoingScans.delete(scanKey));

  ongoingScans.set(scanKey, work);
  return work;
}

chrome.runtime.onInstalled.addListener(() => {
  void ensureStorageState();
  void flushPendingFeedback();
});

chrome.runtime.onStartup.addListener(() => {
  void ensureStorageState();
  void flushPendingFeedback();
});

chrome.runtime.onMessage.addListener((message: RuntimeMessage, sender, sendResponse) => {
  void (async () => {
    if (message.type === "PAGE_READY") {
      if (sender.tab?.id) {
        await runTwoStageScan(sender.tab.id, message.payload.url, message.payload.title);
      }
      sendResponse({ ok: true });
      return;
    }

    if (message.type === "GET_CURRENT_SCAN") {
      const scan = await resolveScanForUrl(message.payload.url);
      sendResponse(scan ?? null);
      return;
    }

    if (message.type === "RESCAN_URL") {
      const tabId =
        sender.tab?.id ??
        (await chrome.tabs.query({ active: true, currentWindow: true })).find((tab) => tab.url === message.payload.url)?.id;
      if (tabId) {
        const settings = await getSettings();
        await clearCacheForUrl(message.payload.url);
        if (settings.rescanDebounceMs > 0) {
          await new Promise((resolve) => globalThis.setTimeout(resolve, settings.rescanDebounceMs));
        }
        await runTwoStageScan(tabId, message.payload.url, "", true);
      }
      sendResponse({ ok: true });
      return;
    }

    if (message.type === "OPEN_DASHBOARD") {
      await openDashboard(message.payload.url, message.payload.scanId);
      sendResponse({ ok: true });
      return;
    }

    if (message.type === "OVERLAY_ACTION") {
      const scan = await resolveScanForUrl(message.payload.url, message.payload.scanId);
      if (message.payload.action === "add_to_whitelist") {
        await handleWhitelist(message.payload.url, scan);
        if (scan) {
          await handleManualAction(sender.tab?.id, "add_to_whitelist", message.payload.url, scan);
        }
        if (sender.tab?.id) {
          await sendTabMessage(sender.tab.id, { type: "CLEAR_PAGE_UI" });
          if (scan) {
            await showSafeIndicator(sender.tab.id, { ...scan, verdict: "safe" }, "trusted_domain");
          }
        }
      } else {
        await handleManualAction(sender.tab?.id, message.payload.action, message.payload.url, scan);
      }
      if (message.payload.action === "report_phishing") {
        await openDashboard(message.payload.url, scan?.scan_id);
      }
      sendResponse({ ok: true });
      return;
    }

    if (message.type === "GET_SETTINGS") {
      sendResponse(await getSettings());
      return;
    }

    if (message.type === "SAVE_SETTINGS") {
      const saved = await saveSettings(message.payload);
      sendResponse(saved);
      return;
    }

    if (message.type === "GET_LOCAL_SNAPSHOT") {
      sendResponse(await buildLocalSnapshot());
      return;
    }
  })();

  return true;
});
