import type {
  FeedbackEvent,
  HistoryResponse,
  PrecheckResponse,
  ScanRecord,
  TrustedDomainRecord,
  WhitelistResponse,
} from "@phishguard/shared";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `API request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function fetchHistory(deviceId?: string): Promise<HistoryResponse> {
  const params = new URLSearchParams();
  if (deviceId) {
    params.set("device_id", deviceId);
  }
  return request<HistoryResponse>(`/v1/history?${params.toString()}`);
}

export function fetchFeedback(deviceId?: string): Promise<FeedbackEvent[]> {
  const params = new URLSearchParams();
  if (deviceId) {
    params.set("device_id", deviceId);
  }
  return request<FeedbackEvent[]>(`/v1/feedback?${params.toString()}`);
}

export function fetchWhitelist(deviceId?: string): Promise<WhitelistResponse> {
  const params = new URLSearchParams();
  if (deviceId) {
    params.set("device_id", deviceId);
  }
  return request<WhitelistResponse>(`/v1/whitelist?${params.toString()}`);
}

export function fetchReport(scanId: string): Promise<ScanRecord> {
  return request<ScanRecord>(`/v1/report/${encodeURIComponent(scanId)}`);
}

export function fetchReportByUrl(url: string, deviceId?: string): Promise<ScanRecord> {
  const params = new URLSearchParams();
  params.set("url", url);
  if (deviceId) {
    params.set("device_id", deviceId);
  }
  return request<ScanRecord>(`/v1/report/by-url?${params.toString()}`);
}

export function addTrustedDomain(domain: string, deviceId?: string): Promise<TrustedDomainRecord> {
  return request<TrustedDomainRecord>("/v1/whitelist", {
    method: "POST",
    body: JSON.stringify({
      domain,
      device_id: deviceId,
      source: "dashboard",
      note: "Added from dashboard",
    }),
  });
}

export function removeTrustedDomain(domain: string, deviceId?: string): Promise<{ status: string; domain: string }> {
  const params = new URLSearchParams();
  if (deviceId) {
    params.set("device_id", deviceId);
  }
  return request<{ status: string; domain: string }>(
    `/v1/whitelist/${encodeURIComponent(domain)}?${params.toString()}`,
    { method: "DELETE" },
  );
}

export async function runQuickPrecheck(url: string, deviceId?: string) {
  return request<PrecheckResponse>("/v1/precheck", {
    method: "POST",
    body: JSON.stringify({
      url,
      device_id: deviceId,
    }),
  });
}
