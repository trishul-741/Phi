import { parseArgs, readCsv, toCsv, normalizeUrl, writeText } from "./lib.mjs";

const args = parseArgs();
const safeInput = args.safe;
const phishingInput = args.phishing;
const syntheticInput = args.synthetic;
const output = args.output ?? "qa/datasets/normalized/phishguard-eval-20k.csv";
const total = Number(args.total ?? 20000);

if (!safeInput || !phishingInput || !syntheticInput) {
  throw new Error(
    "Usage: node qa/scripts/build-eval-dataset.mjs --safe <csv> --phishing <csv> --synthetic <csv> --total 20000 --output <csv>",
  );
}

const counts = {
  safe: Math.round(total * 0.7),
  phishing: Math.round(total * 0.15),
  synthetic: total - Math.round(total * 0.7) - Math.round(total * 0.15),
};

function normalizeRow(row, defaults) {
  return {
    url: normalizeUrl(row.url),
    label: row.label || defaults.label,
    source: row.source || defaults.source,
    category: row.category || defaults.category,
    subcategory: row.subcategory || "",
    should_browser_test: row.should_browser_test || defaults.should_browser_test,
    should_stage2_test: row.should_stage2_test || defaults.should_stage2_test,
    title: row.title || "",
    text_clean: row.text_clean || "",
    text_raw: row.text_raw || "",
    notes: row.notes || "",
  };
}

function takeRows(rows, count, defaults, label) {
  const normalized = [];
  const seen = new Set();
  for (const row of rows) {
    const item = normalizeRow(row, defaults);
    if (!item.url || seen.has(item.url)) {
      continue;
    }
    seen.add(item.url);
    normalized.push(item);
    if (normalized.length >= count) {
      break;
    }
  }

  if (normalized.length < count) {
    throw new Error(
      `${label} dataset has ${normalized.length} unique rows, but ${count} are required for this mix.`,
    );
  }
  return normalized;
}

const safeRows = takeRows(await readCsv(safeInput), counts.safe, {
  label: "safe",
  source: "safe_dataset",
  category: "legitimate",
  should_browser_test: "true",
  should_stage2_test: "false",
}, "Safe");

const phishingRows = takeRows(await readCsv(phishingInput), counts.phishing, {
  label: "phishing",
  source: "phishing_dataset",
  category: "phishing",
  should_browser_test: "false",
  should_stage2_test: "false",
}, "Phishing/test");

const syntheticRows = takeRows(await readCsv(syntheticInput), counts.synthetic, {
  label: "suspicious_synthetic",
  source: "synthetic",
  category: "lexical",
  should_browser_test: "false",
  should_stage2_test: "true",
}, "Synthetic");

const combined = [...safeRows, ...phishingRows, ...syntheticRows];
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

await writeText(output, `${toCsv(combined, headers)}\n`);
console.log(`Wrote ${combined.length} rows to ${output}`);
console.log(`Mix: ${counts.safe} safe, ${counts.phishing} phishing/test, ${counts.synthetic} synthetic suspicious`);
