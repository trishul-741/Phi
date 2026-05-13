import type { LocalDashboardSnapshot, LocalScanRecord, StageVerdict, UserAction, Verdict } from "@phishguard/shared";
import {
  formatTimestamp,
  getDomainLabel,
  isBlockingVerdict,
  scoreToPercent,
  verdictLabel,
} from "@phishguard/shared";
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import { ScanStageTrace } from "../components/ScanStageTrace";
import { SignalChips } from "../components/SignalChips";
import { VerdictBadge } from "../components/VerdictBadge";
import { extractRawHtml, extractVisibleText } from "../lib/extract";
import {
  DASHBOARD_SNAPSHOT_REQUEST,
  DASHBOARD_SNAPSHOT_RESPONSE,
  type PageContentPayload,
  type RuntimeMessage,
} from "../lib/messages";
import { buildLocalSnapshot, getSettings } from "../lib/storage";
import "../styles/base.css";

type OverlayAction = UserAction | "open_dashboard" | "rescan";

type UiState =
  | { mode: "idle" }
  | {
      mode: "indicator";
      reason: string;
      score: number;
      verdict: LocalScanRecord["verdict"];
    }
  | {
      mode: "overlay";
      scan: LocalScanRecord;
      allowContinueOnMalicious: boolean;
    }
  | {
      mode: "error";
      message: string;
    };

const overlayId = "phishguard-overlay-root";
let currentUrl = window.location.href;

function sendRuntimeMessage(message: RuntimeMessage) {
  return chrome.runtime.sendMessage(message);
}

function firePageReady() {
  currentUrl = window.location.href;
  void sendRuntimeMessage({
    type: "PAGE_READY",
    payload: {
      url: currentUrl,
      title: document.title,
    },
  });
}

function watchLocationChanges() {
  const trigger = () => {
    if (window.location.href !== currentUrl) {
      firePageReady();
    }
  };

  const originalPushState = history.pushState;
  const originalReplaceState = history.replaceState;

  history.pushState = function pushState(data: unknown, unused: string, url?: string | URL | null) {
    originalPushState.call(this, data, unused, url);
    window.setTimeout(trigger, 50);
  };

  history.replaceState = function replaceState(data: unknown, unused: string, url?: string | URL | null) {
    originalReplaceState.call(this, data, unused, url);
    window.setTimeout(trigger, 50);
  };

  window.addEventListener("popstate", trigger);
}

function waitForDocumentComplete(timeoutMs: number) {
  if (document.readyState === "complete" || timeoutMs <= 0) {
    return Promise.resolve();
  }

  return new Promise<void>((resolve) => {
    let settled = false;
    let timerId = 0;

    const finish = () => {
      if (settled) {
        return;
      }
      settled = true;
      window.clearTimeout(timerId);
      document.removeEventListener("readystatechange", onReadyStateChange);
      window.removeEventListener("load", finish);
      resolve();
    };

    const onReadyStateChange = () => {
      if (document.readyState === "complete") {
        finish();
      }
    };

    timerId = window.setTimeout(finish, timeoutMs);
    document.addEventListener("readystatechange", onReadyStateChange);
    window.addEventListener("load", finish, { once: true });
    onReadyStateChange();
  });
}

function waitForDomQuiet(quietWindowMs: number, timeoutMs: number) {
  if (quietWindowMs <= 0 || timeoutMs <= 0 || !document.documentElement) {
    return Promise.resolve();
  }

  return new Promise<void>((resolve) => {
    let quietTimer = 0;
    let timeoutTimer = 0;
    let settled = false;

    const observer = new MutationObserver(() => {
      window.clearTimeout(quietTimer);
      quietTimer = window.setTimeout(finish, quietWindowMs);
    });

    const finish = () => {
      if (settled) {
        return;
      }
      settled = true;
      observer.disconnect();
      window.clearTimeout(quietTimer);
      window.clearTimeout(timeoutTimer);
      resolve();
    };

    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
    });
    quietTimer = window.setTimeout(finish, quietWindowMs);
    timeoutTimer = window.setTimeout(finish, timeoutMs);
  });
}

async function waitForStablePage(
  readyTimeoutMs: number,
  stabilityDelayMs: number,
  stabilityTimeoutMs: number,
) {
  await waitForDocumentComplete(readyTimeoutMs);
  await waitForDomQuiet(stabilityDelayMs, stabilityTimeoutMs);
}

function overlayHeadline(scan: LocalScanRecord) {
  if (scan.verdict === "needs_review" || scan.consistency_status === "conflict") {
    return scan.stage2_verdict
      ? `Stage 2 detected ${verdictLabel(scan.stage2_verdict).toLowerCase()}`
      : "Full scan result available";
  }
  return scan.verdict === "malicious" ? "Malicious site detected" : "Suspicious site needs review";
}

function overlaySupportCopy(scan: LocalScanRecord) {
  if (scan.verdict === "needs_review" || scan.consistency_status === "conflict") {
    return "The fast URL precheck and the deeper page review disagreed, so the stored final state remains review-safe while this card shows the actual Stage 2 result from the system.";
  }
  if (scan.verdict === "malicious") {
    return "Non-visual URL, content, structural, and safe-filter signals align strongly enough to recommend leaving this page unless you explicitly trust it.";
  }
  return "This page is not conclusively malicious, but it triggered enough non-visual risk signals to slow down and verify before entering data.";
}

function displayVerdict(scan: LocalScanRecord): Verdict | StageVerdict {
  if ((scan.verdict === "needs_review" || scan.consistency_status === "conflict") && scan.stage2_verdict) {
    return scan.stage2_verdict;
  }
  return scan.verdict;
}

function OverlayApp({
  state,
  onDismiss,
  onAction,
}: {
  state: UiState;
  onDismiss: () => void;
  onAction: (action: OverlayAction) => void;
}) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape" && state.mode === "overlay") {
        if (!isBlockingVerdict(state.scan.verdict) || state.allowContinueOnMalicious) {
          onAction("continue_browsing");
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onAction, state]);

  if (state.mode === "idle") {
    return null;
  }

  if (state.mode === "indicator") {
    return (
      <div className="phishguard-indicator">
        <VerdictBadge verdict={state.verdict} />
        <div>
          <strong>{verdictLabel(state.verdict)}</strong>
          <div className="phishguard-muted">
            {scoreToPercent(state.score)} - {state.reason.replaceAll("_", " ")}
          </div>
        </div>
      </div>
    );
  }

  if (state.mode === "error") {
    return (
      <div className="phishguard-indicator phishguard-indicator-error">
        <strong>PhishGuard scan issue</strong>
        <div className="phishguard-muted">{state.message}</div>
      </div>
    );
  }

  const { scan, allowContinueOnMalicious } = state;
  const visibleVerdict = displayVerdict(scan);
  const blocking = isBlockingVerdict(visibleVerdict);
  const canContinue = !blocking || allowContinueOnMalicious;

  return (
    <div className={blocking ? "phishguard-backdrop" : "phishguard-floating-shell"}>
      <section className={`phishguard-card phishguard-card-${visibleVerdict}`} role="dialog" aria-modal={blocking}>
        <div className="phishguard-card-header">
          <div className="phishguard-heading-group">
            <div className="phishguard-eyebrow">PhishGuard Live Review</div>
            <h1>{overlayHeadline(scan)}</h1>
            <p className="phishguard-section-note">{overlaySupportCopy(scan)}</p>
          </div>
          <VerdictBadge verdict={visibleVerdict} />
        </div>

        <div className="phishguard-hero-shell">
          <div className="phishguard-domain-lockup">
            <div className="phishguard-panel-kicker">Current destination</div>
            <div className="phishguard-url">{getDomainLabel(scan.url)}</div>
          </div>
          <p className="phishguard-body-copy">{scan.recommendation}</p>
        </div>

        <ScanStageTrace
          stage1Verdict={scan.stage1_verdict}
          stage2Verdict={scan.stage2_verdict}
          consistencyStatus={scan.consistency_status}
          title="Stage consistency"
        />

        <section className="phishguard-section">
          <div className="phishguard-section-header">
            <div>
              <div className="phishguard-panel-title">Risk telemetry</div>
              <p className="phishguard-section-note">The extension acts on the final verdict contract, not raw intermediate scores.</p>
            </div>
          </div>
          <div className="phishguard-stat-grid">
            <div className="phishguard-stat-card">
              <span className="phishguard-label">Final score</span>
              <strong className="phishguard-stat-value">{scoreToPercent(scan.final_score)}</strong>
            </div>
            <div className="phishguard-stat-card">
              <span className="phishguard-label">Decision threshold</span>
              <strong className="phishguard-stat-value">{scoreToPercent(scan.threshold)}</strong>
            </div>
            <div className="phishguard-stat-card">
              <span className="phishguard-label">System result</span>
              <strong className="phishguard-stat-value">{verdictLabel(visibleVerdict)}</strong>
            </div>
            <div className="phishguard-stat-card">
              <span className="phishguard-label">Filter reason</span>
              <strong className="phishguard-stat-value">{scan.filter_reason.replaceAll("_", " ")}</strong>
            </div>
            <div className="phishguard-stat-card">
              <span className="phishguard-label">Last scan</span>
              <strong className="phishguard-stat-value">{formatTimestamp(scan.timestamp)}</strong>
            </div>
          </div>
        </section>

        <section className="phishguard-section">
          <div className="phishguard-section-header">
            <div>
              <div className="phishguard-panel-title">Triggered non-visual signals</div>
              <p className="phishguard-section-note">Only URL, content, structural, and safe-filter signals are considered here.</p>
            </div>
          </div>
          <SignalChips signals={scan.signals} limit={6} />
        </section>

        <div className="phishguard-action-layout">
          <div className="phishguard-actions phishguard-actions-primary">
            <button className="phishguard-button phishguard-button-danger" onClick={() => onAction("report_phishing")}>
              Report as phishing
            </button>
            <button className="phishguard-button phishguard-button-secondary" onClick={() => onAction("mark_safe")}>
              Mark as safe
            </button>
            <button className="phishguard-button phishguard-button-secondary" onClick={() => onAction("open_dashboard")}>
              Open full dashboard
            </button>
          </div>
          <div className="phishguard-actions phishguard-actions-secondary">
            {scan.verdict === "malicious" ? (
              <button className="phishguard-button phishguard-button-secondary" onClick={() => onAction("add_to_whitelist")}>
                Add to whitelist
              </button>
            ) : null}
            {canContinue ? (
              <button className="phishguard-button phishguard-button-ghost" onClick={() => onAction("continue_browsing")}>
                Continue browsing
              </button>
            ) : null}
            <button className="phishguard-button phishguard-button-ghost" onClick={() => onAction("rescan")}>
              Rescan page
            </button>
          </div>
        </div>

        {canContinue && (
          <button className="phishguard-close" aria-label="Dismiss" onClick={onDismiss}>
            x
          </button>
        )}
      </section>
    </div>
  );
}

function mountUi() {
  let host = document.getElementById(overlayId);
  if (!host) {
    host = document.createElement("div");
    host.id = overlayId;
    document.documentElement.appendChild(host);
  }

  const root = createRoot(host);

  function App() {
    const [state, setState] = useState<UiState>({ mode: "idle" });

    useEffect(() => {
      const listener = (
        message: RuntimeMessage,
        _sender: chrome.runtime.MessageSender,
        sendResponse: (response?: unknown) => void,
      ) => {
        if (message.type === "REQUEST_PAGE_CONTENT") {
          void (async () => {
            try {
              await waitForStablePage(
                message.payload.readyTimeoutMs,
                message.payload.stabilityDelayMs,
                message.payload.stabilityTimeoutMs,
              );
              const payload: PageContentPayload = {
                url: window.location.href,
                title: document.title,
                text_clean: await extractVisibleText(message.payload.maxVisibleTextChars),
                text_raw: await extractRawHtml(message.payload.maxRawHtmlChars),
              };
              sendResponse(payload);
            } catch (error) {
              sendResponse({
                error: error instanceof Error ? error.message : "Could not collect page content.",
              });
            }
          })();
          return true;
        }

        if (message.type === "SHOW_OVERLAY") {
          setState({
            mode: "overlay",
            scan: message.payload.scan,
            allowContinueOnMalicious: message.payload.allowContinueOnMalicious,
          });
          sendResponse({ ok: true });
          return false;
        }

        if (message.type === "SHOW_SAFE_INDICATOR") {
          setState({
            mode: "indicator",
            verdict: message.payload.verdict,
            score: message.payload.score,
            reason: message.payload.reason,
          });
          sendResponse({ ok: true });
          return false;
        }

        if (message.type === "SHOW_SCAN_ERROR") {
          setState({ mode: "error", message: message.payload.message });
          sendResponse({ ok: true });
          return false;
        }

        if (message.type === "CLEAR_PAGE_UI") {
          setState({ mode: "idle" });
          sendResponse({ ok: true });
          return false;
        }

        return false;
      };

      chrome.runtime.onMessage.addListener(listener);
      return () => chrome.runtime.onMessage.removeListener(listener);
    }, []);

    useEffect(() => {
      const bridgeHandler = async (event: MessageEvent<{ type?: string }>) => {
        if (event.source !== window || event.data?.type !== DASHBOARD_SNAPSHOT_REQUEST) {
          return;
        }
        const settings = await getSettings();
        try {
          const dashboardOrigin = new URL(settings.dashboardBaseUrl).origin;
          const allowedOrigins = new Set([dashboardOrigin, "http://localhost:3000", "http://127.0.0.1:3000"]);
          if (!allowedOrigins.has(window.location.origin)) {
            return;
          }
        } catch {
          return;
        }

        const snapshot: LocalDashboardSnapshot = await buildLocalSnapshot();
        window.postMessage(
          {
            type: DASHBOARD_SNAPSHOT_RESPONSE,
            payload: snapshot,
          },
          window.location.origin,
        );
      };

      window.addEventListener("message", bridgeHandler);
      return () => window.removeEventListener("message", bridgeHandler);
    }, []);

    const handleAction = async (action: OverlayAction) => {
      if (action === "open_dashboard" && state.mode === "overlay") {
        await sendRuntimeMessage({
          type: "OPEN_DASHBOARD",
          payload: {
            url: state.scan.url,
            scanId: state.scan.scan_id,
          },
        });
        return;
      }

      if (action === "rescan") {
        await sendRuntimeMessage({
          type: "RESCAN_URL",
          payload: {
            url: window.location.href,
          },
        });
        return;
      }

      if (state.mode !== "overlay") {
        return;
      }

      if (action === "open_dashboard") {
        return;
      }

      await sendRuntimeMessage({
        type: "OVERLAY_ACTION",
        payload: {
          action,
          scanId: state.scan.scan_id,
          url: state.scan.url,
          verdict: state.scan.verdict,
        },
      });

      if (action === "mark_safe" || action === "continue_browsing" || action === "add_to_whitelist") {
        setState({ mode: "idle" });
      }
    };

    return (
      <OverlayApp
        state={state}
        onDismiss={() => {
          if (state.mode === "overlay") {
            void handleAction("continue_browsing");
            return;
          }
          setState({ mode: "idle" });
        }}
        onAction={handleAction}
      />
    );
  }

  root.render(<App />);
}

mountUi();
watchLocationChanges();
firePageReady();
