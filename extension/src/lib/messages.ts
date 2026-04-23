import type { LocalDashboardSnapshot, LocalScanRecord, UserAction, Verdict } from "@phishguard/shared";

export const DASHBOARD_SNAPSHOT_REQUEST = "PHISHGUARD_DASHBOARD_SNAPSHOT_REQUEST";
export const DASHBOARD_SNAPSHOT_RESPONSE = "PHISHGUARD_DASHBOARD_SNAPSHOT_RESPONSE";

export type RuntimeMessage =
  | {
      type: "PAGE_READY";
      payload: {
        url: string;
        title: string;
        tabId?: number;
      };
    }
  | {
      type: "REQUEST_PAGE_CONTENT";
      payload: {
        maxVisibleTextChars: number;
        maxRawHtmlChars: number;
        readyTimeoutMs: number;
        stabilityDelayMs: number;
        stabilityTimeoutMs: number;
      };
    }
  | {
      type: "SHOW_OVERLAY";
      payload: {
        scan: LocalScanRecord;
        allowContinueOnMalicious: boolean;
      };
    }
  | {
      type: "SHOW_SAFE_INDICATOR";
      payload: {
        url: string;
        verdict: Verdict;
        score: number;
        reason: string;
      };
    }
  | {
      type: "SHOW_SCAN_ERROR";
      payload: {
        message: string;
      };
    }
  | {
      type: "CLEAR_PAGE_UI";
    }
  | {
      type: "OVERLAY_ACTION";
      payload: {
        action: UserAction;
        scanId?: string;
        url: string;
        verdict: Verdict;
        notes?: string;
      };
    }
  | {
      type: "GET_CURRENT_SCAN";
      payload: {
        url: string;
      };
    }
  | {
      type: "RESCAN_URL";
      payload: {
        url: string;
      };
    }
  | {
      type: "OPEN_DASHBOARD";
      payload: {
        url: string;
        scanId?: string;
      };
    }
  | {
      type: "GET_SETTINGS";
    }
  | {
      type: "SAVE_SETTINGS";
      payload: {
        apiBaseUrl: string;
        dashboardBaseUrl: string;
        safeCacheTtlMs: number;
        riskyCacheTtlMs: number;
        showSafeIndicator: boolean;
        allowContinueOnMalicious: boolean;
        rescanDebounceMs: number;
        contentReadyTimeoutMs: number;
        contentStabilityDelayMs: number;
        contentStabilityTimeoutMs: number;
        maxVisibleTextChars: number;
        maxRawHtmlChars: number;
      };
    }
  | {
      type: "GET_LOCAL_SNAPSHOT";
    };

export interface PageContentPayload {
  url: string;
  title: string;
  text_clean: string;
  text_raw: string;
}

export interface LocalSnapshotResponse {
  snapshot: LocalDashboardSnapshot;
}
