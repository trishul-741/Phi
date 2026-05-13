from __future__ import annotations

from typing import Iterable

import pandas as pd

from backend.schemas import ConsistencyStatus, GroupedSignals, SignalItem, StageVerdict, Verdict
from ml.features import engineer_features

_FILTER_REASON_LABELS = {
    "whitelist_bypass": ("Trusted domain bypass", "A trusted or highly reputable domain bypassed the high-risk path."),
    "ip_hostname": ("IP hostname", "The site is served from a raw IP address instead of a registered domain."),
    "hostname_length": ("Long hostname", "The hostname is unusually long for a normal sign-in or account page."),
    "subdomain_depth": ("Deep subdomain chain", "The hostname uses many nested subdomains, which is common in phishing URLs."),
    "brand_impersonation": ("Brand impersonation", "A well-known brand appears in the URL outside the registered domain."),
    "model_only": ("Model-driven risk", "The fused non-visual model carried the decision without extra filter overrides."),
    "plaintext_http": ("Plain HTTP", "The page uses plain HTTP instead of HTTPS."),
    "credential_lure_terms": ("Credential lure terms", "The URL includes account or verification language often used in phishing."),
    "official_security_test": ("Official security test", "The URL matches a public security-test page intended to verify phishing protection behavior."),
    "public_hosting_platform": ("Public hosting platform", "The URL is hosted on a user-content platform commonly abused for disposable phishing pages."),
    "suspicious_tld": ("Suspicious TLD", "The URL uses a top-level domain that frequently appears in abuse reports and needs supporting evidence."),
}

_STRONG_MALICIOUS_SIGNAL_KEYS = {
    "brand_impersonation_score",
    "has_ip",
    "num_at",
    "has_hidden_iframe",
    "same_domain_form_action_ratio",
}


def _single_row(url: str, text_clean: str, text_raw: str) -> pd.Series:
    frame = pd.DataFrame(
        [{"url": url, "text_clean": text_clean or "", "text_raw": text_raw or text_clean or ""}]
    )
    engineered = engineer_features(frame)
    return engineered.iloc[0]


def summarize_signal_evidence(grouped_signals: GroupedSignals | None) -> dict[str, int]:
    if grouped_signals is None:
        return {
            "strong_malicious_count": 0,
            "supporting_signal_count": 0,
        }

    strong_malicious_count = 0
    supporting_signal_count = 0
    for signal in (
        list(grouped_signals.url_signals)
        + list(grouped_signals.content_signals)
        + list(grouped_signals.structural_signals)
    ):
        if signal.key in _STRONG_MALICIOUS_SIGNAL_KEYS or signal.severity == "malicious":
            strong_malicious_count += 1
        elif signal.severity == "suspicious":
            supporting_signal_count += 1

    return {
        "strong_malicious_count": strong_malicious_count,
        "supporting_signal_count": supporting_signal_count,
    }


def derive_verdict(
    final_score: float,
    threshold: float,
    filter_reason: str,
    grouped_signals: GroupedSignals | None = None,
) -> StageVerdict:
    risky_filter = filter_reason not in {"model_only", "whitelist_bypass"}
    safe_cutoff = max(0.18, threshold - 0.15)
    
    if final_score >= threshold:
        return "malicious"
    
    if final_score >= safe_cutoff or risky_filter:
        return "suspicious"
        
    return "safe"


def resolve_consistency(
    *,
    stage1_verdict: StageVerdict,
    stage2_verdict: StageVerdict,
    stage1_reason: str,
) -> tuple[Verdict, ConsistencyStatus, str]:
    if stage1_verdict == "safe" and stage2_verdict == "malicious":
        if stage1_reason in {"trusted_domain", "whitelist_bypass"}:
            return "needs_review", "conflict", "trusted_safe_stage1_conflict"
        return "needs_review", "conflict", "stage1_safe_stage2_malicious"
        
    if stage1_verdict == "malicious" and stage2_verdict == "safe":
        return "needs_review", "conflict", "stage1_malicious_stage2_safe"

    return stage2_verdict, "consistent", "aligned_stage_decision"


def build_recommendation(
    verdict: Verdict,
    filter_reason: str,
    *,
    consistency_status: ConsistencyStatus = "consistent",
) -> str:
    if verdict == "needs_review" or consistency_status == "conflict":
        return (
            "The URL screening looked safe, but page content or structure raised additional concern. "
            "Continue carefully, review the full report, and avoid sharing credentials until verified."
        )
    if verdict == "malicious":
        return "Do not enter credentials or payment details. Leave the page unless you explicitly trust the domain."
    if verdict == "suspicious":
        return "Proceed carefully and verify the destination before submitting credentials or sensitive information."
    if filter_reason == "whitelist_bypass":
        return "Continue browsing. The page matched a trusted-domain safety filter and did not require a full warning."
    return "Continue browsing. No high-risk non-visual phishing signals crossed the action threshold."


def _append(target: list[SignalItem], item: SignalItem | None) -> None:
    if item is not None:
        target.append(item)


def _value_signal(
    *,
    key: str,
    label: str,
    value,
    threshold_hit: bool,
    severity: Verdict,
    description: str,
) -> SignalItem | None:
    if not threshold_hit:
        return None
    return SignalItem(
        key=key,
        label=label,
        value=value,
        severity=severity,
        description=description,
    )


def parse_filter_signals(filter_reason: str, verdict: Verdict) -> list[SignalItem]:
    items: list[SignalItem] = []
    for raw_reason in [part.strip() for part in (filter_reason or "").split(",") if part.strip()]:
        label, description = _FILTER_REASON_LABELS.get(
            raw_reason,
            (raw_reason.replace("_", " ").title(), "Risk control logic attached this reason during scoring."),
        )
        severity = "safe" if raw_reason == "whitelist_bypass" else verdict
        items.append(
            SignalItem(
                key=raw_reason,
                label=label,
                value=raw_reason,
                severity=severity,
                description=description,
            )
        )
    return items


def build_grouped_signals(
    *,
    url: str,
    text_clean: str,
    text_raw: str,
    filter_reason: str,
    final_score: float,
    threshold: float,
    verdict: StageVerdict,
    consistency_status: ConsistencyStatus = "consistent",
    stage1_verdict: StageVerdict | None = None,
    stage2_verdict: StageVerdict | None = None,
) -> GroupedSignals:
    row = _single_row(url, text_clean, text_raw)
    grouped = GroupedSignals()

    _append(
        grouped.url_signals,
        _value_signal(
            key="brand_impersonation_score",
            label="Brand impersonation",
            value=int(row.get("brand_impersonation_score", 0)),
            threshold_hit=int(row.get("brand_impersonation_score", 0)) > 0,
            severity="malicious",
            description="The URL references a known brand outside the registered domain.",
        ),
    )
    _append(
        grouped.url_signals,
        _value_signal(
            key="has_ip",
            label="IP-based host",
            value=bool(row.get("has_ip", 0)),
            threshold_hit=bool(row.get("has_ip", 0)),
            severity="malicious",
            description="The page is hosted on an IP address instead of a normal registered domain.",
        ),
    )
    _append(
        grouped.url_signals,
        _value_signal(
            key="subdomain_depth",
            label="Deep subdomain chain",
            value=int(row.get("subdomain_depth", 0)),
            threshold_hit=int(row.get("subdomain_depth", 0)) >= 3,
            severity="suspicious",
            description="The hostname contains several nested subdomains.",
        ),
    )
    _append(
        grouped.url_signals,
        _value_signal(
            key="num_at",
            label="@ symbol in URL",
            value=int(row.get("num_at", 0)),
            threshold_hit=int(row.get("num_at", 0)) > 0,
            severity="malicious",
            description="The URL contains an @ symbol, which is often used to disguise destinations.",
        ),
    )
    _append(
        grouped.url_signals,
        _value_signal(
            key="domain_entropy",
            label="High hostname entropy",
            value=round(float(row.get("domain_entropy", 0.0)), 3),
            threshold_hit=float(row.get("domain_entropy", 0.0)) >= 3.6,
            severity="suspicious",
            description="The hostname looks unusually random or algorithmically generated.",
        ),
    )

    _append(
        grouped.content_signals,
        _value_signal(
            key="login_kw_density",
            label="Credential lure language",
            value=round(float(row.get("login_kw_density", 0.0)), 3),
            threshold_hit=float(row.get("login_kw_density", 0.0)) >= 0.02,
            severity="suspicious",
            description="The page text contains dense sign-in, verification, or account security language.",
        ),
    )
    _append(
        grouped.content_signals,
        _value_signal(
            key="has_password_field",
            label="Password field present",
            value=bool(row.get("has_password_field", 0)),
            threshold_hit=bool(row.get("has_password_field", 0)),
            severity="suspicious",
            description="The page contains a password field and should be verified carefully.",
        ),
    )
    _append(
        grouped.content_signals,
        _value_signal(
            key="title_mismatch",
            label="Title/domain mismatch",
            value=bool(row.get("title_mismatch", 0)),
            threshold_hit=bool(row.get("title_mismatch", 0)),
            severity="suspicious",
            description="The HTML title does not align well with the registered domain.",
        ),
    )
    _append(
        grouped.content_signals,
        _value_signal(
            key="domain_title_token_overlap",
            label="Low title overlap",
            value=round(float(row.get("domain_title_token_overlap", 0.0)), 3),
            threshold_hit=float(row.get("domain_title_token_overlap", 0.0)) <= 0.1
            and bool(row.get("title_mismatch", 0)),
            severity="suspicious",
            description="The page title shares very little overlap with the site domain.",
        ),
    )

    _append(
        grouped.structural_signals,
        _value_signal(
            key="has_hidden_iframe",
            label="Hidden iframe",
            value=bool(row.get("has_hidden_iframe", 0)),
            threshold_hit=bool(row.get("has_hidden_iframe", 0)),
            severity="malicious",
            description="The DOM includes a hidden iframe, which is commonly used for deceptive flows.",
        ),
    )
    _append(
        grouped.structural_signals,
        _value_signal(
            key="external_link_ratio",
            label="External link ratio",
            value=round(float(row.get("external_link_ratio", 0.0)), 3),
            threshold_hit=float(row.get("external_link_ratio", 0.0)) >= 0.25,
            severity="suspicious",
            description="A large share of links point to external destinations outside the page domain.",
        ),
    )
    _append(
        grouped.structural_signals,
        _value_signal(
            key="form_action_density",
            label="Form action density",
            value=round(float(row.get("form_action_density", 0.0)), 5),
            threshold_hit=float(row.get("form_action_density", 0.0)) >= 0.01,
            severity="suspicious",
            description="The page has an unusual density of form actions relative to visible text.",
        ),
    )
    _append(
        grouped.structural_signals,
        _value_signal(
            key="same_domain_form_action_ratio",
            label="Cross-domain forms",
            value=round(float(row.get("same_domain_form_action_ratio", 0.0)), 3),
            threshold_hit=float(row.get("same_domain_form_action_ratio", 0.0)) < 0.5
            and int(row.get("submit_button_count", 0)) > 0,
            severity="malicious",
            description="Form submissions appear to target a different domain from the current page.",
        ),
    )
    _append(
        grouped.structural_signals,
        _value_signal(
            key="num_hidden_inputs",
            label="Hidden inputs",
            value=int(row.get("num_hidden_inputs", 0)),
            threshold_hit=int(row.get("num_hidden_inputs", 0)) >= 4,
            severity="suspicious",
            description="The page contains many hidden inputs, which may indicate deceptive form handling.",
        ),
    )

    grouped.filter_signals.extend(parse_filter_signals(filter_reason, verdict))
    if consistency_status == "conflict":
        grouped.filter_signals.insert(
            0,
            SignalItem(
                key="stage_conflict",
                label="Stage conflict",
                value=f"{stage1_verdict or 'unknown'}->{stage2_verdict or verdict}",
                severity="suspicious",
                description=(
                    "Stage 1 URL screening stayed safe, but Stage 2 page text or structure produced a much higher risk signal."
                ),
            ),
        )
    if not any([grouped.url_signals, grouped.content_signals, grouped.structural_signals, grouped.filter_signals]):
        grouped.filter_signals.append(
            SignalItem(
                key="low_risk_score",
                label="Low risk score",
                value=round(final_score, 3),
                severity="safe",
                description="The final score stayed well below the active action threshold.",
            )
        )
    elif not grouped.filter_signals:
        grouped.filter_signals.append(
            SignalItem(
                key="score_band",
                label="Final score band",
                value=f"{final_score:.3f} / {threshold:.3f}",
                severity=verdict,
                description="The final decision is based on the calibrated score and safe-filter adjustment.",
            )
        )
    return grouped
