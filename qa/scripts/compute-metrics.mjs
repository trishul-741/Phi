import { readFile } from "node:fs/promises";
import {
  average,
  decisionToBinary,
  labelToBinary,
  parseArgs,
  percentile,
  writeJson,
} from "./lib.mjs";

const args = parseArgs();
const input = args.input;
const output = args.output ?? "qa/reports/metrics.json";

if (!input) {
  throw new Error("Usage: node qa/scripts/compute-metrics.mjs --input <jsonl> --output <json>");
}

const lines = (await readFile(input, "utf8")).split(/\r?\n/).filter(Boolean);
const rows = lines.map((line) => JSON.parse(line)).filter((row) => !row.error);

const matrix = { tp: 0, tn: 0, fp: 0, fn: 0 };
const byCategory = {};
const reasonCounts = {};
const stage1Latencies = [];
const stage2Latencies = [];
const totalLatencies = [];
const scores = [];

for (const row of rows) {
  const actual = labelToBinary(row.label);
  const predicted = decisionToBinary(row.decision);
  if (actual === 1 && predicted === 1) matrix.tp += 1;
  if (actual === 0 && predicted === 0) matrix.tn += 1;
  if (actual === 0 && predicted === 1) matrix.fp += 1;
  if (actual === 1 && predicted === 0) matrix.fn += 1;

  byCategory[row.category] ??= { total: 0, tp: 0, tn: 0, fp: 0, fn: 0 };
  const bucket = byCategory[row.category];
  bucket.total += 1;
  if (actual === 1 && predicted === 1) bucket.tp += 1;
  if (actual === 0 && predicted === 0) bucket.tn += 1;
  if (actual === 0 && predicted === 1) bucket.fp += 1;
  if (actual === 1 && predicted === 0) bucket.fn += 1;

  for (const reason of String(row.reason ?? "").split(",").filter(Boolean)) {
    reasonCounts[reason] = (reasonCounts[reason] ?? 0) + 1;
  }
  if (row.stage1_latency_ms != null) stage1Latencies.push(row.stage1_latency_ms);
  if (row.stage2_latency_ms != null) stage2Latencies.push(row.stage2_latency_ms);
  if (row.total_latency_ms != null) totalLatencies.push(row.total_latency_ms);
  if (row.final_score != null) scores.push({ score: row.final_score, label: actual });
}

function ratio(numerator, denominator) {
  return denominator === 0 ? null : numerator / denominator;
}

function auc(points) {
  const sorted = [...points].sort((a, b) => b.score - a.score);
  const positives = sorted.filter((point) => point.label === 1).length;
  const negatives = sorted.length - positives;
  if (!positives || !negatives) return null;
  let tp = 0;
  let fp = 0;
  let prevFpr = 0;
  let prevTpr = 0;
  let area = 0;
  for (const point of sorted) {
    if (point.label === 1) tp += 1;
    else fp += 1;
    const tpr = tp / positives;
    const fpr = fp / negatives;
    area += (fpr - prevFpr) * (tpr + prevTpr) / 2;
    prevFpr = fpr;
    prevTpr = tpr;
  }
  return area;
}

const total = matrix.tp + matrix.tn + matrix.fp + matrix.fn;
const precision = ratio(matrix.tp, matrix.tp + matrix.fp);
const recall = ratio(matrix.tp, matrix.tp + matrix.fn);
const metrics = {
  input,
  total,
  confusion_matrix: matrix,
  accuracy: ratio(matrix.tp + matrix.tn, total),
  precision,
  recall,
  f1: precision == null || recall == null || precision + recall === 0 ? null : 2 * precision * recall / (precision + recall),
  false_positive_rate: ratio(matrix.fp, matrix.fp + matrix.tn),
  false_negative_rate: ratio(matrix.fn, matrix.fn + matrix.tp),
  roc_auc: auc(scores),
  by_category: byCategory,
  reason_counts: Object.fromEntries(Object.entries(reasonCounts).sort((a, b) => b[1] - a[1])),
  latency_ms: {
    stage1: {
      avg: average(stage1Latencies),
      p50: percentile(stage1Latencies, 50),
      p95: percentile(stage1Latencies, 95),
      p99: percentile(stage1Latencies, 99),
    },
    stage2: {
      avg: average(stage2Latencies),
      p50: percentile(stage2Latencies, 50),
      p95: percentile(stage2Latencies, 95),
      p99: percentile(stage2Latencies, 99),
    },
    total: {
      avg: average(totalLatencies),
      p50: percentile(totalLatencies, 50),
      p95: percentile(totalLatencies, 95),
      p99: percentile(totalLatencies, 99),
    },
  },
  generated_at: new Date().toISOString(),
};

await writeJson(output, metrics);
console.log(`Wrote metrics to ${output}`);
