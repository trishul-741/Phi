import { parseArgs, readCsv, toCsv, normalizeUrl, writeText } from "./lib.mjs";

const args = parseArgs();
const input = args.input ?? "metadata.csv";
const safeOutput = args.safeOutput ?? "qa/datasets/normalized/safe.csv";
const phishingOutput = args.phishingOutput ?? "qa/datasets/normalized/phishing.csv";
const safeCount = Number(args.safeCount ?? 14000);
const phishingCount = Number(args.phishingCount ?? 3000);

const officialSecurityTests = [
  {
    url: "http://testsafebrowsing.appspot.com/s/phishing.html",
    label: "phishing",
    source: "official_test",
    category: "official_security_test",
    subcategory: "google_safe_browsing",
    should_browser_test: "true",
    should_stage2_test: "false",
    notes: "Official Safe Browsing phishing test URL.",
  },
  {
    url: "https://www.amtso.org/feature-settings-check-phishing-page/",
    label: "phishing",
    source: "official_test",
    category: "official_security_test",
    subcategory: "amtso",
    should_browser_test: "true",
    should_stage2_test: "false",
    notes: "Official AMTSO phishing test page.",
  },
  {
    url: "https://demo.smartscreen.msft.net/",
    label: "phishing",
    source: "official_test",
    category: "official_security_test",
    subcategory: "microsoft_smartscreen",
    should_browser_test: "true",
    should_stage2_test: "false",
    notes: "Official Microsoft SmartScreen demo landing page.",
  },
];

const headers = [
  "url",
  "label",
  "source",
  "category",
  "subcategory",
  "should_browser_test",
  "should_stage2_test",
  "title",
  "text_clean",
  "text_raw",
  "notes",
];

function normalizeMetadataRow(row, overrides) {
  return {
    url: normalizeUrl(row.url),
    label: overrides.label,
    source: row.source || overrides.source,
    category: overrides.category,
    subcategory: row.source || overrides.subcategory,
    should_browser_test: overrides.should_browser_test,
    should_stage2_test: overrides.should_stage2_test,
    title: "",
    text_clean: "",
    text_raw: "",
    notes: overrides.notes,
  };
}

function uniqueTake(rows, count) {
  const seen = new Set();
  const out = [];
  for (const row of rows) {
    if (!row.url || seen.has(row.url)) {
      continue;
    }
    seen.add(row.url);
    out.push(row);
    if (out.length >= count) {
      break;
    }
  }
  return out;
}

const rows = await readCsv(input);
const safeRows = uniqueTake(
  rows
    .filter((row) => row.label === "legitimate")
    .map((row) => normalizeMetadataRow(row, {
      label: "safe",
      source: "metadata",
      category: "legitimate",
      subcategory: "tranco",
      should_browser_test: "false",
      should_stage2_test: "false",
      notes: "Legitimate URL from local metadata dataset.",
    })),
  safeCount,
);

const phishingRows = uniqueTake(
  [
    ...officialSecurityTests,
    ...rows
      .filter((row) => row.label === "phishing")
      .map((row) => normalizeMetadataRow(row, {
        label: "phishing",
        source: "metadata",
        category: "phishing",
        subcategory: "url_feed",
        should_browser_test: "false",
        should_stage2_test: "false",
        notes: "Phishing-labeled URL from local metadata. API-only; do not browse live.",
      })),
  ],
  phishingCount,
);

if (safeRows.length < safeCount) {
  throw new Error(`Only found ${safeRows.length} unique safe rows, but ${safeCount} requested.`);
}

if (phishingRows.length < phishingCount) {
  throw new Error(`Only found ${phishingRows.length} unique phishing rows, but ${phishingCount} requested.`);
}

await writeText(safeOutput, `${toCsv(safeRows, headers)}\n`);
await writeText(phishingOutput, `${toCsv(phishingRows, headers)}\n`);

console.log(`Wrote ${safeRows.length} safe rows to ${safeOutput}`);
console.log(`Wrote ${phishingRows.length} phishing/test rows to ${phishingOutput}`);
