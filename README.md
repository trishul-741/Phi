# PhishGuard

PhishGuard is now wired as a non-visual phishing detection product across three layers:

- `api.py` + `backend/`: FastAPI contract surface for Stage 1 precheck, Stage 2 scan, feedback, report, history, and whitelist routes.
- `extension/`: Chrome Manifest V3 extension with two-stage scanning, local storage, overlay UI, popup, options page, cache TTLs, and a dashboard bridge.
- `dashboard/`: Next.js dashboard for overview, reports, phishing history, safe-but-reported cases, whitelist management, feedback, and analytics.

## Architecture alignment

This implementation stays aligned with the current backend model path only:

1. URL and page text/HTML arrive
2. lexical, textual, and structural features are engineered
3. the non-visual multimodal fusion model runs
4. calibration is applied
5. the safe-filter adjusts the score
6. the API returns verdict, scores, grouped non-visual signals, filter reason, and architecture

There is no screenshot model, OCR branch, Siamese network, logo verification, or visual target field in this scaffold.

## Key folders

```text
backend/                  FastAPI schemas, Stage 1 logic, grouped signal mapping, JSON persistence
dashboard/                Next.js app router dashboard
extension/                MV3 extension project (React + TypeScript + Vite/CRX)
packages/shared/          Shared TypeScript contracts and storage models
api.py                    FastAPI entrypoint
data/phishguard_store.json  Local JSON persistence created at runtime
```

## Running the backend

1. Install Python dependencies from `requirements.txt`.
2. Start the API:

```bash
uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

Available routes:

- `POST /v1/precheck`
- `POST /v1/scan`
- `POST /v1/feedback`
- `GET /v1/report/{scan_id}`
- `GET /v1/report/by-url?url=...`
- `GET /v1/history`
- `GET /v1/feedback`
- `POST /v1/whitelist`
- `DELETE /v1/whitelist/{domain}`
- `GET /v1/whitelist`

## Running the dashboard

1. Install workspace dependencies from the repo root:

```bash
npm install
```

2. Start the dashboard:

```bash
npm run dev:dashboard
```

Default API base URL is `http://127.0.0.1:8000`. Override with:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

## Running the extension

1. Install workspace dependencies from the repo root if you have not already:

```bash
npm install
```

2. Build the extension:

```bash
npm run build:extension
```

Icon assets are generated in:

```text
extension/icons/concept-1-shield-check
extension/icons/concept-2-shield-warning
extension/icons/concept-3-shield-monogram
```

The default extension icon family is concept 1 (`shield + check / trust`), exported to:

```text
extension/icons/icon-16.png
extension/icons/icon-32.png
extension/icons/icon-48.png
extension/icons/icon-128.png
```

To regenerate the full icon family later:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File extension\scripts\generate-icons.ps1
```

3. In Chrome, open `chrome://extensions`, enable Developer mode, click `Load unpacked`, and select:

```text
E:\Phi\extension\dist
```

Do not select `E:\Phi\extension`, because that folder contains the TypeScript/Vite source project and does not contain a loadable `manifest.json`. Chrome must be pointed at the built output folder, which contains:

- `extension/dist/manifest.json`
- `extension/dist/popup.html`
- `extension/dist/options.html`
- compiled JS/CSS/assets

4. If you rebuild the extension later, go back to `chrome://extensions` and click the refresh icon on the loaded extension.

Current extension behavior:

- Stage 1 safe pages continue browsing normally with only the passive indicator when enabled.
- Stage 2 uses the backend's final decision contract and never upgrades from raw or calibrated scores alone.
- If Stage 1 is safe but Stage 2 escalates to a high-risk result, PhishGuard stores and renders that as `needs_review` with `consistency_status=conflict` instead of forcing an immediate hard malicious block.

The extension stores these local collections in `chrome.storage.local`:

- `scanHistory`
- `flaggedPhishingUrls`
- `safeReportedAsPhishing`
- `userFeedbackQueue`
- `trustedDomains`
- `scanCache`

## Local dashboard integration

When the dashboard is opened from the extension, the content script exposes a local snapshot bridge on the dashboard origin. That lets the dashboard read device-local extension state for:

- local phishing history
- conflicting `needs_review` scans
- safe-but-user-reported phishing records
- pending feedback queue
- trusted domains

If the bridge is unavailable, the dashboard falls back to synced backend records.

## Notes

- Stage 1 is URL-only and uses trusted-domain plus lightweight lexical heuristics.
- Stage 2 submits only the required non-visual page data: `url`, `title`, `text_clean`, and truncated `text_raw`.
- Full scans wait for `document.readyState === "complete"` plus a short DOM quiet window before extracting content. The debounce and stabilization timings are configurable from the extension options page.
- Password values are not collected by the extension extractor.
- Safe and risky cache TTLs are configurable from the extension options page.
- The dashboard includes a dedicated `Needs Review` history page for Stage 1 safe to Stage 2 malicious conflicts.
- The checked-in Python virtual environment currently points to a missing interpreter path, so recreate or repair it before running the backend locally.
