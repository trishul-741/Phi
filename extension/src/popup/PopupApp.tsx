import type { LocalScanRecord, Verdict } from "@phishguard/shared";
import { formatTimestamp, getDomainLabel, scoreToPercent, verdictLabel } from "@phishguard/shared";
import { useEffect, useMemo, useState } from "react";

import { ScanStageTrace } from "../components/ScanStageTrace";
import { SignalChips } from "../components/SignalChips";
import { VerdictBadge } from "../components/VerdictBadge";
import { getScanHistory } from "../lib/storage";

async function getActiveTabUrl(): Promise<string | undefined> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab?.url;
}

function displayVerdict(scan: LocalScanRecord): Verdict {
  if ((scan.verdict === "needs_review" || scan.consistency_status === "conflict") && scan.stage2_verdict) {
    return scan.stage2_verdict;
  }
  return scan.verdict;
}

export function PopupApp() {
  const [currentScan, setCurrentScan] = useState<LocalScanRecord | null>(null);
  const [history, setHistory] = useState<LocalScanRecord[]>([]);
  const [activeUrl, setActiveUrl] = useState<string>("");

  useEffect(() => {
    void (async () => {
      const url = (await getActiveTabUrl()) ?? "";
      setActiveUrl(url);
      const latest = (await chrome.runtime.sendMessage({
        type: "GET_CURRENT_SCAN",
        payload: { url },
      })) as LocalScanRecord | null;
      setCurrentScan(latest);
      setHistory((await getScanHistory()).slice(0, 5));
    })();
  }, []);

  const currentTitle = useMemo(() => {
    if (currentScan) {
      return getDomainLabel(currentScan.url);
    }
    if (activeUrl) {
      return getDomainLabel(activeUrl);
    }
    return "No page selected";
  }, [activeUrl, currentScan]);

  const openDashboard = async () => {
    if (!activeUrl) {
      return;
    }
    await chrome.runtime.sendMessage({
      type: "OPEN_DASHBOARD",
      payload: {
        url: activeUrl,
        scanId: currentScan?.scan_id,
      },
    });
  };

  const rescan = async () => {
    if (!activeUrl) {
      return;
    }
    await chrome.runtime.sendMessage({
      type: "RESCAN_URL",
      payload: {
        url: activeUrl,
      },
    });
    window.close();
  };

  const action = async (kind: "report_phishing" | "mark_safe") => {
    if (!currentScan) {
      return;
    }
    await chrome.runtime.sendMessage({
      type: "OVERLAY_ACTION",
      payload: {
        action: kind,
        scanId: currentScan.scan_id,
        url: currentScan.url,
        verdict: currentScan.verdict,
      },
    });
    window.close();
  };

  const currentSummary = currentScan
    ? currentScan.verdict === "needs_review" || currentScan.consistency_status === "conflict"
      ? "Showing the actual Stage 2 full-scan result. The stored final state remains review-safe because Stage 1 and Stage 2 disagreed."
      : currentScan.recommendation
    : "PhishGuard shows passive protection on low-risk pages and escalates only when non-visual risk increases.";
  const currentDisplayVerdict = currentScan ? displayVerdict(currentScan) : null;
  const historyLabel = history.length === 1 ? "1 item" : `${history.length} items`;

  return (
    <div className="phishguard-page-shell phishguard-popup-shell">
      <section className="phishguard-panel phishguard-panel-hero">
        <div className="phishguard-page-header">
          <div className="phishguard-heading-group">
            <div className="phishguard-eyebrow">PhishGuard</div>
            <h1>Current page review</h1>
            <p className="phishguard-panel-copy">Immediate protection for the active browser tab.</p>
          </div>
          {currentDisplayVerdict ? <VerdictBadge verdict={currentDisplayVerdict} /> : <span className="phishguard-mini-status">Awaiting scan</span>}
        </div>

        <div className="phishguard-domain-lockup">
          <div className="phishguard-panel-kicker">Active destination</div>
          <div className="phishguard-domain-title">{currentTitle}</div>
          <div className="phishguard-muted">{currentScan ? currentScan.url : activeUrl || "No active browser tab detected."}</div>
        </div>

        <p className="phishguard-body-copy">{currentSummary}</p>

        {currentScan ? (
          <>
            <div className="phishguard-stat-grid phishguard-stat-grid-compact">
              <div className="phishguard-stat-card">
                <span className="phishguard-label">System result</span>
                <strong className="phishguard-stat-value">{verdictLabel(currentDisplayVerdict ?? currentScan.verdict)}</strong>
              </div>
              <div className="phishguard-stat-card">
                <span className="phishguard-label">Final score</span>
                <strong className="phishguard-stat-value">{scoreToPercent(currentScan.final_score)}</strong>
              </div>
              <div className="phishguard-stat-card">
                <span className="phishguard-label">Updated</span>
                <strong className="phishguard-stat-value">{formatTimestamp(currentScan.timestamp)}</strong>
              </div>
            </div>
            <ScanStageTrace
              stage1Verdict={currentScan.stage1_verdict}
              stage2Verdict={currentScan.stage2_verdict}
              consistencyStatus={currentScan.consistency_status}
              compact
            />
          </>
        ) : null}
      </section>

      <section className="phishguard-panel">
        <div className="phishguard-section-header">
          <div>
            <div className="phishguard-panel-title">Quick actions</div>
            <p className="phishguard-section-note">Review the final verdict, then decide how you want to handle this page.</p>
          </div>
        </div>

        {currentScan ? <SignalChips signals={currentScan.signals} limit={4} /> : <p className="phishguard-muted">No locally stored non-visual signals yet.</p>}

        <div className="phishguard-action-layout">
          <div className="phishguard-actions phishguard-actions-primary">
            <button className="phishguard-button phishguard-button-danger" onClick={() => void action("report_phishing")} disabled={!currentScan}>
              Report as phishing
            </button>
            <button className="phishguard-button phishguard-button-secondary" onClick={() => void action("mark_safe")} disabled={!currentScan}>
              Mark as safe
            </button>
            <button className="phishguard-button phishguard-button-secondary" onClick={() => void openDashboard()} disabled={!activeUrl}>
              Open full dashboard
            </button>
          </div>
          <div className="phishguard-actions phishguard-actions-secondary">
            <button className="phishguard-button phishguard-button-ghost" onClick={() => void rescan()} disabled={!activeUrl}>
              Rescan page
            </button>
          </div>
        </div>
      </section>

      <section className="phishguard-panel">
        <div className="phishguard-section-header">
          <div>
            <div className="phishguard-panel-title">Recent local activity</div>
            <p className="phishguard-section-note">Latest scan records stored in `chrome.storage.local` on this device.</p>
          </div>
          <span className="phishguard-mini-status">{historyLabel}</span>
        </div>
        <div className="phishguard-list">
          {history.length === 0 ? (
            <p className="phishguard-muted">No local activity yet.</p>
          ) : (
            history.map((item) => (
              <div key={item.scan_id} className="phishguard-list-item phishguard-activity-item">
                <div className={`phishguard-severity-dot phishguard-severity-dot-${item.verdict}`} aria-hidden="true" />
                <div className="phishguard-activity-copy">
                  <strong>{getDomainLabel(item.url)}</strong>
                  <div className="phishguard-muted">{formatTimestamp(item.timestamp)}</div>
                </div>
                <div className="phishguard-activity-meta">
                  <span className="phishguard-muted">{scoreToPercent(item.final_score)}</span>
                  <VerdictBadge verdict={item.verdict} subtle />
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
