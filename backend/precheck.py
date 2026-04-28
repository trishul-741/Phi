from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlparse

import re
import tldextract

from backend.schemas import PrecheckResponse

_RE_IP = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")
_TLD = tldextract.TLDExtract(suffix_list_urls=None)
_KEYWORDS = {
    "login",
    "signin",
    "sign-in",
    "verify",
    "update",
    "secure",
    "security",
    "account",
    "password",
    "wallet",
    "billing",
    "bank",
    "credential",
}
_BRANDS = {
    "paypal",
    "apple",
    "microsoft",
    "google",
    "amazon",
    "facebook",
    "instagram",
    "linkedin",
    "netflix",
    "chase",
    "bankofamerica",
    "wellsfargo",
    "dhl",
    "fedex",
}
_SSO_WHITELIST = {
    "login.microsoftonline.com",
    "okta.com",
    "aws.amazon.com",
}


@dataclass
class ParsedUrl:
    url: str
    scheme: str
    host: str
    path: str
    registered_domain: str
    subdomain_depth: int


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_url(url: str) -> ParsedUrl:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.netloc or parsed.path or "").split("/")[0].split(":")[0].lower().strip(".")
    extracted = _TLD(host)
    registered_domain = (
        f"{extracted.domain}.{extracted.suffix}"
        if extracted.domain and extracted.suffix
        else extracted.domain or host
    )
    subdomain_depth = len([part for part in extracted.subdomain.split(".") if part and part != "www"])
    return ParsedUrl(
        url=url,
        scheme=parsed.scheme or "https",
        host=host,
        path=parsed.path or "",
        registered_domain=registered_domain,
        subdomain_depth=subdomain_depth,
    )


def domain_matches(host: str, trusted_domains: Iterable[str]) -> bool:
    for domain in trusted_domains:
        candidate = normalize_domain(domain)
        if not candidate:
            continue
        if host == candidate or host.endswith(f".{candidate}"):
            return True
    return False


def normalize_domain(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.netloc or parsed.path or "").split("/")[0].split(":")[0].lower().strip(".")


def score_url_risk(url: str) -> tuple[float, list[str]]:
    parsed = parse_url(url)
    reasons: list[str] = []
    risk = 0.0

    if not parsed.host:
        return 0.45, ["empty_host"]

    if _RE_IP.search(parsed.host):
        return 0.97, ["ip_hostname"]

    lowered = url.lower()
    search_area = f"{parsed.host} {parsed.path}".lower()

    for sso in _SSO_WHITELIST:
        if sso in search_area or domain_matches(parsed.host, [sso]):
            return 0.05, ["sso_whitelist"]

    if parsed.scheme == "http":
        risk += 0.08
        reasons.append("plaintext_http")
    if "@" in lowered:
        risk += 0.25
        reasons.append("at_symbol")
    if "xn--" in parsed.host:
        risk += 0.25
        reasons.append("punycode_host")
    if len(parsed.host) > 45:
        risk += 0.15
        reasons.append("hostname_length")
    if parsed.subdomain_depth >= 3:
        risk += 0.15
        reasons.append("subdomain_depth")
    if sum(ch.isdigit() for ch in parsed.host) >= 6:
        risk += 0.08
        reasons.append("digit_heavy_host")
    if lowered.count("-") >= 4:
        risk += 0.08
        reasons.append("hyphenated_url")
    if any(keyword in search_area for keyword in _KEYWORDS):
        risk += 0.14
        reasons.append("credential_lure_terms")
    for brand in _BRANDS:
        if brand in search_area and parsed.registered_domain.split(".")[0] != brand:
            risk += 0.22
            reasons.append("brand_impersonation")
            break

    return min(risk, 1.0), reasons


def run_stage1_precheck(url: str, trusted_domains: list[str], safeguard=None) -> PrecheckResponse:
    parsed = parse_url(url)
    timestamp = now_iso()

    if domain_matches(parsed.host, trusted_domains):
        return PrecheckResponse(
            stage1_verdict="safe",
            stage1_score=0.02,
            should_run_full_scan=False,
            reason="trusted_domain",
            cacheable=True,
            timestamp=timestamp,
        )

    top_domains = getattr(safeguard, "top_domains", set()) if safeguard else set()
    if parsed.registered_domain and parsed.registered_domain in top_domains:
        return PrecheckResponse(
            stage1_verdict="safe",
            stage1_score=0.05,
            should_run_full_scan=False,
            reason="whitelist_bypass",
            cacheable=True,
            timestamp=timestamp,
        )

    score, reasons = score_url_risk(url)
    if score >= 0.75:
        verdict = "malicious"
        run_full_scan = True
    elif score >= 0.25:
        verdict = "suspicious"
        run_full_scan = True
    else:
        verdict = "safe"
        run_full_scan = False

    return PrecheckResponse(
        stage1_verdict=verdict,
        stage1_score=score,
        should_run_full_scan=run_full_scan,
        reason=",".join(reasons) if reasons else "low_risk_url",
        cacheable=True,
        timestamp=timestamp,
    )
