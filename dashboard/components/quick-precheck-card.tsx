"use client";

import type { PrecheckResponse } from "@phishguard/shared";
import { scoreToPercent, verdictLabel } from "@phishguard/shared";
import { useState } from "react";

import { runQuickPrecheck } from "../lib/api";
import { Panel } from "./panel";

export function QuickPrecheckCard({ deviceId }: { deviceId?: string }) {
  const [url, setUrl] = useState("");
  const [result, setResult] = useState<PrecheckResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!url) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      const next = await runQuickPrecheck(url, deviceId);
      setResult(next);
    } catch (nextError) {
      setResult(null);
      setError(nextError instanceof Error ? nextError.message : "Stage 1 pre-check failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Panel
      title="Quick URL pre-check"
      subtitle="Runs the same Stage 1 URL-first screening the extension uses before a full content scan."
    >
      <form className="flex flex-col gap-3 md:flex-row" onSubmit={onSubmit}>
        <input
          className="flex-1 rounded-2xl border border-line/70 bg-night/70 px-4 py-3 text-white outline-none"
          placeholder="https://example.com/login"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
        />
        <button
          className="rounded-2xl bg-accent px-5 py-3 font-semibold text-slate-950 transition hover:bg-cyan-300"
          type="submit"
          disabled={loading}
        >
          {loading ? "Checking..." : "Run pre-check"}
        </button>
      </form>

      {result ? (
        <div className="mt-4 rounded-[22px] border border-line/70 bg-white/5 p-4">
          <div className="text-sm uppercase tracking-[0.16em] text-slate-400">Stage 1 result</div>
          <div className="mt-2 text-xl font-semibold text-white">{verdictLabel(result.stage1_verdict)}</div>
          <div className="mt-2 text-sm text-slate-400">
            Score {scoreToPercent(result.stage1_score)} - {result.reason.replaceAll("_", " ")}
          </div>
          <div className="mt-2 text-xs text-slate-500">
            Full scan required: {result.should_run_full_scan ? "yes" : "no"}
          </div>
        </div>
      ) : null}

      {error ? <div className="mt-4 text-sm text-rose-300">{error}</div> : null}
    </Panel>
  );
}
