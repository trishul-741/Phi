import { readFile } from "node:fs/promises";
import { parseArgs, writeText } from "./lib.mjs";

const args = parseArgs();
const metricsPath = args.metrics;
const output = args.output ?? "qa/reports/phishguard-heavy-data-report.md";

if (!metricsPath) {
  throw new Error("Usage: node qa/scripts/generate-report.mjs --metrics <metrics.json> --output <report.md>");
}

const metrics = JSON.parse(await readFile(metricsPath, "utf8"));
const pct = (value) => value == null ? "n/a" : `${(value * 100).toFixed(2)}%`;
const ms = (value) => value == null ? "n/a" : `${Math.round(value)} ms`;

const report = `# PhishGuard Heavy-Data Evaluation Report

Generated: ${new Date().toISOString()}

## Executive Summary

- Total evaluated rows: ${metrics.total}
- Accuracy: ${pct(metrics.accuracy)}
- Precision: ${pct(metrics.precision)}
- Recall: ${pct(metrics.recall)}
- F1-score: ${pct(metrics.f1)}
- False Positive Rate: ${pct(metrics.false_positive_rate)}
- False Negative Rate: ${pct(metrics.false_negative_rate)}
- ROC-AUC: ${metrics.roc_auc == null ? "n/a" : metrics.roc_auc.toFixed(4)}

## Confusion Matrix

| | Predicted Safe | Predicted Risky |
|---|---:|---:|
| Actual Safe | ${metrics.confusion_matrix.tn} | ${metrics.confusion_matrix.fp} |
| Actual Risky | ${metrics.confusion_matrix.fn} | ${metrics.confusion_matrix.tp} |

## Latency

| Stage | Avg | p50 | p95 | p99 |
|---|---:|---:|---:|---:|
| Stage 1 | ${ms(metrics.latency_ms.stage1.avg)} | ${ms(metrics.latency_ms.stage1.p50)} | ${ms(metrics.latency_ms.stage1.p95)} | ${ms(metrics.latency_ms.stage1.p99)} |
| Stage 2 | ${ms(metrics.latency_ms.stage2.avg)} | ${ms(metrics.latency_ms.stage2.p50)} | ${ms(metrics.latency_ms.stage2.p95)} | ${ms(metrics.latency_ms.stage2.p99)} |
| Total | ${ms(metrics.latency_ms.total.avg)} | ${ms(metrics.latency_ms.total.p50)} | ${ms(metrics.latency_ms.total.p95)} | ${ms(metrics.latency_ms.total.p99)} |

## Category Breakdown

| Category | Total | TP | TN | FP | FN |
|---|---:|---:|---:|---:|---:|
${Object.entries(metrics.by_category).map(([category, row]) => `| ${category} | ${row.total} | ${row.tp} | ${row.tn} | ${row.fp} | ${row.fn} |`).join("\n")}

## Top Reason Codes

| Reason | Count |
|---|---:|
${Object.entries(metrics.reason_counts).slice(0, 20).map(([reason, count]) => `| ${reason} | ${count} |`).join("\n")}

## Production Readiness Criteria

- False Positive Rate target: below 3-5%.
- Phishing/test recall target: above 90-95%.
- Stage 1 p95 latency target: below 100 ms.
- Stage 2 p95 latency target: below 5 seconds.
- No credential collection or sensitive data logging.

## Notes

This report is generated from defensive QA data only. Live phishing-feed URLs must remain API-only unless converted into sanitized offline fixtures.
`;

await writeText(output, report);
console.log(`Wrote report to ${output}`);
