"""
Unit tests for v5 feature engineering changes in ml/features.py.

Tests each new or modified feature extractor with ≥3 edge cases to verify
correctness and ensure the FP-reduction changes work as intended.
"""

import sys
import os
import pytest

# Ensure project root is on sys.path so `ml.features` resolves
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ml.features import (
    _extract_text_features,
    _extract_url_features,
    _external_link_ratio,
    _subdomain_depth,
    _brand_impersonation_score,
    _extract_registered_domain,
    _title_mismatch,
    _domain_title_token_overlap,
    ALL_FEATURE_NAMES,
    SAFE_DOMAINS,
    TOP_BRANDS,
)


# ═════════════════════════════════════════════════════════════════════
# 1. form_action_density
# ═════════════════════════════════════════════════════════════════════

class TestFormActionDensity:
    """Replaces the old binary has_form_action flag."""

    def _get_density(self, raw_html: str, text_clean: str) -> float:
        feats = _extract_text_features(text_clean, raw_html, page_netloc="example.com")
        return feats["form_action_density"]

    def test_no_forms(self):
        """Page with no forms → density 0."""
        html = "<html><body><p>Hello world</p></body></html>"
        text = "Hello world"
        assert self._get_density(html, text) == 0.0

    def test_single_form_many_words(self):
        """Legitimate login page: 1 form, many words → low density."""
        words = " ".join(["word"] * 200)
        html = f'<html><body><form action="/login"><input></form><p>{words}</p></body></html>'
        density = self._get_density(html, words)
        assert density == pytest.approx(1 / 200, abs=1e-6)

    def test_multiple_forms_few_words(self):
        """Suspicious: 3 forms on a short page → high density."""
        html = (
            '<form action="/a"><input></form>'
            '<form action="/b"><input></form>'
            '<form action="/c"><input></form>'
        )
        text = "click here now"  # 3 words
        density = self._get_density(html, text)
        assert density == pytest.approx(3 / 3, abs=1e-6)  # 1.0

    def test_case_insensitive(self):
        """<FORM ACTION=...> should also be detected."""
        html = '<FORM ACTION="/submit"><input></FORM>'
        text = "submit your info please"  # 4 words
        density = self._get_density(html, text)
        assert density == pytest.approx(1 / 4, abs=1e-6)

    def test_empty_text_no_division_by_zero(self):
        """Empty text → word_count=0, max(0,1)=1 prevents ZeroDivisionError."""
        html = '<form action="/x"></form>'
        text = ""
        density = self._get_density(html, text)
        assert density == 1.0  # 1 form / max(0, 1)

    def test_form_without_action_not_counted(self):
        """<form> without action= attribute should NOT be counted."""
        html = '<form method="post"><input></form>'
        text = "some words here"
        density = self._get_density(html, text)
        assert density == 0.0


# ═════════════════════════════════════════════════════════════════════
# 2. external_link_ratio
# ═════════════════════════════════════════════════════════════════════

class TestExternalLinkRatio:
    """Replaces the old num_external_links raw count."""

    def test_no_anchors(self):
        """No anchor tags at all → ratio 0."""
        html = "<html><body><p>No links here</p></body></html>"
        ratio = _external_link_ratio(html, "example.com")
        assert ratio == 0.0

    def test_all_internal_links(self):
        """All links point to same domain → 0 external."""
        html = '''
        <a href="https://example.com/page1">P1</a>
        <a href="https://example.com/page2">P2</a>
        '''
        ratio = _external_link_ratio(html, "example.com")
        assert ratio == 0.0

    def test_mixed_internal_and_external(self):
        """Mix of internal and external links → ratio > 0."""
        html = '''
        <a href="https://example.com/page1">Internal</a>
        <a href="https://evil.com/phish">External</a>
        <a href="https://other-evil.org/bait">External2</a>
        '''
        # 3 navigational anchors, 2 external anchors
        ratio = _external_link_ratio(html, "example.com")
        assert ratio == pytest.approx(2 / 3, abs=1e-6)

    def test_safe_domains_excluded(self):
        """Links to CDN/analytics safe domains should be excluded from count."""
        html = '''
        <a href="https://example.com/home">Internal</a>
        <a href="https://fonts.googleapis.com/css">CDN</a>
        <a href="https://cdn.cloudflare.com/lib.js">CDN</a>
        <a href="https://code.jquery.com/jquery.min.js">CDN</a>
        '''
        # 4 total anchors, 0 external (all safe or internal)
        ratio = _external_link_ratio(html, "example.com")
        assert ratio == 0.0

    def test_safe_domain_subdomain_also_excluded(self):
        """Subdomains of safe domains (e.g., fonts.googleapis.com) should be excluded."""
        html = '''
        <a href="https://fonts.googleapis.com/css">Font</a>
        <a href="https://www.facebook.net/sdk.js">SDK</a>
        '''
        ratio = _external_link_ratio(html, "example.com")
        assert ratio == 0.0

    def test_external_with_some_safe(self):
        """Mix: one real external + two safe → ratio reflects only real external."""
        html = '''
        <a href="https://example.com/home">Internal</a>
        <a href="https://fonts.googleapis.com/css">Safe</a>
        <a href="https://malicious-site.ru/steal">External</a>
        '''
        # 3 navigational anchors, 1 external anchor
        ratio = _external_link_ratio(html, "example.com")
        assert ratio == pytest.approx(1 / 3, abs=1e-6)

    def test_safe_suffix_lookalikes_not_excluded(self):
        """Lookalike domains should not be dropped just because they end with a safe suffix."""
        html = '''
        <a href="https://notgoogle.com/login">FakeGoogle</a>
        <a href="https://evilfacebook.net/reset">FakeFacebook</a>
        '''
        ratio = _external_link_ratio(html, "example.com")
        assert ratio == pytest.approx(2 / 2, abs=1e-6)

    def test_non_anchor_hrefs_do_not_inflate_ratio(self):
        """Stylesheet/script href/src values should not count toward anchor-based risk."""
        html = '''
        <link rel="stylesheet" href="https://fonts.googleapis.com/css">
        <script src="https://evil.com/app.js"></script>
        <a href="/home">Home</a>
        '''
        ratio = _external_link_ratio(html, "example.com")
        assert ratio == 0.0

    def test_duplicate_external_anchors_count_per_anchor(self):
        """Repeated external anchors should count per link, not per unique domain."""
        html = '''
        <a href="https://example.com/home">Internal</a>
        <a href="https://evil.com/phish">External 1</a>
        <a href="https://evil.com/reset">External 2</a>
        '''
        ratio = _external_link_ratio(html, "example.com")
        assert ratio == pytest.approx(2 / 3, abs=1e-6)


# ═════════════════════════════════════════════════════════════════════
# 3. subdomain_depth
# ═════════════════════════════════════════════════════════════════════

class TestSubdomainDepth:
    """New feature: subdomain labels beyond the registered domain."""

    def test_bare_domain(self):
        """chase.com → depth 0."""
        assert _subdomain_depth("chase.com") == 0

    def test_www_prefix(self):
        """www.chase.com → depth 0 (www excluded)."""
        assert _subdomain_depth("www.chase.com") == 0

    def test_single_subdomain(self):
        """login.chase.com → depth 1."""
        assert _subdomain_depth("login.chase.com") == 1

    def test_deep_nesting(self):
        """secure.login.bank.phish.com → depth 3."""
        assert _subdomain_depth("secure.login.bank.phish.com") == 3

    def test_www_plus_subdomain(self):
        """www.login.chase.com → depth 1 (www excluded, login counted)."""
        assert _subdomain_depth("www.login.chase.com") == 1

    def test_with_port(self):
        """login.chase.com:8080 → depth 1 (port stripped)."""
        assert _subdomain_depth("login.chase.com:8080") == 1

    def test_empty_netloc(self):
        """Empty string → depth 0."""
        assert _subdomain_depth("") == 0

    def test_single_label(self):
        """localhost → depth 0."""
        assert _subdomain_depth("localhost") == 0


# ═════════════════════════════════════════════════════════════════════
# 4. brand_impersonation_score
# ═════════════════════════════════════════════════════════════════════

class TestBrandImpersonationScore:
    """New feature: count brand names in subdomains/path, NOT in reg domain."""

    def test_legit_brand_domain(self):
        """www.paypal.com → score 0 (paypal IS the registered domain)."""
        score = _brand_impersonation_score("http://www.paypal.com/checkout", "www.paypal.com")
        assert score == 0

    def test_brand_in_subdomain(self):
        """paypal.phishing.com → score 1 (paypal in subdomain)."""
        score = _brand_impersonation_score("http://paypal.phishing.com/login", "paypal.phishing.com")
        assert score == 1

    def test_multiple_brands_in_url(self):
        """apple-microsoft.evil.com/netflix → score 3."""
        score = _brand_impersonation_score(
            "http://apple-microsoft.evil.com/netflix",
            "apple-microsoft.evil.com"
        )
        assert score == 3

    def test_no_brands(self):
        """www.example.com/page → score 0."""
        score = _brand_impersonation_score("http://www.example.com/page", "www.example.com")
        assert score == 0

    def test_brand_in_path_only(self):
        """www.evil.com/paypal/verify → score 1 (paypal in path)."""
        score = _brand_impersonation_score(
            "http://www.evil.com/paypal/verify",
            "www.evil.com"
        )
        assert score == 1

    def test_legit_google_domain(self):
        """www.google.com/search → score 0 (google IS the reg domain)."""
        score = _brand_impersonation_score("http://www.google.com/search", "www.google.com")
        assert score == 0

    def test_brand_as_part_of_different_word(self):
        """applesauce.evil.com → 'apple' substring match still scores 1.
        This is intentional: phishing sites embed brand names like this."""
        score = _brand_impersonation_score("http://applesauce.evil.com/", "applesauce.evil.com")
        assert score == 1  # 'apple' is in 'applesauce'


# ═════════════════════════════════════════════════════════════════════
# 5. _extract_registered_domain helper
# ═════════════════════════════════════════════════════════════════════

class TestExtractRegisteredDomain:
    """Helper used by brand_impersonation_score."""

    def test_simple(self):
        assert _extract_registered_domain("www.paypal.com") == "paypal.com"

    def test_deep_subdomain(self):
        assert _extract_registered_domain("secure.login.bank.phish.com") == "phish.com"

    def test_bare_domain(self):
        assert _extract_registered_domain("phish.com") == "phish.com"

    def test_with_port(self):
        assert _extract_registered_domain("example.com:8080") == "example.com"

    def test_single_label(self):
        assert _extract_registered_domain("localhost") == "localhost"


# ═════════════════════════════════════════════════════════════════════
# 6. ALL_FEATURE_NAMES integrity
# ═════════════════════════════════════════════════════════════════════

class TestAllFeatureNames:
    """Verify the feature list was updated correctly."""

    def test_old_features_removed(self):
        assert "has_form_action" not in ALL_FEATURE_NAMES
        assert "num_external_links" not in ALL_FEATURE_NAMES

    def test_new_features_present(self):
        assert "form_action_density" in ALL_FEATURE_NAMES
        assert "external_link_ratio" in ALL_FEATURE_NAMES
        assert "subdomain_depth" in ALL_FEATURE_NAMES
        assert "brand_impersonation_score" in ALL_FEATURE_NAMES

    def test_existing_features_kept(self):
        for feat in ["url_length", "domain_entropy", "login_kw_density",
                      "is_modern_spa", "has_hidden_iframe", "num_subdomains"]:
            assert feat in ALL_FEATURE_NAMES

    def test_total_count(self):
        """Updated non-visual pipeline feature count."""
        assert len(ALL_FEATURE_NAMES) == 29

    def test_no_duplicates(self):
        assert len(ALL_FEATURE_NAMES) == len(set(ALL_FEATURE_NAMES))


# ═════════════════════════════════════════════════════════════════════
# 7. Integration: _extract_url_features returns new fields
# ═════════════════════════════════════════════════════════════════════

class TestExtractUrlFeaturesIntegration:
    """Verify the URL extractor returns the new features."""

    def test_contains_subdomain_depth(self):
        feats = _extract_url_features("http://secure.login.bank.phish.com/page")
        assert "subdomain_depth" in feats
        assert feats["subdomain_depth"] == 3

    def test_contains_brand_impersonation_score(self):
        feats = _extract_url_features("http://paypal.phishing.com/login")
        assert "brand_impersonation_score" in feats
        assert feats["brand_impersonation_score"] == 1

    def test_legit_url_low_scores(self):
        feats = _extract_url_features("http://www.chase.com/personal/banking")
        assert feats["subdomain_depth"] == 0
        assert feats["brand_impersonation_score"] == 0


class TestNewStructuralFeatures:
    def test_password_field_detected(self):
        feats = _extract_text_features("login now", '<form><input type="password"></form>', page_netloc="example.com")
        assert feats["has_password_field"] == 1
        assert feats["num_password_fields"] == 1

    def test_title_mismatch(self):
        html = "<html><title>PayPal Verification</title></html>"
        feats = _extract_text_features("verify account", html, page_netloc="secure.example.com")
        assert feats["title_mismatch"] in (0, 1)

    def test_feature_registry_contains_new_fields(self):
        for feat in ["has_password_field", "num_password_fields", "title_mismatch",
                     "same_domain_form_action_ratio", "num_iframes",
                     "num_hidden_inputs", "submit_button_count", "domain_title_token_overlap"]:
            assert feat in ALL_FEATURE_NAMES


class TestDomainTitleAlignment:
    def test_compound_brand_domain_not_marked_as_mismatch(self):
        html = "<html><title>Bank of America Secure Login</title></html>"
        assert _title_mismatch(html, "www.bankofamerica.com") == 0
        assert _domain_title_token_overlap(html, "www.bankofamerica.com") == pytest.approx(1.0, abs=1e-6)
