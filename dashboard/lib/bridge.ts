"use client";

import type { LocalDashboardSnapshot } from "@phishguard/shared";
import { useEffect, useState } from "react";

const REQUEST = "PHISHGUARD_DASHBOARD_SNAPSHOT_REQUEST";
const RESPONSE = "PHISHGUARD_DASHBOARD_SNAPSHOT_RESPONSE";

export function useExtensionSnapshot() {
  const [snapshot, setSnapshot] = useState<LocalDashboardSnapshot | null>(null);
  const [bridgeAvailable, setBridgeAvailable] = useState(false);

  useEffect(() => {
    let finished = false;
    const timeout = window.setTimeout(() => {
      if (!finished) {
        setBridgeAvailable(false);
      }
    }, 1200);

    const handler = (event: MessageEvent<{ type?: string; payload?: LocalDashboardSnapshot }>) => {
      if (event.source !== window || event.data?.type !== RESPONSE || !event.data.payload) {
        return;
      }
      finished = true;
      setBridgeAvailable(true);
      setSnapshot(event.data.payload);
      window.clearTimeout(timeout);
    };

    window.addEventListener("message", handler);
    window.postMessage({ type: REQUEST }, window.location.origin);

    return () => {
      window.clearTimeout(timeout);
      window.removeEventListener("message", handler);
    };
  }, []);

  return { snapshot, bridgeAvailable };
}
