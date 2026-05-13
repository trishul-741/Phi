"""
Pre/Post-Classification Safety Filter for PhishGuard (v1).

This module implements deterministic safeguards around the ML model:
1. Tranco Top 100K Domain Whitelist (reduces false positives on popular sites).
2. Lexical Heuristic Pre-filters (catches obvious phishing features before
   evaluation, or boosts borderline models scores).

Integration:
In production (e.g., inference.py or an API worker), the flow should be:
    
    from ml.safe_filter import SafeFilter
    from ml.config import cfg
    
    safeguard = SafeFilter()
    
    def predict_url(url, model, features):
        ...
        raw_model_score = model(features).sigmoid().item()
        final_score, reason = safeguard.predict(url, raw_model_score)
        
        is_phishing = final_score >= cfg.DECISION_THRESHOLD
        return is_phishing, final_score, reason
"""

import os
import re
import csv
import logging
import zipfile
import urllib.request
import io
import unittest

import tldextract

from ml.config import cfg

logger = logging.getLogger("safe_filter")

# Common brands often impersonated in phishing attacks
# Expand this list in production based on CTI feeds.
TARGETED_BRANDS = {
    "paypal", "apple", "microsoft", "google", "amazon", 
    "facebook", "netflix", "chase", "bankofamerica", "wellsfargo",
    "linkedin", "dhl", "fedex", "instagram", "whatsapp",
}

class SafeFilter:
    def __init__(self, top_k=100_000, cache_dir=None):
        self.top_k = top_k
        self.cache_dir = cache_dir or cfg.OUTPUT_DIR
        self.tranco_path = os.path.join(self.cache_dir, "tranco_top1m.csv")
        self.top_domains = self._load_or_download_tranco()
        
        # We pre-initialize the tldextract fetcher so it doesn't block later
        # using the default caching behavior of tldextract.
        self.extract = tldextract.TLDExtract()

    def _load_or_download_tranco(self) -> set:
        """
        Loads the Tranco top 1M list, downloading it if it doesn't exist.
        Returns a set of the top `self.top_k` registered domains.
        """
        if not os.path.exists(self.tranco_path):
            logger.info("Tranco list not found. Downloading from https://tranco-list.eu/top-1m.csv.zip ...")
            os.makedirs(self.cache_dir, exist_ok=True)
            try:
                # Tranco provides a static zip of their latest daily list
                url = "https://tranco-list.eu/top-1m.csv.zip"
                req = urllib.request.urlopen(url, timeout=30)
                with zipfile.ZipFile(io.BytesIO(req.read())) as z:
                    # Usually there's only one CSV in the zip, named top-1m.csv or similar
                    csv_filename = z.namelist()[0]
                    with z.open(csv_filename) as f_in, open(self.tranco_path, "wb") as f_out:
                        f_out.write(f_in.read())
                logger.info(f"Successfully downloaded and cached Tranco list to {self.tranco_path}")
            except Exception as e:
                logger.warning(f"Failed to download Tranco list ({e}). Whitelist bypass disabled.")
                return set()
        
        logger.info(f"Loading top {self.top_k} domains from {self.tranco_path} ...")
        top_domains = set()
        try:
            with open(self.tranco_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    if i >= self.top_k:
                        break
                    if len(row) >= 2:
                        top_domains.add(row[1].lower().strip())
        except Exception as e:
            logger.error(f"Error parsing Tranco list: {e}")
            
        return top_domains

    def predict(self, url: str, model_score: float) -> tuple[float, str]:
        """
        Apply deterministic safety checks around the ML model score.
        
        Returns:
            (final_score: float, reason_code: str)
        """
        url_lower = url.lower()
        extracted = self.extract(url_lower)
        
        # registered_domain will be something like "google.com" or "bbc.co.uk"
        registered_domain = f"{extracted.domain}.{extracted.suffix}" if extracted.suffix else extracted.domain
        
        # --- 1. ALEXA / TRANCO TOP DOMAIN CHECK ---
        if registered_domain in self.top_domains:
            # High confidence it is legitimate
            return (0.05, "whitelist_bypass")
            
        # --- 2. HEURISTIC PRE-FILTERS ---
        # Is it an IP address hostname? (tldextract parses IPs into the `domain` field with no suffix)
        is_ip = re.match(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$", extracted.domain) and not extracted.suffix
        if is_ip:
            # IP hostnames are highly suspicious for typical consumer web traffic
            return (max(0.97, model_score), "ip_hostname")
            
        adjusted_score = model_score
        reasons = []
        
        # Hostname length check
        hostname = f"{extracted.subdomain}.{registered_domain}" if extracted.subdomain else registered_domain
        if len(hostname) > 50:
            adjusted_score += 0.15
            reasons.append("hostname_length")
            
        # Subdomain depth check
        if extracted.subdomain:
            sub_count = len(extracted.subdomain.split("."))
            if sub_count > 3:
                adjusted_score += 0.10
                reasons.append("subdomain_depth")
                
        # Brand impersonation check (Brand in URL but NOT the registered domain)
        for brand in TARGETED_BRANDS:
            if brand in url_lower and extracted.domain != brand:
                adjusted_score += 0.20
                reasons.append("brand_impersonation")
                break
                
        # --- 3. FINAL ADJUSTMENT ---
        if adjusted_score > model_score:
            final_score = min(1.0, adjusted_score)
            return (final_score, ",".join(reasons))
            
        return (model_score, "model_only")


# ══════════════════════════════════════════════════════════════════════
# Unit Tests
# ══════════════════════════════════════════════════════════════════════

class TestSafeFilter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Initialise SafeFilter. We use a small mock set for top_domains to speed up tests.
        cls.sf = SafeFilter(top_k=0) # Do not load actual Tranco file limits
        cls.sf.top_domains = {"google.com", "microsoft.com"}
        
    def test_whitelist_bypass(self):
        # Branch 1
        score, reason = self.sf.predict("https://www.google.com/login", 0.85)
        self.assertEqual(score, 0.05)
        self.assertEqual(reason, "whitelist_bypass")
        
        score, reason = self.sf.predict("http://office.microsoft.com/", 0.99)
        self.assertEqual(score, 0.05)
        self.assertEqual(reason, "whitelist_bypass")

    def test_ip_hostname(self):
        # Branch 2a (IP as hostname)
        score, reason = self.sf.predict("http://192.168.1.1/login.php", 0.20)
        self.assertEqual(score, 0.97) # Gets bumped to 0.97
        self.assertEqual(reason, "ip_hostname")
        
        score, reason = self.sf.predict("http://10.0.0.5/", 0.99)
        self.assertEqual(score, 0.99) # Higher model score preserved
        self.assertEqual(reason, "ip_hostname")

    def test_heuristic_bump_hostname_length(self):
        # Branch 2b (Hostname > 50 chars)
        long_sub = "a" * 45
        url = f"https://{long_sub}.example.com/path"
        score, reason = self.sf.predict(url, 0.50)
        self.assertAlmostEqual(score, 0.65)
        self.assertIn("hostname_length", reason)

    def test_heuristic_bump_subdomain_depth(self):
        # Branch 2c (> 3 subdomains)
        url = "https://one.two.three.four.example.com/path"
        score, reason = self.sf.predict(url, 0.50)
        # Length of one.two.three.four.example.com is 28 chars (<=50), 4 subdomains.
        self.assertAlmostEqual(score, 0.60)
        self.assertIn("subdomain_depth", reason)

    def test_heuristic_bump_brand_impersonation(self):
        # Branch 2d (Brand in subdomain/path, not domain)
        url = "https://paypal.secure-update.com/login"
        score, reason = self.sf.predict(url, 0.50)
        self.assertAlmostEqual(score, 0.70)
        self.assertIn("brand_impersonation", reason)
        
    def test_multiple_heuristics(self):
        # > 3 subdomains AND > 50 chars AND brand impersonation
        long_sub = ("a" * 20) + ".paypal.login.secure"
        url = f"https://{long_sub}.example.com/path"
        score, reason = self.sf.predict(url, 0.50)
        
        # 0.50 + 0.15 (len) + 0.10 (depth) + 0.20 (brand) = 0.95
        self.assertAlmostEqual(score, 0.95)
        self.assertIn("hostname_length", reason)
        self.assertIn("subdomain_depth", reason)
        self.assertIn("brand_impersonation", reason)
        
        # Ensure it clamps at 1.0
        score2, _ = self.sf.predict(url, 0.80)
        self.assertEqual(score2, 1.0)

    def test_model_only(self):
        # Branch 3 (Normal unseen domain with no heuritsic triggers)
        url = "https://www.unknown-domain-test.com/about"
        score, reason = self.sf.predict(url, 0.45)
        self.assertEqual(score, 0.45)
        self.assertEqual(reason, "model_only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
