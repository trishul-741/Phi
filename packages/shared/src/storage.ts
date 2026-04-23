import type {
  ConsistencyStatus,
  FeedbackEvent,
  ScanRecord,
  ScanStage,
  StageVerdict,
  SyncStatus,
  TrustedDomainRecord,
  Verdict,
} from "./contracts";

export interface ExtensionSettings {
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
}

export interface ScanCacheEntry {
  url: string;
  normalizedUrl: string;
  verdict: Verdict;
  finalScore: number;
  reason: string;
  stage: "precheck" | "full";
  scanId?: string;
  cachedAt: string;
  expiresAt: string;
  manualDisposition?: "marked_safe" | "continued" | "whitelisted";
}

export interface LocalScanRecord extends Omit<ScanRecord, "stage"> {
  stage: ScanStage;
  final_verdict?: Verdict;
  synced?: boolean;
}

export interface FlaggedPhishingRecord {
  scanId?: string;
  url: string;
  verdict: "malicious";
  score: number;
  reasons: string[];
  stage1Verdict?: StageVerdict;
  stage2Verdict?: StageVerdict;
  finalVerdict?: Verdict;
  consistencyStatus?: ConsistencyStatus;
  rawScore?: number;
  calibratedScore?: number;
  finalScore?: number;
  threshold?: number;
  filterReason?: string;
  timestamp: string;
  source: string;
  deviceId?: string;
}

export interface SafeReportedAsPhishingRecord {
  scanId?: string;
  url: string;
  originalVerdict: "safe";
  currentFeedbackStatus: "reported_phishing";
  finalVerdict?: Verdict;
  consistencyStatus?: ConsistencyStatus;
  notes: string;
  timestamp: string;
  source: string;
  deviceId?: string;
}

export interface FeedbackQueueItem extends FeedbackEvent {
  retryCount: number;
  lastAttemptAt?: string;
  sync_status: SyncStatus;
}

export interface ExtensionStorageState {
  scanHistory: LocalScanRecord[];
  flaggedPhishingUrls: FlaggedPhishingRecord[];
  safeReportedAsPhishing: SafeReportedAsPhishingRecord[];
  userFeedbackQueue: FeedbackQueueItem[];
  trustedDomains: TrustedDomainRecord[];
  scanCache: Record<string, ScanCacheEntry>;
  settings: ExtensionSettings;
  deviceId: string;
}

export interface LocalDashboardSnapshot {
  deviceId: string;
  collectedAt: string;
  scanHistory: LocalScanRecord[];
  flaggedPhishingUrls: FlaggedPhishingRecord[];
  safeReportedAsPhishing: SafeReportedAsPhishingRecord[];
  userFeedbackQueue: FeedbackQueueItem[];
  trustedDomains: TrustedDomainRecord[];
  settings: ExtensionSettings;
}
