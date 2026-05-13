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
    "phish",
    "phishing",
}
_BRANDS = {
    "adobe",
    "allegro",
    "allegrolokalnie",
    "binance",
    "bmw",
    "coinbase",
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
    "edf",
    "exodus",
    "icloud",
    "ing",
    "kucoin",
    "ledger",
    "metamask",
    "telegram",
    "trezor",
    "ups",
    "usps",
    "whatsapp",
}
_BRAND_ALIASES = {
    "allegro": {"alegro", "allegrolo", "allegrolokalnie"},
    "exodus": {"exodos", "exodues", "exodocus"},
    "facebook": {"facebooks", "facebok", "facbook"},
    "ledger": {"ledgr"},
    "microsoft": {"microsft", "mircosoft"},
    "paypal": {"p0aypal", "paipal", "paqpal", "pahypal", "pay0al", "pay6pal", "payal", "payapal", "paylal", "payoal", "payopal", "paypan", "payqal", "pypal"},
    "telegram": {"telegramnco"},
    "whatsapp": {"webwhatsapp", "whatsap"},
}
_SSO_WHITELIST = {
    "login.microsoftonline.com",
    "okta.com",
    "aws.amazon.com",
}
_USER_CONTENT_PLATFORMS = {
    "appwrite.network",
    "blogspot.com",
    "cloudfront.net",
    "edgeone.dev",
    "firebaseapp.com",
    "framer.ai",
    "framer.app",
    "github.io",
    "godaddysites.com",
    "ghost.io",
    "netlify.app",
    "pages.dev",
    "sitebeat.crazydomains.com",
    "square.site",
    "typedream.app",
    "vercel.app",
    "web.app",
    "webflow.io",
    "weebly.com",
    "weeblysite.com",
    "wixsite.com",
    "wixstudio.com",
    "workers.dev",
    "zapier.app",
}
_HIGH_RISK_TLDS = {
    "buzz",
    "click",
    "cn",
    "cyou",
    "icu",
    "lol",
    "mom",
    "rest",
    "sbs",
    "top",
    "xyz",
}
_SUSPICIOUS_TLDS = {
    "app",
    "buzz",
    "click",
    "cn",
    "cyou",
    "icu",
    "info",
    "live",
    "lol",
    "mom",
    "rest",
    "sbs",
    "shop",
    "top",
    "xyz",
}
_OFFICIAL_SECURITY_TESTS = {
    "testsafebrowsing.appspot.com": ("phishing", "malware", "billing", "uws"),
    "demo.smartscreen.msft.net": (),
    "amtso.org": ("phishing", "feature-settings-check-phishing-page"),
}
_RESERVED_TEST_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
}
_TOP_DOMAIN_STRONG_REASONS = {
    "at_symbol",
    "digit_heavy_host",
    "hostname_length",
    "public_hosting_platform",
    "punycode_host",
    "subdomain_depth",
    "suspicious_tld",
}


@dataclass
class ParsedUrl:
    url: str
    scheme: str
    host: str
    path: str
    registered_domain: str
    subdomain_depth: int
    suffix: str


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
        suffix=extracted.suffix.lower(),
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


def _levenshtein_at_most(value: str, target: str, limit: int) -> bool:
    if abs(len(value) - len(target)) > limit:
        return False

    previous = list(range(len(target) + 1))
    for i, char in enumerate(value, start=1):
        current = [i]
        row_min = current[0]
        for j, target_char in enumerate(target, start=1):
            cost = 0 if char == target_char else 1
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + cost,
                )
            )
            row_min = min(row_min, current[-1])
        if row_min > limit:
            return False
        previous = current
    return previous[-1] <= limit


def _contains_brand_impersonation(search_area: str, registered_domain: str) -> bool:
    registered_base = registered_domain.split(".")[0]
    tokens = [token for token in re.split(r"[^a-z0-9]+", search_area.lower()) if token]

    for brand in _BRANDS:
        if registered_base == brand:
            continue
        if brand in tokens:
            return True
        if any(alias in search_area for alias in _BRAND_ALIASES.get(brand, set())):
            return True
    return False


def score_url_risk(url: str) -> tuple[float, list[str]]:
    parsed = parse_url(url)
    reasons: list[str] = []
    risk = 0.0

    if not parsed.host:
        return 0.45, ["empty_host"]

    for test_host, markers in _OFFICIAL_SECURITY_TESTS.items():
        if domain_matches(parsed.host, [test_host]) and (not markers or any(marker in url.lower() for marker in markers)):
            return 0.90, ["official_security_test"]

    if _RE_IP.search(parsed.host):
        return 0.97, ["ip_hostname"]

    lowered = url.lower()
    search_area = f"{parsed.host} {parsed.path}".lower()

    for sso in _SSO_WHITELIST:
        if sso in search_area or domain_matches(parsed.host, [sso]):
            return 0.05, ["sso_whitelist"]

    if parsed.scheme == "http":
        risk += 0.10
        reasons.append("plaintext_http")
    if "@" in lowered:
        risk += 0.25
        reasons.append("at_symbol")
    if "xn--" in parsed.host:
        risk += 0.35
        reasons.append("punycode_host")
    if len(parsed.host) > 45:
        risk += 0.20
        reasons.append("hostname_length")
    if parsed.subdomain_depth >= 3:
        risk += 0.20
        reasons.append("subdomain_depth")
    if sum(ch.isdigit() for ch in parsed.host) >= 6:
        risk += 0.15
        reasons.append("digit_heavy_host")
    if lowered.count("-") >= 4:
        risk += 0.12
        reasons.append("hyphenated_url")
    if any(keyword in search_area for keyword in _KEYWORDS):
        risk += 0.20
        reasons.append("credential_lure_terms")
    if parsed.registered_domain in _USER_CONTENT_PLATFORMS and parsed.subdomain_depth > 0:
        risk += 0.20
        reasons.append("public_hosting_platform")
    if parsed.suffix in _SUSPICIOUS_TLDS:
        risk += 0.15 if parsed.suffix in _HIGH_RISK_TLDS else 0.10
        reasons.append("suspicious_tld")
    if _contains_brand_impersonation(search_area, parsed.registered_domain):
        risk += 0.35
        reasons.append("brand_impersonation")

    return min(risk, 1.0), reasons


def run_stage1_precheck(url: str, trusted_domains: list[str], safeguard=None) -> PrecheckResponse:
    parsed = parse_url(url)
    timestamp = now_iso()
    score, reasons = score_url_risk(url)

    if "official_security_test" in reasons:
        return PrecheckResponse(
            stage1_verdict="malicious",
            stage1_score=score,
            should_run_full_scan=True,
            reason="official_security_test",
            cacheable=True,
            timestamp=timestamp,
        )

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
    can_use_top_domain_bypass = (
        parsed.registered_domain
        and parsed.registered_domain in top_domains
        and parsed.registered_domain not in _USER_CONTENT_PLATFORMS
        and parsed.registered_domain not in _RESERVED_TEST_DOMAINS
        and not any(reason in _TOP_DOMAIN_STRONG_REASONS for reason in reasons)
    )
    if can_use_top_domain_bypass:
        return PrecheckResponse(
            stage1_verdict="safe",
            stage1_score=0.05,
            should_run_full_scan=False,
            reason="whitelist_bypass",
            cacheable=True,
            timestamp=timestamp,
        )

    if score >= 0.75:
        verdict = "malicious"
        run_full_scan = True
    elif score >= 0.15:
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
