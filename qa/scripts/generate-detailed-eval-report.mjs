import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import {
  average,
  decisionToBinary,
  labelToBinary,
  parseArgs,
  percentile,
  readCsv,
  writeText,
} from "./lib.mjs";

const args = parseArgs();
const datasetPath = args.dataset ?? "qa/datasets/normalized/phishguard-eval-20k.csv";
const resultsPath = args.results ?? "qa/results/jsonl/api-eval-20k.jsonl";
const output = args.output ?? "qa/reports/phishguard-api-eval-20k-detailed-report.md";
const vizDir = args.vizDir ?? "qa/reports/visualizations";

const pct = (value) => value == null ? "n/a" : `${(value * 100).toFixed(2)}%`;
const wholePct = (count, total) => total ? pct(count / total) : "n/a";
const ms = (value) => value == null ? "n/a" : `${Math.round(value)} ms`;
const number = (value) => Number(value ?? 0).toLocaleString("en-US");
const md = (value) => String(value ?? "").replace(/\|/g, "\\|");

function increment(map, key, amount = 1) {
  const normalized = String(key || "unknown");
  map[normalized] = (map[normalized] ?? 0) + amount;
}

function sortEntries(map) {
  return Object.entries(map).sort((a, b) => b[1] - a[1]);
}

function safeName(name) {
  return String(name).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function escapeXml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function barChartSvg({ title, rows, width = 980, barHeight = 30, color = "#2563eb", valueFormatter = number }) {
  const margin = { top: 56, right: 140, bottom: 40, left: 260 };
  const height = margin.top + margin.bottom + rows.length * (barHeight + 12);
  const max = Math.max(...rows.map((row) => row.value), 1);
  const plotWidth = width - margin.left - margin.right;
  const items = rows.map((row, index) => {
    const y = margin.top + index * (barHeight + 12);
    const barWidth = Math.max(2, (row.value / max) * plotWidth);
    return `
      <text x="${margin.left - 12}" y="${y + 20}" text-anchor="end" class="label">${escapeXml(row.label)}</text>
      <rect x="${margin.left}" y="${y}" width="${barWidth.toFixed(1)}" height="${barHeight}" rx="6" fill="${row.color ?? color}" />
      <text x="${margin.left + barWidth + 10}" y="${y + 20}" class="value">${escapeXml(valueFormatter(row.value, row))}</text>`;
  }).join("");

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
    <style>
      .title { font: 700 24px Georgia, serif; fill: #111827; }
      .label { font: 14px Verdana, sans-serif; fill: #374151; }
      .value { font: 700 14px Verdana, sans-serif; fill: #111827; }
      .axis { stroke: #d1d5db; stroke-width: 1; }
    </style>
    <rect width="100%" height="100%" fill="#f8fafc" />
    <text x="32" y="36" class="title">${escapeXml(title)}</text>
    <line x1="${margin.left}" y1="${margin.top - 10}" x2="${margin.left}" y2="${height - margin.bottom + 4}" class="axis" />
    ${items}
  </svg>`;
}

function stackedBarSvg({ title, rows, segments, width = 1040 }) {
  const margin = { top: 70, right: 180, bottom: 46, left: 220 };
  const barHeight = 34;
  const height = margin.top + margin.bottom + rows.length * (barHeight + 16);
  const plotWidth = width - margin.left - margin.right;
  const legend = segments.map((segment, index) => `
    <rect x="${width - margin.right + 10}" y="${margin.top + index * 24}" width="14" height="14" rx="3" fill="${segment.color}" />
    <text x="${width - margin.right + 32}" y="${margin.top + 12 + index * 24}" class="legend">${escapeXml(segment.label)}</text>
  `).join("");
  const bars = rows.map((row, rowIndex) => {
    const total = segments.reduce((sum, segment) => sum + (row[segment.key] ?? 0), 0) || 1;
    let x = margin.left;
    const parts = segments.map((segment) => {
      const value = row[segment.key] ?? 0;
      const segmentWidth = (value / total) * plotWidth;
      const item = `<rect x="${x.toFixed(1)}" y="${margin.top + rowIndex * (barHeight + 16)}" width="${segmentWidth.toFixed(1)}" height="${barHeight}" fill="${segment.color}" />`;
      x += segmentWidth;
      return item;
    }).join("");
    const y = margin.top + rowIndex * (barHeight + 16);
    return `
      <text x="${margin.left - 12}" y="${y + 22}" text-anchor="end" class="label">${escapeXml(row.label)}</text>
      <g>${parts}</g>
      <text x="${margin.left + plotWidth + 10}" y="${y + 22}" class="value">${number(total)}</text>
    `;
  }).join("");

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
    <style>
      .title { font: 700 24px Georgia, serif; fill: #111827; }
      .label, .legend { font: 14px Verdana, sans-serif; fill: #374151; }
      .value { font: 700 14px Verdana, sans-serif; fill: #111827; }
    </style>
    <rect width="100%" height="100%" fill="#f8fafc" />
    <text x="32" y="38" class="title">${escapeXml(title)}</text>
    ${bars}
    ${legend}
  </svg>`;
}

function confusionMatrixSvg(matrix) {
  const cells = [
    { label: "True Negative", sub: "Actual safe, predicted safe", value: matrix.tn, x: 260, y: 120, fill: "#dcfce7" },
    { label: "False Positive", sub: "Actual safe, predicted risky", value: matrix.fp, x: 540, y: 120, fill: "#fee2e2" },
    { label: "False Negative", sub: "Actual risky, predicted safe", value: matrix.fn, x: 260, y: 330, fill: "#ffedd5" },
    { label: "True Positive", sub: "Actual risky, predicted risky", value: matrix.tp, x: 540, y: 330, fill: "#dbeafe" },
  ];
  const content = cells.map((cell) => `
    <rect x="${cell.x}" y="${cell.y}" width="240" height="160" rx="18" fill="${cell.fill}" stroke="#94a3b8" />
    <text x="${cell.x + 120}" y="${cell.y + 48}" text-anchor="middle" class="cell-label">${escapeXml(cell.label)}</text>
    <text x="${cell.x + 120}" y="${cell.y + 92}" text-anchor="middle" class="cell-value">${number(cell.value)}</text>
    <text x="${cell.x + 120}" y="${cell.y + 126}" text-anchor="middle" class="cell-sub">${escapeXml(cell.sub)}</text>
  `).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="860" height="560" viewBox="0 0 860 560">
    <style>
      .title { font: 700 25px Georgia, serif; fill: #111827; }
      .axis { font: 700 17px Verdana, sans-serif; fill: #334155; }
      .cell-label { font: 700 16px Verdana, sans-serif; fill: #111827; }
      .cell-value { font: 800 34px Verdana, sans-serif; fill: #0f172a; }
      .cell-sub { font: 12px Verdana, sans-serif; fill: #475569; }
    </style>
    <rect width="100%" height="100%" fill="#f8fafc" />
    <text x="32" y="40" class="title">Confusion Matrix</text>
    <text x="400" y="84" text-anchor="middle" class="axis">Predicted Safe</text>
    <text x="660" y="84" text-anchor="middle" class="axis">Predicted Risky</text>
    <text x="128" y="206" text-anchor="middle" class="axis">Actual Safe</text>
    <text x="128" y="416" text-anchor="middle" class="axis">Actual Risky</text>
    ${content}
  </svg>`;
}

function latencySvg(latency) {
  const rows = [
    { label: "Stage 1 avg", value: latency.stage1.avg, color: "#0f766e" },
    { label: "Stage 1 p95", value: latency.stage1.p95, color: "#14b8a6" },
    { label: "Stage 2 avg", value: latency.stage2.avg, color: "#b45309" },
    { label: "Stage 2 p95", value: latency.stage2.p95, color: "#f59e0b" },
    { label: "Total avg", value: latency.total.avg, color: "#1d4ed8" },
    { label: "Total p95", value: latency.total.p95, color: "#60a5fa" },
  ].filter((row) => row.value != null);
  return barChartSvg({ title: "Latency Summary", rows, color: "#2563eb", valueFormatter: ms });
}

function ratio(numerator, denominator) {
  return denominator === 0 ? null : numerator / denominator;
}

function metricsForRows(rows) {
  const matrix = { tp: 0, tn: 0, fp: 0, fn: 0 };
  const byCategory = {};
  const bySource = {};
  const byLabel = {};
  const reasonCounts = {};
  const stage1Counts = {};
  const stage2Counts = {};
  const stage2ByStage1 = {};
  const stage2ReasonCounts = {};
  const stage1Latencies = [];
  const stage2Latencies = [];
  const totalLatencies = [];

  for (const row of rows) {
    const actual = labelToBinary(row.label);
    const predicted = decisionToBinary(row.decision);
    if (actual === 1 && predicted === 1) matrix.tp += 1;
    if (actual === 0 && predicted === 0) matrix.tn += 1;
    if (actual === 0 && predicted === 1) matrix.fp += 1;
    if (actual === 1 && predicted === 0) matrix.fn += 1;

    const category = row.category || "unknown";
    byCategory[category] ??= { total: 0, correct: 0, wrong: 0, tp: 0, tn: 0, fp: 0, fn: 0, stage2_required: 0 };
    const bucket = byCategory[category];
    bucket.total += 1;
    if (actual === predicted) bucket.correct += 1;
    else bucket.wrong += 1;
    if (actual === 1 && predicted === 1) bucket.tp += 1;
    if (actual === 0 && predicted === 0) bucket.tn += 1;
    if (actual === 0 && predicted === 1) bucket.fp += 1;
    if (actual === 1 && predicted === 0) bucket.fn += 1;

    increment(bySource, row.source);
    increment(byLabel, row.label);
    increment(stage1Counts, row.stage1_verdict);
    increment(stage2Counts, row.stage2_verdict);

    const stage2Required = row.stage2_verdict !== "not_required" && row.stage2_latency_ms != null;
    if (stage2Required) {
      bucket.stage2_required += 1;
      increment(stage2ReasonCounts, row.stage1_reason);
    }

    stage2ByStage1[row.stage1_verdict || "unknown"] ??= { stage2: 0, no_stage2: 0 };
    if (stage2Required) stage2ByStage1[row.stage1_verdict || "unknown"].stage2 += 1;
    else stage2ByStage1[row.stage1_verdict || "unknown"].no_stage2 += 1;

    for (const reason of String(row.reason ?? "").split(",").filter(Boolean)) {
      increment(reasonCounts, reason);
    }
    if (row.stage1_latency_ms != null) stage1Latencies.push(Number(row.stage1_latency_ms));
    if (row.stage2_latency_ms != null) stage2Latencies.push(Number(row.stage2_latency_ms));
    if (row.total_latency_ms != null) totalLatencies.push(Number(row.total_latency_ms));
  }

  const total = matrix.tp + matrix.tn + matrix.fp + matrix.fn;
  const precision = ratio(matrix.tp, matrix.tp + matrix.fp);
  const recall = ratio(matrix.tp, matrix.tp + matrix.fn);
  return {
    total,
    matrix,
    accuracy: ratio(matrix.tp + matrix.tn, total),
    precision,
    recall,
    f1: precision == null || recall == null || precision + recall === 0 ? null : 2 * precision * recall / (precision + recall),
    falsePositiveRate: ratio(matrix.fp, matrix.fp + matrix.tn),
    falseNegativeRate: ratio(matrix.fn, matrix.fn + matrix.tp),
    byCategory,
    bySource,
    byLabel,
    reasonCounts,
    stage1Counts,
    stage2Counts,
    stage2ByStage1,
    stage2ReasonCounts,
    latency: {
      stage1: { avg: average(stage1Latencies), p50: percentile(stage1Latencies, 50), p95: percentile(stage1Latencies, 95), p99: percentile(stage1Latencies, 99) },
      stage2: { avg: average(stage2Latencies), p50: percentile(stage2Latencies, 50), p95: percentile(stage2Latencies, 95), p99: percentile(stage2Latencies, 99) },
      total: { avg: average(totalLatencies), p50: percentile(totalLatencies, 50), p95: percentile(totalLatencies, 95), p99: percentile(totalLatencies, 99) },
    },
  };
}

function datasetSummary(rows) {
  const byCategory = {};
  const byLabel = {};
  const bySource = {};
  const bySubcategory = {};
  for (const row of rows) {
    increment(byCategory, row.category);
    increment(byLabel, row.label);
    increment(bySource, row.source);
    increment(bySubcategory, row.subcategory);
  }
  return { byCategory, byLabel, bySource, bySubcategory };
}

function table(headers, rows) {
  return [
    `| ${headers.join(" | ")} |`,
    `| ${headers.map(() => "---").join(" | ")} |`,
    ...rows.map((row) => `| ${row.map(md).join(" | ")} |`),
  ].join("\n");
}

async function writeSvg(fileName, svg) {
  const fullPath = path.join(vizDir, fileName);
  await writeText(fullPath, svg);
  return path.relative(path.dirname(output), fullPath).replaceAll("\\", "/");
}

const dataset = await readCsv(datasetPath);
const resultLines = (await readFile(resultsPath, "utf8")).split(/\r?\n/).filter(Boolean);
const results = resultLines.map((line) => JSON.parse(line)).filter((row) => !row.error);
const datasetStats = datasetSummary(dataset);
const metrics = metricsForRows(results);

await mkdir(vizDir, { recursive: true });

const categoryRows = sortEntries(datasetStats.byCategory).map(([label, value]) => ({ label, value }));
const labelRows = sortEntries(datasetStats.byLabel).map(([label, value]) => ({ label, value, color: label === "safe" ? "#16a34a" : "#dc2626" }));
const stage1Rows = sortEntries(metrics.stage1Counts).map(([label, value]) => ({ label, value }));
const stage2Rows = Object.entries(metrics.stage2ByStage1).map(([label, value]) => ({ label, stage2: value.stage2, no_stage2: value.no_stage2 }));
const reasonRows = sortEntries(metrics.reasonCounts).slice(0, 15).map(([label, value]) => ({ label, value }));
const correctnessRows = Object.entries(metrics.byCategory).map(([label, value]) => ({ label, correct: value.correct, wrong: value.wrong }));

const visuals = {
  categoryMix: await writeSvg("20k-category-mix.svg", barChartSvg({ title: "20k Dataset Category Mix", rows: categoryRows, color: "#1d4ed8" })),
  labelMix: await writeSvg("20k-label-type-mix.svg", barChartSvg({ title: "20k Dataset Type Mix", rows: labelRows, color: "#16a34a" })),
  confusion: await writeSvg("20k-confusion-matrix.svg", confusionMatrixSvg(metrics.matrix)),
  correctness: await writeSvg("20k-correctness-by-category.svg", stackedBarSvg({
    title: "Correct vs Wrong Predictions by Category",
    rows: correctnessRows,
    segments: [
      { key: "correct", label: "Correct", color: "#22c55e" },
      { key: "wrong", label: "Wrong", color: "#ef4444" },
    ],
  })),
  stage1: await writeSvg("20k-stage1-verdicts.svg", barChartSvg({ title: "Stage 1 Verdict Distribution", rows: stage1Rows, color: "#7c3aed" })),
  stage2: await writeSvg("20k-stage2-requirement-by-stage1.svg", stackedBarSvg({
    title: "Stage 2 Requirement by Stage 1 Verdict",
    rows: stage2Rows,
    segments: [
      { key: "stage2", label: "Stage 2 executed", color: "#f97316" },
      { key: "no_stage2", label: "Stage 2 skipped", color: "#94a3b8" },
    ],
  })),
  reasons: await writeSvg("20k-top-reason-codes.svg", barChartSvg({ title: "Top Reason Codes", rows: reasonRows, color: "#0f766e" })),
  latency: await writeSvg("20k-latency-summary.svg", latencySvg(metrics.latency)),
};

const categoryTableRows = sortEntries(datasetStats.byCategory).map(([category, count]) => [
  category,
  number(count),
  wholePct(count, dataset.length),
]);

const labelTableRows = sortEntries(datasetStats.byLabel).map(([label, count]) => [
  label,
  number(count),
  wholePct(count, dataset.length),
]);

const sourceTableRows = sortEntries(datasetStats.bySource).slice(0, 20).map(([source, count]) => [
  source,
  number(count),
  wholePct(count, dataset.length),
]);

const predictionRows = [
  ["True Negative", "safe", "safe", number(metrics.matrix.tn), wholePct(metrics.matrix.tn, metrics.total)],
  ["False Positive", "safe", "risky", number(metrics.matrix.fp), wholePct(metrics.matrix.fp, metrics.total)],
  ["True Positive", "risky", "risky", number(metrics.matrix.tp), wholePct(metrics.matrix.tp, metrics.total)],
  ["False Negative", "risky", "safe", number(metrics.matrix.fn), wholePct(metrics.matrix.fn, metrics.total)],
];

const categoryPredictionRows = Object.entries(metrics.byCategory).map(([category, row]) => [
  category,
  number(row.total),
  number(row.correct),
  number(row.wrong),
  pct(row.correct / row.total),
  number(row.tp),
  number(row.tn),
  number(row.fp),
  number(row.fn),
  number(row.stage2_required),
  wholePct(row.stage2_required, row.total),
]);

const stage1RowsMd = sortEntries(metrics.stage1Counts).map(([verdict, count]) => [
  verdict,
  number(count),
  wholePct(count, metrics.total),
  number(metrics.stage2ByStage1[verdict]?.stage2 ?? 0),
  wholePct(metrics.stage2ByStage1[verdict]?.stage2 ?? 0, count),
]);

const stage2ReasonRows = sortEntries(metrics.stage2ReasonCounts).slice(0, 20).map(([reason, count]) => [
  reason,
  number(count),
  wholePct(count, Object.values(metrics.stage2ReasonCounts).reduce((sum, value) => sum + value, 0)),
]);

const reasonRowsMd = sortEntries(metrics.reasonCounts).slice(0, 20).map(([reason, count]) => [
  reason,
  number(count),
  wholePct(count, metrics.total),
]);

const report = `# PhishGuard 20k Detailed Evaluation Report

Generated: ${new Date().toISOString()}

Input dataset: \`${datasetPath}\`

Input results: \`${resultsPath}\`

## Executive Summary

PhishGuard was evaluated on ${number(metrics.total)} URLs using the 20k QA dataset. The dataset is intentionally imbalanced toward legitimate traffic to approximate a production browser-extension environment where most pages are safe.

- Total test samples: ${number(metrics.total)}
- Correct predictions: ${number(metrics.matrix.tp + metrics.matrix.tn)} (${pct(metrics.accuracy)})
- Wrong predictions: ${number(metrics.matrix.fp + metrics.matrix.fn)} (${wholePct(metrics.matrix.fp + metrics.matrix.fn, metrics.total)})
- Accuracy: ${pct(metrics.accuracy)}
- Precision: ${pct(metrics.precision)}
- Recall: ${pct(metrics.recall)}
- F1-score: ${pct(metrics.f1)}
- False Positive Rate: ${pct(metrics.falsePositiveRate)}
- False Negative Rate: ${pct(metrics.falseNegativeRate)}

## Dataset Composition

### Samples by Category

${table(["Category", "Samples", "Dataset %"], categoryTableRows)}

![Dataset category mix](${visuals.categoryMix})

### Samples by Type

${table(["Type / Label", "Samples", "Dataset %"], labelTableRows)}

![Dataset label mix](${visuals.labelMix})

### Samples by Source

${table(["Source", "Samples", "Dataset %"], sourceTableRows)}

## Prediction Quality

${table(["Outcome", "Actual", "Predicted", "Samples", "Dataset %"], predictionRows)}

![Confusion matrix](${visuals.confusion})

### Prediction Quality by Category

${table(["Category", "Total", "Correct", "Wrong", "Category Accuracy", "TP", "TN", "FP", "FN", "Stage 2 Required", "Stage 2 %"], categoryPredictionRows)}

![Correctness by category](${visuals.correctness})

## Stage 1 and Stage 2 Behavior

### Stage 1 Purpose

Stage 1 is the fast URL and SafeFilter precheck. It is designed to make quick decisions from lexical, domain reputation, whitelist, reserved-test, user-content platform, TLD, IP-hostname, and brand-impersonation signals.

Stage 1 should skip Stage 2 when the URL is clearly safe, especially for trusted or popular domains with no strong risk signal. This keeps browsing latency low.

Stage 1 should require Stage 2 when the URL is suspicious or malicious from URL-only evidence, such as:

- IP-address hostnames, for example local/private IP login URLs.
- Official security-test URLs.
- Brand impersonation indicators.
- Credential lure terms like login, verify, account, update, billing, wallet, or password.
- Public user-content hosting platforms with tenant subdomains.
- High-risk or suspicious TLDs.
- Long hostnames, deep subdomains, digit-heavy hosts, hyphen-heavy URLs, punycode, or \`@\` symbols.

### Why Stage 2 Is Needed

Stage 2 is needed because URL-only evidence is incomplete. Many phishing pages use ordinary-looking domains, compromised legitimate sites, short random domains, or public site builders. Stage 2 gives the system page-level context by analyzing webpage text/content and model fusion outputs.

Stage 2 helps answer questions Stage 1 cannot safely answer alone:

- Does the page actually ask for credentials, payment data, wallet recovery phrases, or verification?
- Does the visible page text impersonate a brand even when the hostname is not obviously malicious?
- Is a suspicious URL actually harmless or a legitimate login-heavy page?
- Does the ML model score confirm or reject the heuristic signal?
- Should the extension block, warn, allow, or show needs-review because Stage 1 and Stage 2 disagree?

### Stage 1 Verdicts and Stage 2 Routing

${table(["Stage 1 Verdict", "Samples", "Dataset %", "Stage 2 Executed", "Stage 2 Rate"], stage1RowsMd)}

![Stage 1 verdicts](${visuals.stage1})

![Stage 2 requirement by Stage 1 verdict](${visuals.stage2})

### Stage 2 Trigger Conditions Observed

These are the top Stage 1 reasons that caused Stage 2 to execute during the 20k run.

${table(["Stage 1 Reason", "Stage 2 Executions", "Stage 2 Share"], stage2ReasonRows)}

## Reason-Code Analysis

${table(["Reason Code", "Count", "Dataset %"], reasonRowsMd)}

![Top reason codes](${visuals.reasons})

## Latency and User Experience

${table(
  ["Stage", "Average", "p50", "p95", "p99"],
  [
    ["Stage 1", ms(metrics.latency.stage1.avg), ms(metrics.latency.stage1.p50), ms(metrics.latency.stage1.p95), ms(metrics.latency.stage1.p99)],
    ["Stage 2", ms(metrics.latency.stage2.avg), ms(metrics.latency.stage2.p50), ms(metrics.latency.stage2.p95), ms(metrics.latency.stage2.p99)],
    ["Total", ms(metrics.latency.total.avg), ms(metrics.latency.total.p50), ms(metrics.latency.total.p95), ms(metrics.latency.total.p99)],
  ],
)}

![Latency summary](${visuals.latency})

## System Condition

- Safe-site handling is strong in this 20k run: ${number(metrics.matrix.fp)} false positives were recorded, giving a ${pct(metrics.falsePositiveRate)} false-positive rate.
- Unsafe-site recall is the main weakness: ${number(metrics.matrix.fn)} risky samples were predicted safe, giving a ${pct(metrics.falseNegativeRate)} false-negative rate.
- The strongest current behavior is precision: when PhishGuard predicts risky, the prediction was correct in this run.
- The weakest current behavior is recall on low-signal phishing URLs and phishing URLs hidden behind whitelist/reputation bypass behavior.
- Stage 2 is essential for suspicious URLs because it provides page/content evidence and reduces the risk of blocking legitimate login-heavy websites from URL signals alone.

## Recommended Next Actions

1. Rerun the full 20k evaluation after the latest SafeFilter and Stage 1 changes.
2. Retrain or recalibrate the model using the false-negative set if recall remains below 90%.
3. Keep the false-positive gate strict for top legitimate websites and login-heavy pages.
4. Add regression tests for official security-test pages, public-hosting tenant URLs, typo-brand aliases, and safe infrastructure root domains.
5. Track Stage 1 and Stage 2 latency separately because Stage 2 currently dominates total wait time.

## Ethical Testing Boundary

This report uses defensive QA data only. Do not browse active credential-harvesting pages, do not submit credentials, do not bypass access controls, and do not deploy phishing content. Public phishing feeds should be used API-only or converted into sanitized offline fixtures.
`;

await writeText(output, report);
console.log(`Wrote detailed report to ${output}`);
console.log(`Wrote visualizations to ${vizDir}`);
