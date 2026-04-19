import { z } from "zod";
import {
  SnapPreviewResponseSchema,
  LabelDataSchema,
  SaveLabelResponseSchema,
} from "./schemas";
import type {
  PanelsInput,
  LabelData,
  SnapPreviewResponse,
  PanelCorners,
  BrowserError,
} from "./schemas";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public traceId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiFetch<T>(
  path: string,
  schema: z.ZodType<T>,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!res.ok) {
    const traceId = res.headers.get("X-Trace-ID") ?? undefined;
    const body = await res.json().catch(() => ({ message: res.statusText }));
    throw new ApiError(
      res.status,
      body.message || body.detail || res.statusText,
      traceId,
    );
  }
  const data = await res.json();
  return schema.parse(data);
}

export async function getLabels(sampleId: string): Promise<LabelData> {
  return apiFetch(`/api/labels/${sampleId}`, LabelDataSchema);
}

export async function saveLabels(
  sampleId: string,
  panels: PanelCorners[],
): Promise<{ status: string; sample_id: string; panel_count: number }> {
  return apiFetch(`/api/labels/${sampleId}`, SaveLabelResponseSchema, {
    method: "POST",
    body: JSON.stringify({ sample_id: sampleId, panels }),
  });
}

export async function snapPreview(
  input: PanelsInput,
): Promise<SnapPreviewResponse> {
  return apiFetch("/api/snap/preview", SnapPreviewResponseSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function reportError(error: BrowserError): void {
  fetch(`${API_BASE}/api/errors`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(error),
    keepalive: true,
  }).catch(() => {}); // fire-and-forget
}
