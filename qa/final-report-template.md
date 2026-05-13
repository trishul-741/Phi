# PhishGuard Real-World QA Report

## Objective

Describe detection accuracy, false-positive reduction, false-negative coverage, extension UX, two-stage scanning, latency, logging, and SafeFilter/whitelist goals.

## Test Environment

- Date:
- Tester:
- OS:
- Browser:
- Extension build:
- Backend commit:
- Model checkpoint:
- Calibration file:
- Threshold:
- Test mode:
- Device ID:

## Test Dataset

| Category | Count | Notes |
|---|---:|---|
| Legitimate high-trust |  |  |
| Login-heavy legitimate |  |  |
| Official security test |  |  |
| Synthetic suspicious |  |  |

## Test Execution Summary

| Total | Passed | Failed | Safe Sites Blocked | Test URLs Missed |
|---:|---:|---:|---:|---:|
|  |  |  |  |  |

## Confusion Matrix

| | Predicted Safe | Predicted Suspicious/Malicious |
|---|---:|---:|
| Actual Safe | TN | FP |
| Actual Test/Risky | FN | TP |

## Metrics

- Accuracy:
- Precision:
- Recall:
- F1-score:
- False Positive Rate:
- False Negative Rate:
- Average Stage 1 latency:
- Average Stage 2 latency:
- Average total latency:
- p95 total latency:

## False Positive Analysis

List each legitimate site incorrectly warned or blocked, with score, threshold, reason code, and suspected cause.

## False Negative Analysis

List each official test/synthetic case missed, with score, threshold, reason code, and suspected cause.

## UI Bugs Found

| Bug ID | Severity | Area | Summary | Status |
|---|---|---|---|---|
|  |  |  |  |  |

## Performance Results

Summarize Stage 1, Stage 2, and total latency. Include p50, p90, p95, and max.

## Security Observations

Document credential handling, password redaction, extension permissions, privacy, storage behavior, and whether any sensitive data was collected.

## Recommendations

Prioritize fixes by risk and user impact.

## Acceptance Decision

Accepted / Accepted with Conditions / Rejected
