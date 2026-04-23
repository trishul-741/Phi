import type { ExtensionSettings, FeedbackQueueItem, TrustedDomainRecord } from "@phishguard/shared";
import { formatTimestamp } from "@phishguard/shared";
import { useEffect, useState } from "react";

import { addTrustedDomain, deleteTrustedDomain } from "../lib/api";
import {
  addTrustedDomainLocal,
  getDeviceId,
  getFeedbackQueue,
  getSettings,
  getTrustedDomains,
  removeTrustedDomainLocal,
  saveSettings,
} from "../lib/storage";

export function OptionsApp() {
  const [settings, setSettings] = useState<ExtensionSettings | null>(null);
  const [deviceId, setDeviceId] = useState("");
  const [trustedDomains, setTrustedDomains] = useState<TrustedDomainRecord[]>([]);
  const [feedbackQueue, setFeedbackQueue] = useState<FeedbackQueueItem[]>([]);
  const [domainInput, setDomainInput] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    void (async () => {
      setSettings(await getSettings());
      setDeviceId(await getDeviceId());
      setTrustedDomains(await getTrustedDomains());
      setFeedbackQueue(await getFeedbackQueue());
    })();
  }, []);

  if (!settings) {
    return <div className="phishguard-page-shell">Loading PhishGuard settings...</div>;
  }

  const pendingFeedbackCount = feedbackQueue.filter((item) => item.sync_status !== "synced").length;

  const persistSettings = async () => {
    await saveSettings(settings);
    setStatus("Settings saved locally.");
  };

  const addDomain = async () => {
    const domain = domainInput.trim();
    if (!domain) {
      return;
    }
    const record: TrustedDomainRecord = {
      domain,
      device_id: deviceId,
      added_at: new Date().toISOString(),
      source: "browser_extension",
      note: "Added from settings",
    };
    await addTrustedDomainLocal(record);
    try {
      await addTrustedDomain({
        domain,
        device_id: deviceId,
        source: "browser_extension",
        note: "Added from settings",
      });
      setStatus("Trusted domain added and synced.");
    } catch {
      setStatus("Trusted domain added locally. Backend sync will need retry.");
    }
    setTrustedDomains(await getTrustedDomains());
    setDomainInput("");
  };

  const removeDomain = async (domain: string) => {
    await removeTrustedDomainLocal(domain);
    try {
      await deleteTrustedDomain(domain, deviceId);
      setStatus("Trusted domain removed.");
    } catch {
      setStatus("Trusted domain removed locally. Backend sync could not be confirmed.");
    }
    setTrustedDomains(await getTrustedDomains());
  };

  return (
    <div className="phishguard-page-shell phishguard-options-shell">
      <section className="phishguard-panel phishguard-panel-hero">
        <div className="phishguard-page-header">
          <div className="phishguard-heading-group">
            <div className="phishguard-eyebrow">PhishGuard Settings</div>
            <h1>Local protection controls</h1>
            <p className="phishguard-panel-copy">Tune the extension's local-first protection flow, sync endpoints, and trusted domain policy.</p>
          </div>
          <span className="phishguard-mini-status">Non-visual protection</span>
        </div>

        <div className="phishguard-stat-grid">
          <div className="phishguard-stat-card">
            <span className="phishguard-label">Device identity</span>
            <strong className="phishguard-stat-value phishguard-stat-value-small">{deviceId}</strong>
            <span className="phishguard-muted">Used to correlate local extension records with the dashboard.</span>
          </div>
          <div className="phishguard-stat-card">
            <span className="phishguard-label">Trusted domains</span>
            <strong className="phishguard-stat-value">{trustedDomains.length}</strong>
            <span className="phishguard-muted">Domains that can bypass stronger warnings after explicit user trust.</span>
          </div>
          <div className="phishguard-stat-card">
            <span className="phishguard-label">Pending feedback</span>
            <strong className="phishguard-stat-value">{pendingFeedbackCount}</strong>
            <span className="phishguard-muted">Feedback events still waiting for backend confirmation or retry.</span>
          </div>
        </div>
      </section>

      <div className="phishguard-settings-grid">
        <section className="phishguard-panel">
          <div className="phishguard-section-header">
            <div>
              <div className="phishguard-panel-title">Endpoints</div>
              <p className="phishguard-section-note">These routes back Stage 1 prechecks, Stage 2 full scans, dashboard navigation, feedback, and whitelist sync.</p>
            </div>
          </div>
          <label className="phishguard-field">
            <span>API base URL</span>
            <span className="phishguard-field-hint">Used for `/v1/precheck`, `/v1/scan`, `/v1/feedback`, and whitelist endpoints.</span>
            <input value={settings.apiBaseUrl} onChange={(event) => setSettings({ ...settings, apiBaseUrl: event.target.value })} />
          </label>
          <label className="phishguard-field">
            <span>Dashboard base URL</span>
            <span className="phishguard-field-hint">Used for opening the full PhishGuard report experience from the popup and overlay.</span>
            <input value={settings.dashboardBaseUrl} onChange={(event) => setSettings({ ...settings, dashboardBaseUrl: event.target.value })} />
          </label>
        </section>

        <section className="phishguard-panel">
          <div className="phishguard-section-header">
            <div>
              <div className="phishguard-panel-title">Protection timing and cache</div>
              <p className="phishguard-section-note">Control how long verdicts are cached and how patiently the extension waits before collecting Stage 2 page content.</p>
            </div>
          </div>
          <div className="phishguard-field-grid">
            <label className="phishguard-field">
              <span>Safe cache TTL (ms)</span>
              <input
                type="number"
                value={settings.safeCacheTtlMs}
                onChange={(event) => setSettings({ ...settings, safeCacheTtlMs: Number(event.target.value) })}
              />
            </label>
            <label className="phishguard-field">
              <span>Risky cache TTL (ms)</span>
              <input
                type="number"
                value={settings.riskyCacheTtlMs}
                onChange={(event) => setSettings({ ...settings, riskyCacheTtlMs: Number(event.target.value) })}
              />
            </label>
            <label className="phishguard-field">
              <span>Rescan debounce (ms)</span>
              <input
                type="number"
                value={settings.rescanDebounceMs}
                onChange={(event) => setSettings({ ...settings, rescanDebounceMs: Number(event.target.value) })}
              />
            </label>
            <label className="phishguard-field">
              <span>Document ready timeout (ms)</span>
              <input
                type="number"
                value={settings.contentReadyTimeoutMs}
                onChange={(event) => setSettings({ ...settings, contentReadyTimeoutMs: Number(event.target.value) })}
              />
            </label>
            <label className="phishguard-field">
              <span>DOM quiet window (ms)</span>
              <input
                type="number"
                value={settings.contentStabilityDelayMs}
                onChange={(event) => setSettings({ ...settings, contentStabilityDelayMs: Number(event.target.value) })}
              />
            </label>
            <label className="phishguard-field">
              <span>DOM stabilization timeout (ms)</span>
              <input
                type="number"
                value={settings.contentStabilityTimeoutMs}
                onChange={(event) => setSettings({ ...settings, contentStabilityTimeoutMs: Number(event.target.value) })}
              />
            </label>
          </div>

          <div className="phishguard-option-stack">
            <label className="phishguard-checkbox">
              <input
                type="checkbox"
                checked={settings.showSafeIndicator}
                onChange={(event) => setSettings({ ...settings, showSafeIndicator: event.target.checked })}
              />
              <span>Show passive indicator on low-risk pages</span>
            </label>
            <label className="phishguard-checkbox">
              <input
                type="checkbox"
                checked={settings.allowContinueOnMalicious}
                onChange={(event) => setSettings({ ...settings, allowContinueOnMalicious: event.target.checked })}
              />
              <span>Allow explicit continue action on malicious verdicts</span>
            </label>
          </div>

          <div className="phishguard-actions phishguard-actions-secondary">
            <button className="phishguard-button phishguard-button-secondary" onClick={() => void persistSettings()}>
              Save settings
            </button>
          </div>
        </section>
      </div>

      {status ? <div className="phishguard-status-banner">{status}</div> : null}

      <div className="phishguard-settings-grid">
        <section className="phishguard-panel">
          <div className="phishguard-section-header">
            <div>
              <div className="phishguard-panel-title">Trusted domains</div>
              <p className="phishguard-section-note">Whitelist entries are always explicit. They should reflect domains you intentionally trust, not domains you merely visit often.</p>
            </div>
            <span className="phishguard-mini-status">{trustedDomains.length} tracked</span>
          </div>
          <div className="phishguard-inline-form">
            <input value={domainInput} onChange={(event) => setDomainInput(event.target.value)} placeholder="example.com" />
            <button className="phishguard-button phishguard-button-secondary" onClick={() => void addDomain()}>
              Add trusted domain
            </button>
          </div>
          <div className="phishguard-list">
            {trustedDomains.length === 0 ? (
              <p className="phishguard-muted">No trusted domains yet.</p>
            ) : (
              trustedDomains.map((item) => (
                <div key={`${item.domain}-${item.device_id}`} className="phishguard-list-item">
                  <div className="phishguard-activity-copy">
                    <strong>{item.domain}</strong>
                    <div className="phishguard-muted">{formatTimestamp(item.added_at)}</div>
                  </div>
                  <button className="phishguard-button phishguard-button-ghost" onClick={() => void removeDomain(item.domain)}>
                    Remove
                  </button>
                </div>
              ))
            )}
          </div>
        </section>

        <section className="phishguard-panel">
          <div className="phishguard-section-header">
            <div>
              <div className="phishguard-panel-title">Feedback queue</div>
              <p className="phishguard-section-note">User actions are kept locally first, then synced to the backend when available.</p>
            </div>
            <span className="phishguard-mini-status">{feedbackQueue.length} queued</span>
          </div>
          <div className="phishguard-list">
            {feedbackQueue.length === 0 ? (
              <p className="phishguard-muted">No feedback events stored locally.</p>
            ) : (
              feedbackQueue.slice(0, 12).map((item) => (
                <div key={item.feedback_id} className="phishguard-list-item phishguard-list-item-tight">
                  <div className="phishguard-activity-copy">
                    <strong>{item.user_action.replaceAll("_", " ")}</strong>
                    <div className="phishguard-muted">{item.url}</div>
                    <div className="phishguard-muted">{formatTimestamp(item.timestamp)}</div>
                  </div>
                  <span className={`phishguard-sync-pill phishguard-sync-pill-${item.sync_status}`}>{item.sync_status}</span>
                </div>
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
