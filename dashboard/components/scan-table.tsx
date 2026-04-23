import type {
  FlaggedPhishingRecord,
  LocalScanRecord,
  SafeReportedAsPhishingRecord,
} from "@phishguard/shared";
import { formatTimestamp, getDomainLabel, scoreToPercent } from "@phishguard/shared";
import Link from "next/link";

import { StatusPill } from "./status-pill";

type AnyRow = LocalScanRecord | FlaggedPhishingRecord | SafeReportedAsPhishingRecord;

function resolveUrl(row: AnyRow) {
  return row.url;
}

function resolveTimestamp(row: AnyRow) {
  return "timestamp" in row ? row.timestamp : "";
}

function resolveScore(row: AnyRow) {
  if ("final_score" in row) {
    return scoreToPercent(row.final_score);
  }
  if ("score" in row) {
    return scoreToPercent(row.score);
  }
  return "-";
}

function resolveVerdict(row: AnyRow) {
  if ("verdict" in row) {
    return row.verdict;
  }
  return row.originalVerdict;
}

function resolveReasons(row: AnyRow) {
  if ("signals" in row) {
    const groupedReasons = row.signals.filter_signals.map((item) => item.label).join(", ") || row.filter_reason;
    if (row.consistency_status === "conflict") {
      return `Conflict: ${row.stage1_verdict ?? "unknown"} -> ${row.stage2_verdict ?? "unknown"}. ${groupedReasons}`;
    }
    return groupedReasons;
  }
  if ("reasons" in row) {
    return row.reasons.join(", ");
  }
  return row.currentFeedbackStatus;
}

function resolveScanId(row: AnyRow) {
  if ("scan_id" in row) {
    return row.scan_id;
  }
  return row.scanId;
}

export function ScanTable({
  rows,
  deviceId,
}: {
  rows: AnyRow[];
  deviceId?: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="text-left uppercase tracking-[0.16em] text-slate-500">
          <tr>
            <th className="pb-3 pr-4">Timestamp</th>
            <th className="pb-3 pr-4">URL</th>
            <th className="pb-3 pr-4">Verdict</th>
            <th className="pb-3 pr-4">Score</th>
            <th className="pb-3 pr-4">Reason</th>
            <th className="pb-3">Report</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const scanId = resolveScanId(row);
            const url = resolveUrl(row);
            const href = scanId
              ? `/report/${scanId}${deviceId ? `?device_id=${encodeURIComponent(deviceId)}` : ""}`
              : `/report/url?url=${encodeURIComponent(url)}${deviceId ? `&device_id=${encodeURIComponent(deviceId)}` : ""}`;

            return (
              <tr key={`${url}-${resolveTimestamp(row)}-${scanId ?? "url"}`} className="border-t border-line/50 align-top">
                <td className="py-4 pr-4 text-slate-300">{formatTimestamp(resolveTimestamp(row))}</td>
                <td className="py-4 pr-4">
                  <div className="font-medium text-white">{getDomainLabel(url)}</div>
                  <div className="mt-1 max-w-[320px] break-all text-xs text-slate-500">{url}</div>
                </td>
                <td className="py-4 pr-4">
                  <StatusPill verdict={resolveVerdict(row)} />
                </td>
                <td className="py-4 pr-4 text-white">{resolveScore(row)}</td>
                <td className="py-4 pr-4 text-slate-400">{resolveReasons(row)}</td>
                <td className="py-4">
                  <Link className="text-accent hover:text-cyan-200" href={href}>
                    Open report
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
