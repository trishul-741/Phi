"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { EmptyState } from "../empty-state";
import { Panel } from "../panel";
import { addTrustedDomain, removeTrustedDomain } from "../../lib/api";
import { useDashboardData } from "../../lib/dashboard-data";

export function WhitelistPageClient({ deviceId }: { deviceId?: string }) {
  const { trustedDomains, deviceId: resolvedDeviceId } = useDashboardData(deviceId);
  const [domain, setDomain] = useState("");
  const [status, setStatus] = useState("");
  const queryClient = useQueryClient();

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["whitelist", resolvedDeviceId] });
  };

  const onAdd = async () => {
    if (!domain.trim()) {
      return;
    }
    try {
      await addTrustedDomain(domain.trim(), resolvedDeviceId);
      setStatus("Trusted domain saved for Stage 1 precheck.");
      setDomain("");
      await refresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to save trusted domain.");
    }
  };

  const onRemove = async (target: string) => {
    try {
      await removeTrustedDomain(target, resolvedDeviceId);
      setStatus("Trusted domain removed.");
      await refresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to remove trusted domain.");
    }
  };

  return (
    <div className="space-y-6">
      <Panel
        title="Trusted domains"
        subtitle="Backend-managed trusted domains participate in Stage 1 precheck for the same device ID."
      >
        <div className="flex flex-col gap-3 md:flex-row">
          <input
            className="flex-1 rounded-2xl border border-line/70 bg-night/70 px-4 py-3 text-white outline-none"
            placeholder="example.com"
            value={domain}
            onChange={(event) => setDomain(event.target.value)}
          />
          <button className="rounded-2xl bg-accent px-5 py-3 font-semibold text-slate-950" onClick={() => void onAdd()}>
            Add trusted domain
          </button>
        </div>
        {status ? <div className="mt-3 text-sm text-slate-400">{status}</div> : null}
      </Panel>

      <Panel title="Current whitelist" subtitle="Extension-local and synced trusted domains visible for this device.">
        {trustedDomains.length === 0 ? (
          <EmptyState
            title="No trusted domains"
            body="Add a domain here or from the extension overlay to bypass repeated low-risk interruptions."
          />
        ) : (
          <div className="space-y-3">
            {trustedDomains.map((item) => (
              <div key={`${item.domain}-${item.device_id}`} className="flex items-center justify-between rounded-[22px] border border-line/70 bg-white/5 p-4">
                <div>
                  <div className="font-medium text-white">{item.domain}</div>
                  <div className="mt-1 text-sm text-slate-400">{item.note || "Trusted for this device"}</div>
                </div>
                <button className="rounded-2xl border border-line/70 px-4 py-2 text-sm text-slate-300" onClick={() => void onRemove(item.domain)}>
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
