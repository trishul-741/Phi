export type StageVerdict = "safe" | "suspicious" | "malicious";
export type Verdict = StageVerdict | "needs_review";
export type ConsistencyStatus = "consistent" | "conflict";
export type ScanStage = "precheck" | "full_scan";
export type SyncStatus = "pending" | "synced" | "error";
export type UserAction =
  | "report_phishing"
  | "mark_safe"
  | "continue_browsing"
  | "add_to_whitelist"
  | "rescan";

export interface SignalItem {
  key: string;
  label: string;
  value: string | number | boolean;
  severity: StageVerdict;
  description: string;
}

export interface GroupedSignals {
  url_signals: SignalItem[];
  content_signals: SignalItem[];
  structural_signals: SignalItem[];
  filter_signals: SignalItem[];
}

export interface PrecheckRequest {
  url: string;
  hostname?: string;
  device_id?: string;
}

export interface PrecheckResponse {
  stage: "precheck";
  stage1_verdict: StageVerdict;
  stage1_score: number;
  should_run_full_scan: boolean;
  reason: string;
  cacheable: boolean;
  timestamp: string;
}

export interface ScanRequest {
  url: string;
  title: string;
  text_clean: string;
  text_raw: string;
  source: string;
  device_id?: string;
  tab_id?: number;
}

export interface ScanResponse {
  stage: "full_scan";
  scan_id: string;
  url: string;
  title: string;
  verdict: Verdict;
  stage1_verdict?: StageVerdict;
  stage1_score?: number;
  stage1_reason?: string;
  stage2_verdict?: StageVerdict;
  consistency_status: ConsistencyStatus;
  consistency_reason?: string;
  raw_score: number;
  calibrated_score: number;
  final_score: number;
  threshold: number;
  signals: GroupedSignals;
  filter_reason: string;
  recommendation: string;
  timestamp: string;
  architecture: "non_visual_multimodal_fusion";
}

export interface ScanRecord extends ScanResponse {
  source: string;
  device_id?: string;
  tab_id?: number;
}

export interface HistoryResponse {
  items: ScanRecord[];
}

export interface FeedbackRequest {
  scan_id?: string;
  url: string;
  user_action: UserAction;
  previous_verdict: Verdict;
  notes: string;
  timestamp?: string;
  source: string;
  device_id?: string;
}

export interface FeedbackEvent {
  feedback_id: string;
  scan_id?: string;
  url: string;
  user_action: UserAction;
  previous_verdict: Verdict;
  notes: string;
  timestamp: string;
  source: string;
  device_id?: string;
  sync_status: SyncStatus;
}

export interface TrustedDomainRecord {
  domain: string;
  device_id?: string;
  added_at: string;
  source: string;
  note: string;
}

export interface TrustedDomainRequest {
  domain: string;
  device_id?: string;
  source: string;
  note: string;
}

export interface WhitelistResponse {
  items: TrustedDomainRecord[];
}
