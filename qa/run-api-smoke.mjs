import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const apiBaseUrl = process.env.PHISHGUARD_API_BASE_URL ?? "http://127.0.0.1:8000";
const deviceId = process.env.PHISHGUARD_QA_DEVICE_ID ?? "qa-device";
const casesPath = process.env.PHISHGUARD_QA_CASES ?? "qa/test-cases.json";
const outputDir = process.env.PHISHGUARD_QA_OUTPUT_DIR ?? "qa/results";

function nowCompact() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

function hostnameFor(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
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
    const detail = typeof body?.detail === "string" ? body.detail : text;
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  return { body, latencyMs };
}

function flattenSignalKeys(scan) {
  const groups = scan?.signals ?? {};
  return [
    ...(groups.url_signals ?? []),
    ...(groups.content_signals ?? []),
    ...(groups.structural_signals ?? []),
    ...(groups.filter_signals ?? []),
  ].map((signal) => signal.key);
}

function expectedIncludes(expected, actual) {
  return Array.isArray(expected) && expected.includes(actual);
}

function evaluate(testCase, precheck, scan, error) {
  if (error) {
    return {
      pass: testCase.category === "backend_error",
      reason: error.message,
    };
  }

  const stage1 = precheck?.stage1_verdict;
  const stage2 = scan?.stage2_verdict ?? (testCase.mode === "precheck" ? "not_required" : undefined);
  const finalVerdict = scan?.verdict ?? stage1;
  const signalKeys = flattenSignalKeys(scan);

  const stage1Ok = expectedIncludes(testCase.expectedStage1, stage1);
  const stage2Ok = expectedIncludes(testCase.expectedStage2, stage2);

  if (testCase.category === "synthetic_suspicious") {
    const hasRiskSignal = signalKeys.some((key) =>
      ["brand_impersonation_score", "has_ip", "subdomain_depth", "ip_hostname", "brand_impersonation"].includes(key),
    );
    return {
      pass: stage1Ok && stage2Ok && (hasRiskSignal || finalVerdict !== "safe"),
      reason: `stage1=${stage1}; stage2=${stage2}; final=${finalVerdict}; signals=${signalKeys.join(",")}`,
    };
  }

  return {
    pass: stage1Ok && stage2Ok,
    reason: `stage1=${stage1}; stage2=${stage2}; final=${finalVerdict}`,
  };
}

async function runCase(testCase) {
  const result = {
    id: testCase.id,
    category: testCase.category,
    url: testCase.url,
    mode: testCase.mode,
    started_at: new Date().toISOString(),
    precheck: null,
    scan: null,
    error: null,
  };

  try {
    if (testCase.mode === "manual_extension") {
      result.error = "Manual extension case; not executed by API smoke runner.";
      result.evaluation = { pass: true, reason: result.error };
      return result;
    }

    const precheck = await requestJson("/v1/precheck", {
      method: "POST",
      body: JSON.stringify({
        url: testCase.url,
        hostname: hostnameFor(testCase.url),
        device_id: deviceId,
      }),
    });
    result.precheck = {
      latency_ms: precheck.latencyMs,
      ...precheck.body,
    };

    if (testCase.mode === "full_scan") {
      const scan = await requestJson("/v1/scan", {
        method: "POST",
        body: JSON.stringify({
          url: testCase.url,
          title: testCase.title ?? "",
          text_clean: testCase.text_clean ?? "",
          text_raw: testCase.text_raw ?? "",
          source: "qa_api_smoke",
          device_id: deviceId,
          tab_id: 0,
        }),
      });
      result.scan = {
        latency_ms: scan.latencyMs,
        ...scan.body,
      };
    }

    result.evaluation = evaluate(testCase, result.precheck, result.scan, null);
  } catch (error) {
    result.error = error instanceof Error ? error.message : String(error);
    result.evaluation = evaluate(testCase, result.precheck, result.scan, error);
  }

  return result;
}

function summarize(results) {
  const executable = results.filter((item) => item.mode !== "manual_extension");
  const passed = executable.filter((item) => item.evaluation?.pass).length;
  const failed = executable.length - passed;
  return {
    api_base_url: apiBaseUrl,
    device_id: deviceId,
    total_cases: results.length,
    executable_cases: executable.length,
    passed,
    failed,
    generated_at: new Date().toISOString(),
  };
}

const rawCases = JSON.parse(await readFile(casesPath, "utf8"));
const cases = rawCases.filter((testCase) => testCase.mode === "precheck" || testCase.mode === "full_scan" || testCase.mode === "manual_extension");
const results = [];

const health = await requestJson("/health");
if (health.body?.status !== "ok") {
  throw new Error(`Health check did not return ok: ${JSON.stringify(health.body)}`);
}

for (const testCase of cases) {
  const result = await runCase(testCase);
  results.push(result);
  const mark = result.evaluation?.pass ? "PASS" : "FAIL";
  console.log(`${mark} ${testCase.id} ${testCase.url} :: ${result.evaluation?.reason ?? result.error}`);
}

const summary = summarize(results);
await mkdir(outputDir, { recursive: true });
const outputPath = path.join(outputDir, `api-smoke-${nowCompact()}.json`);
await writeFile(outputPath, JSON.stringify({ summary, results }, null, 2));

console.log(`\nSummary: ${summary.passed}/${summary.executable_cases} executable cases passed.`);
console.log(`Report: ${outputPath}`);

if (summary.failed > 0) {
  process.exitCode = 1;
}
