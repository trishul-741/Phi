import type {
  FeedbackEvent,
  FeedbackRequest,
  HistoryResponse,
  PrecheckRequest,
  PrecheckResponse,
  ScanRequest,
  ScanResponse,
  TrustedDomainRecord,
  TrustedDomainRequest,
  WhitelistResponse,
} from "@phishguard/shared";

import { getSettings } from "./storage";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const settings = await getSettings();
  const response = await fetch(`${settings.apiBaseUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || `PhishGuard API request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function postPrecheck(payload: PrecheckRequest): Promise<PrecheckResponse> {
  return request<PrecheckResponse>("/v1/precheck", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function postScan(payload: ScanRequest): Promise<ScanResponse> {
  return request<ScanResponse>("/v1/scan", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function postFeedback(payload: FeedbackRequest): Promise<FeedbackEvent> {
  return request<FeedbackEvent>("/v1/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getHistory(deviceId?: string): Promise<HistoryResponse> {
  const params = new URLSearchParams();
  if (deviceId) {
    params.set("device_id", deviceId);
  }
  return request<HistoryResponse>(`/v1/history?${params.toString()}`);
}

export function addTrustedDomain(payload: TrustedDomainRequest): Promise<TrustedDomainRecord> {
  return request<TrustedDomainRecord>("/v1/whitelist", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteTrustedDomain(domain: string, deviceId?: string): Promise<{ status: string; domain: string }> {
  const params = new URLSearchParams();
  if (deviceId) {
    params.set("device_id", deviceId);
  }
  return request<{ status: string; domain: string }>(`/v1/whitelist/${encodeURIComponent(domain)}?${params.toString()}`, {
    method: "DELETE",
  });
}

export function getTrustedDomains(deviceId?: string): Promise<WhitelistResponse> {
  const params = new URLSearchParams();
  if (deviceId) {
    params.set("device_id", deviceId);
  }
  return request<WhitelistResponse>(`/v1/whitelist?${params.toString()}`);
}
