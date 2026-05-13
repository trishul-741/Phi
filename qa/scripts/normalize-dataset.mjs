import { parseArgs, readCsv, toCsv, normalizeUrl, writeText } from "./lib.mjs";

const args = parseArgs();
const input = args.input;
const output = args.output ?? "qa/datasets/normalized/phishguard-eval.csv";

if (!input) {
  throw new Error("Usage: node qa/scripts/normalize-dataset.mjs --input <csv> --output <csv>");
}

const rows = await readCsv(input);
const seen = new Set();
const normalized = [];

for (const row of rows) {
  const url = normalizeUrl(row.url);
  if (!url || seen.has(url)) {
    continue;
  }
  seen.add(url);
  normalized.push({
    url,
    label: row.label || "safe",
    source: row.source || "unknown",
    category: row.category || "uncategorized",
    subcategory: row.subcategory || "",
    should_browser_test: row.should_browser_test || "false",
    should_stage2_test: row.should_stage2_test || "false",
    title: row.title || "",
    text_clean: row.text_clean || "",
    text_raw: row.text_raw || "",
    notes: row.notes || "",
  });
}

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
await writeText(output, `${toCsv(normalized, headers)}\n`);
console.log(`Normalized ${rows.length} rows to ${normalized.length} unique URLs at ${output}`);
