"use client";

import { formatTimestamp } from "@phishguard/shared";

import { EmptyState } from "../empty-state";
import { Panel } from "../panel";
import { useDashboardData } from "../../lib/dashboard-data";

export function FeedbackPageClient({ deviceId }: { deviceId?: string }) {
  const { feedback } = useDashboardData(deviceId);

  return (
    <Panel
      title="Feedback and reports"
      subtitle="Manual reports, corrections, and local queue state for this device."
    >
      {feedback.length === 0 ? (
        <EmptyState title="No feedback events" body="User feedback from the extension will show up here." />
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left uppercase tracking-[0.16em] text-slate-500">
              <tr>
                <th className="pb-3 pr-4">Timestamp</th>
                <th className="pb-3 pr-4">Action</th>
                <th className="pb-3 pr-4">URL</th>
                <th className="pb-3 pr-4">Previous verdict</th>
                <th className="pb-3">Sync status</th>
              </tr>
            </thead>
            <tbody>
              {feedback.map((item) => (
                <tr key={item.feedback_id} className="border-t border-line/50">
                  <td className="py-4 pr-4 text-slate-300">{formatTimestamp(item.timestamp)}</td>
                  <td className="py-4 pr-4 text-white">{item.user_action.replaceAll("_", " ")}</td>
                  <td className="py-4 pr-4 break-all text-slate-400">{item.url}</td>
                  <td className="py-4 pr-4 text-slate-300">{item.previous_verdict}</td>
                  <td className="py-4 text-slate-400">{item.sync_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
