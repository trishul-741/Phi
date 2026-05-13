# PhishGuard Heavy-Data Evaluation Plan

This plan is for large-scale, defensive evaluation only. Do not generate, host, modify, deploy, or interact with phishing pages. Do not collect credentials. Do not bypass login protections. Do not use browser automation against live phishing-feed URLs.

## Objective

Evaluate PhishGuard with 10,000 to 20,000+ URLs using a realistic but evaluation-friendly mix:

- 70% legitimate/safe URLs.
- 15% public phishing, official security-test, or malicious-labeled dataset URLs.
- 15% synthetic suspicious URLs using reserved domains only.

This distribution keeps false-positive measurement central while providing enough risky examples to measure recall, SafeFilter behavior, and Stage 1 to Stage 2 escalation.

## Dataset Mix

| Class | Percentage | 10,000 URL Run | 20,000 URL Run |
|---|---:|---:|---:|
| Legitimate / safe | 70% | 7,000 | 14,000 |
| Phishing / malicious / official test | 15% | 1,500 | 3,000 |
| Synthetic suspicious | 15% | 1,500 | 3,000 |

Production note: real browsing traffic may be even more safe-heavy, often 90-95% legitimate. The final report should include both this 70/30 evaluation view and, where possible, a reweighted production-impact estimate.

## A. Legitimate Websites

Target: 70%.

Sources:

- Tranco top domains.
- Banking homepages only.
- SaaS platforms.
- E-commerce sites.
- News websites.
- Government websites.
- Education/documentation sites.
- Login-heavy legitimate pages.

Safe collection rules:

- Use public pages only.
- Do not log into personal accounts.
- Do not submit forms.
- Do not scrape private dashboards.
- Label each row with category metadata such as `banking`, `saas`, `ecommerce`, `news`, `government`, `login`, `cdn_heavy`, or `spa`.

Why this matters:

- False positives are the biggest production trust risk.
- SafeFilter, whitelist, threshold calibration, and rescan behavior must be tested mostly against legitimate traffic.

## B. Phishing / Malicious / Official Test

Target: 15%.

Allowed sources:

- PhishTank URL datasets.
- OpenPhish URL datasets.
- Kaggle phishing URL datasets.
- Google Safe Browsing official test URLs.
- AMTSO phishing test page.
- Microsoft SmartScreen demo/test pages.

Safe handling:

- Prefer API-only URL evaluation for PhishTank/OpenPhish/Kaggle URLs.
- Do not open live phishing-feed URLs in a browser.
- Do not submit credentials.
- Do not download payloads.
- Do not bypass browser warnings.
- If Stage 2 content is needed, use sanitized offline fixtures or dataset-provided text, not live phishing pages.

## C. Synthetic Suspicious URLs

Target: 15%.

Use reserved domains only:

```text
paypal-login-secure.example.com
account-verify-bank.example.net
login-update-security.example.org
microsoft-365-password-reset.example.com
apple-id-verify-login.example.net
secure-wallet-update.example.org
http://192.168.1.10/login.php
```

Purpose:

- Stress-test lexical detection.
- Validate `brand_impersonation_score`.
- Validate `subdomain_depth`.
- Validate `ip_hostname`.
- Validate `plaintext_http`.
- Validate `credential_lure_terms`.
- Confirm SafeFilter does not suppress strong lexical evidence.

## Pipeline

1. Collect raw URLs from approved safe sources.
2. Normalize URLs.
3. Deduplicate by normalized URL.
4. Deduplicate or cap by registered domain to avoid overrepresenting one provider.
5. Assign labels:
   - `safe`
   - `phishing`
   - `phishing_test`
   - `phishing_synthetic`
   - `suspicious_synthetic`
6. Add metadata:
   - `source`
   - `category`
   - `subcategory`
   - `collection_date`
   - `should_browser_test`
   - `should_stage2_test`
7. Write normalized dataset to CSV.
8. Run Stage 1 API batch on all rows.
9. Run Stage 2 API batch only on safe fixtures, synthetic suspicious rows, and sanitized phishing fixtures.
10. Run browser automation only on safe URLs, official test pages, and local benign fixtures.
11. Store JSONL result logs.
12. Generate final report.

## Canonical Dataset Schema

```csv
url,label,source,category,subcategory,should_browser_test,should_stage2_test,notes
https://github.com,safe,tranco,saas,developer,true,true,
http://paypal-login-secure.example.com,phishing_synthetic,synthetic,lexical,brand_impersonation,false,true,
```

## Execution Strategy

API batch:

- Run all 10k-20k URLs through `/v1/precheck`.
- Run selected rows through `/v1/scan`.
- Record scores, verdicts, thresholds, reason codes, signals, and latency.

Browser subset:

- Use 300-1,000 safe/official/local-fixture URLs.
- Use a dedicated Chrome profile.
- Load `extension/dist`.
- Capture UI state and screenshots.
- Do not automate live phishing-feed URLs.

Parallel execution:

- Stage 1 workers: 20-100 concurrent workers.
- Stage 2 workers: 2-8 workers depending on model hardware.
- Browser workers: 1-5 max.

## Metrics

Compute:

- Accuracy.
- Precision.
- Recall.
- F1-score.
- False Positive Rate.
- False Negative Rate.
- ROC-AUC.
- PR-AUC.
- Stage 1 latency p50/p95/p99.
- Stage 2 latency p50/p95/p99.
- Total latency p50/p95/p99.
- Stage 1 bypass count.
- Stage 2 escalation count.
- Stage conflict count.
- SafeFilter reason-code counts.
- Whitelist bypass count.

Binary mapping:

- Actual safe: legitimate rows.
- Actual risky: phishing, official test, malicious-labeled, and synthetic suspicious rows.
- Predicted safe: `safe`.
- Predicted risky: `suspicious`, `malicious`, or `needs_review`.

## Error Analysis

False positives:

- Login pages.
- Banking homepages.
- CDN-heavy pages.
- Long URLs.
- SPA pages.
- Forms/password fields.
- Brand-owned legitimate domains.

False negatives:

- Brand impersonation missed.
- IP host missed.
- Suspicious subdomain missed.
- Credential-lure language missed.
- SafeFilter bypassed risk.
- Stage 1 failed to trigger Stage 2.
- Threshold too high.

## Production Readiness Criteria

Minimum:

- False Positive Rate on legitimate URLs below 3-5%.
- Official security test URLs warned or blocked.
- Phishing/test recall above 90-95%.
- Stage 1 p95 latency below 100 ms.
- Stage 2 p95 latency below 5 seconds.
- No credential collection.
- No sensitive data logging.
- No critical dashboard mismatch.
- Rescan does not convert clearly safe pages to malicious without evidence.

Preferred:

- False Positive Rate below 1-2%.
- Phishing/test recall above 95%.
- Stage 1 p95 below 50 ms.
- Stage 2 p95 below 3 seconds.

## Final Report Sections

1. Executive summary.
2. Dataset composition.
3. Environment.
4. Detection metrics.
5. Confusion matrix.
6. ROC-AUC and PR-AUC.
7. False-positive analysis.
8. False-negative analysis.
9. Stage 1 vs Stage 2 contribution.
10. SafeFilter impact.
11. Latency and throughput.
12. Extension UI findings.
13. Security/privacy observations.
14. Production readiness decision.
15. Recommendations.
