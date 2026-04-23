from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

StageVerdict = Literal["safe", "suspicious", "malicious"]
Verdict = Literal["safe", "suspicious", "malicious", "needs_review"]
ConsistencyStatus = Literal["consistent", "conflict"]
ScanStage = Literal["precheck", "full_scan"]
SyncStatus = Literal["pending", "synced", "error"]
UserAction = Literal[
    "report_phishing",
    "mark_safe",
    "continue_browsing",
    "add_to_whitelist",
    "rescan",
]


class SignalItem(BaseModel):
    key: str
    label: str
    value: str | float | int | bool
    severity: StageVerdict
    description: str


class GroupedSignals(BaseModel):
    url_signals: list[SignalItem] = Field(default_factory=list)
    content_signals: list[SignalItem] = Field(default_factory=list)
    structural_signals: list[SignalItem] = Field(default_factory=list)
    filter_signals: list[SignalItem] = Field(default_factory=list)


class PrecheckRequest(BaseModel):
    url: str
    hostname: str | None = None
    device_id: str | None = None


class PrecheckResponse(BaseModel):
    stage: Literal["precheck"] = "precheck"
    stage1_verdict: StageVerdict
    stage1_score: float
    should_run_full_scan: bool
    reason: str
    cacheable: bool
    timestamp: str


class ScanRequest(BaseModel):
    url: str
    title: str = ""
    text_clean: str = ""
    text_raw: str = ""
    source: str = "browser_extension"
    device_id: str | None = None
    tab_id: int | None = None


class ScanResponse(BaseModel):
    stage: Literal["full_scan"] = "full_scan"
    scan_id: str
    url: str
    title: str = ""
    verdict: Verdict
    stage1_verdict: StageVerdict | None = None
    stage1_score: float | None = None
    stage1_reason: str = ""
    stage2_verdict: StageVerdict | None = None
    consistency_status: ConsistencyStatus = "consistent"
    consistency_reason: str = ""
    raw_score: float
    calibrated_score: float
    final_score: float
    threshold: float
    signals: GroupedSignals
    filter_reason: str
    recommendation: str
    timestamp: str
    architecture: Literal["non_visual_multimodal_fusion"]


class ScanRecord(ScanResponse):
    source: str = "browser_extension"
    device_id: str | None = None
    tab_id: int | None = None


class FeedbackRequest(BaseModel):
    scan_id: str | None = None
    url: str
    user_action: UserAction
    previous_verdict: Verdict
    notes: str = ""
    timestamp: str | None = None
    source: str = "browser_extension"
    device_id: str | None = None


class FeedbackEvent(BaseModel):
    feedback_id: str
    scan_id: str | None = None
    url: str
    user_action: UserAction
    previous_verdict: Verdict
    notes: str = ""
    timestamp: str
    source: str = "browser_extension"
    device_id: str | None = None
    sync_status: SyncStatus = "synced"


class HistoryResponse(BaseModel):
    items: list[ScanRecord]


class TrustedDomainRequest(BaseModel):
    domain: str
    device_id: str | None = None
    source: str = "browser_extension"
    note: str = ""


class TrustedDomainRecord(BaseModel):
    domain: str
    device_id: str | None = None
    added_at: str
    source: str = "browser_extension"
    note: str = ""


class WhitelistResponse(BaseModel):
    items: list[TrustedDomainRecord]
