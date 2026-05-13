22# PhishGuard QA Plan

This folder contains safe, defensive QA assets for real-world PhishGuard testing. Do not use these assets to generate, host, modify, deploy, or interact with phishing pages. Do not collect credentials, bypass login protections, attack third-party sites, or browse live phishing kits.

## Scope

The test plan evaluates:

- Detection accuracy on real-world URLs.
- False positives on legitimate websites.
- False negatives on official security test pages and synthetic URL strings.
- Extension UI behavior.
- Two-stage scanning behavior.
- Latency and user experience.
- Logging and dashboard correctness.
- SafeFilter and whitelist behavior.

## Environment Setup

Start the backend:

```powershell
cd E:\Phi
.\venv\Scripts\Activate.ps1
uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

Verify health:

```powershell
curl.exe http://127.0.0.1:8000/health
```

Build and reload the extension:

```powershell
cd E:\Phi
npm run build:extension
```

Then open `chrome://extensions`, enable Developer mode, load or reload `E:\Phi\extension\dist`.

## Safe API Smoke Runner

Run:

```powershell
npm run qa:api
```

Optional settings:

```powershell
$env:PHISHGUARD_API_BASE_URL="http://127.0.0.1:8000"
$env:PHISHGUARD_QA_DEVICE_ID="qa-device"
$env:PHISHGUARD_QA_CASES="qa/test-cases.json"
$env:PHISHGUARD_QA_OUTPUT_DIR="qa/results"
npm run qa:api
```

The runner writes JSON reports to `qa/results/`.

## Heavy-Data Pipeline Commands

Generate safe and phishing/test datasets from the local `metadata.csv`:

```powershell
npm run qa:generate-labeled -- --input metadata.csv --safeCount 14000 --phishingCount 3000 --safeOutput qa/datasets/normalized/safe.csv --phishingOutput qa/datasets/normalized/phishing.csv
```

Generate a synthetic suspicious slice:

```powershell
npm run qa:generate-synthetic -- --count 1500 --output qa/datasets/raw/synthetic-suspicious.csv
```

Normalize any CSV that follows the QA schema:

```powershell
npm run qa:normalize -- --input qa/datasets/raw/synthetic-suspicious.csv --output qa/datasets/normalized/synthetic-suspicious.csv
```

Build the full 70/15/15 evaluation CSV after you have normalized safe, phishing/test, and synthetic source files:

```powershell
npm run qa:build-dataset -- --safe qa/datasets/normalized/safe.csv --phishing qa/datasets/normalized/phishing.csv --synthetic qa/datasets/normalized/synthetic-suspicious.csv --total 20000 --output qa/datasets/normalized/phishguard-eval-20k.csv
```

Run a large API batch:

```powershell
npm run qa:batch -- --input qa/datasets/normalized/phishguard-eval-20k.csv --workers 16 --output qa/results/jsonl/api-eval-20k.jsonl
```

Compute metrics:

```powershell
npm run qa:metrics -- --input qa/results/jsonl/api-eval-20k.jsonl --output qa/reports/metrics-20k.json
```

Generate a markdown report:

```powershell
npm run qa:report -- --metrics qa/reports/metrics-20k.json --output qa/reports/phishguard-eval-20k.md
```

Recommended large dataset mix:

```text
70% legitimate / safe
15% phishing / malicious / official test
15% synthetic suspicious
```

## Manual Browser QA Checklist

- Safe page shows no blocking overlay.
- Warning page shows evidence chips.
- Block page prevents unsafe interaction unless policy allows continue.
- Rescan shows the actual Stage 2 system result.
- Continue Surfing works for safe pages.
- Full dashboard opens the matching report.
- Logs/history match local extension state and backend records.
- Whitelist add/remove changes future decisions.
- Backend-down state shows a friendly error.
- Model timeout state shows a friendly error.

## Large-Scale Dataset Notes

For the heavy-data evaluation plan, use:

| Class | Percentage | 10,000 URLs | 20,000 URLs |
|---|---:|---:|---:|
| Legitimate / safe | 70% | 7,000 | 14,000 |
| Phishing / malicious / official test | 15% | 1,500 | 3,000 |
| Synthetic suspicious | 15% | 1,500 | 3,000 |

See `qa/heavy-data-testing-plan.md` and `qa/dataset-mix.json`.

## Dataset Notes

- Legitimate high-trust examples: Google, Microsoft, GitHub, Wikipedia, Amazon, Flipkart, LinkedIn, Netflix, PayPal.
- Login-heavy legitimate examples: Google login, Microsoft login, GitHub login, LinkedIn login, banking homepages only.
- Official test pages: Google Safe Browsing test links, Microsoft SmartScreen demo pages, AMTSO phishing test page.
- Synthetic suspicious examples must use reserved domains such as `example.com` and must not be hosted as credential collection pages.

## Acceptance Criteria

- False Positive Rate on legitimate sites below 3-5%.
- Official phishing/security test pages are warned or blocked.
- Popular safe websites are not blocked.
- Login-heavy legitimate sites are not hard-blocked from one ordinary login form alone.
- Rescan does not convert clearly safe pages to malicious without evidence.
- Dashboard logs are correct.
- Average Stage 1 and Stage 2 latency is acceptable.
- No credentials or sensitive user data are collected.
