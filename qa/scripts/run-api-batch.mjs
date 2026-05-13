import { access, mkdir, open } from "node:fs/promises";
import path from "node:path";
import {
  appendJsonl,
  hostnameFor,
  parseArgs,
  readCsv,
  timestampSlug,
  writeJson,
} from "./lib.mjs";

const args = parseArgs();
const input = args.input;
const apiBaseUrl = args.api ?? process.env.PHISHGUARD_API_BASE_URL ?? "http://127.0.0.1:8000";
const deviceId = args.device ?? process.env.PHISHGUARD_QA_DEVICE_ID ?? "qa-heavy";
const workers = Number(args.workers ?? 16);
const output = args.output ?? `qa/results/jsonl/api-batch-${timestampSlug()}.jsonl`;
const summaryOutput = args.summary ?? output.replace(/\.jsonl$/, ".summary.json");

if (!input) {
  throw new Error("Usage: node qa/scripts/run-api-batch.mjs --input <csv> [--workers 16] [--output <jsonl>]");
}

try {
  await access(input);
} catch {
  console.error([
    `Input dataset not found: ${input}`,
    "",
    "Create it first, for example:",
    "  npm run qa:generate-synthetic -- --count 3000 --output qa/datasets/raw/synthetic-suspicious.csv",
    "  npm run qa:normalize -- --input qa/datasets/raw/synthetic-suspicious.csv --output qa/datasets/normalized/synthetic-suspicious.csv",
    "",
    "For a full 70/15/15 dataset, provide safe, phishing/test, and synthetic CSVs:",
    "  npm run qa:build-dataset -- --safe qa/datasets/normalized/safe.csv --phishing qa/datasets/normalized/phishing.csv --synthetic qa/datasets/normalized/synthetic-suspicious.csv --total 20000 --output qa/datasets/normalized/phishguard-eval-20k.csv",
  ].join("\n"));
  process.exit(1);
}

async function requestJson(pathname, init) {
  const startedAt = performance.now();
  const response = await fetch(`${apiBaseUrl}${pathname}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const latencyMs = Math.round(performance.now() - startedAt);
  const text = await response.text();
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${text}`);
  }
  return { body, latencyMs };
}

function shouldRunStage2(row, precheckBody) {
  if (row.should_stage2_test === "true") {
    return true;
  }
  return Boolean(precheckBody?.should_run_full_scan);
}

function fallbackText(row) {
  return row.text_clean || "Benign QA fixture only. No credentials are collected.";
}

async function runRow(row, index) {
  const startedAt = performance.now();
  const base = {
    run_id: deviceId,
    row_index: index,
    timestamp: new Date().toISOString(),
    url: row.url,
    domain: hostnameFor(row.url),
    label: row.label,
    source: row.source,
    category: row.category,
    subcategory: row.subcategory,
    error: null,
  };

  try {
    const precheck = await requestJson("/v1/precheck", {
      method: "POST",
      body: JSON.stringify({
        url: row.url,
        hostname: hostnameFor(row.url),
        device_id: deviceId,
      }),
    });

    let scan = null;
    if (shouldRunStage2(row, precheck.body)) {
      scan = await requestJson("/v1/scan", {
        method: "POST",
        body: JSON.stringify({
          url: row.url,
          title: row.title || "QA fixture",
          text_clean: fallbackText(row),
          text_raw: row.text_raw || `<html><body>${fallbackText(row)}</body></html>`,
          source: "qa_heavy_api",
          device_id: deviceId,
          tab_id: 0,
        }),
      });
    }

    return {
      ...base,
      stage1_latency_ms: precheck.latencyMs,
      stage2_latency_ms: scan?.latencyMs ?? null,
      total_latency_ms: Math.round(performance.now() - startedAt),
      stage1_score: precheck.body.stage1_score,
      stage1_verdict: precheck.body.stage1_verdict,
      stage1_reason: precheck.body.reason,
      stage2_verdict: scan?.body.stage2_verdict ?? "not_required",
      raw_score: scan?.body.raw_score ?? null,
      calibrated_score: scan?.body.calibrated_score ?? null,
      final_score: scan?.body.final_score ?? precheck.body.stage1_score,
      threshold: scan?.body.threshold ?? null,
      decision: scan?.body.verdict ?? precheck.body.stage1_verdict,
      consistency_status: scan?.body.consistency_status ?? "precheck_only",
      reason: scan?.body.filter_reason ?? precheck.body.reason,
      signals: scan?.body.signals ?? null,
    };
  } catch (error) {
    return {
      ...base,
      total_latency_ms: Math.round(performance.now() - startedAt),
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

const rows = await readCsv(input);
await mkdir(path.dirname(output), { recursive: true });
const handle = await open(output, "w");
let nextIndex = 0;
let completed = 0;
let failed = 0;

async function worker() {
  while (nextIndex < rows.length) {
    const index = nextIndex;
    nextIndex += 1;
    const result = await runRow(rows[index], index);
    if (result.error) {
      failed += 1;
    }
    completed += 1;
    await appendJsonl(handle, result);
    if (completed % 100 === 0 || completed === rows.length) {
      console.log(`Processed ${completed}/${rows.length}`);
    }
  }
}

await Promise.all(Array.from({ length: Math.min(workers, rows.length) }, () => worker()));
await handle.close();

const summary = {
  api_base_url: apiBaseUrl,
  device_id: deviceId,
  input,
  output,
  total_rows: rows.length,
  completed,
  failed,
  workers,
  generated_at: new Date().toISOString(),
};

await writeJson(summaryOutput, summary);
console.log(`Wrote batch results to ${output}`);
console.log(`Wrote batch summary to ${summaryOutput}`);
if (failed > 0) {
  process.exitCode = 1;
}
