import createClient from "openapi-fetch";

import type { paths } from "./types";

/** RFC 7807 problem details, as produced by backend/app/core/errors.py. */
export interface Problem {
  title?: string;
  status?: number;
  detail?: unknown;
  request_id?: string;
}

const GATEWAY_STATUSES = new Set([502, 503, 504]);

export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem;

  constructor(status: number, problem: Problem) {
    super(describeProblem(status, problem));
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  get isAuth(): boolean {
    return this.status === 401 || this.status === 403;
  }

  /** The API could not be reached (offline, or the free host is asleep or restarting): worth retrying. */
  get isUnavailable(): boolean {
    return this.status === 0 || GATEWAY_STATUSES.has(this.status);
  }
}

/** What a sleeping or restarting host returns instead of an API response (usually an HTML page). */
export const WAKING_PROBLEM: Problem = {
  title: "The archive server is waking up",
  detail:
    "The free server sleeps when nobody has used it for a while and takes up to a minute to start. Please try again in a moment.",
};

/** A request that never got a response (offline, DNS, or a reply that was not JSON). */
export const UNREACHABLE_PROBLEM: Problem = {
  title: "Couldn't reach the archive server",
  detail: "Check your connection and try again. If the free server was asleep, it may need up to a minute to start.",
};

/**
 * Turn an error body into a {@link Problem}. Gateway and hosting error pages (HTML, not RFC 7807 JSON) become
 * {@link WAKING_PROBLEM} so their markup is never shown to people.
 */
export function toProblem(status: number, body: unknown): Problem {
  if (body && typeof body === "object" && ("title" in body || "detail" in body || !GATEWAY_STATUSES.has(status))) {
    return body as Problem;
  }
  const text = typeof body === "string" ? body.trim() : "";
  if (GATEWAY_STATUSES.has(status) || text.startsWith("<")) return WAKING_PROBLEM;
  return text ? { detail: text.length > 300 ? `${text.slice(0, 300)}…` : text } : {};
}

export function describeProblem(status: number, problem: Problem): string {
  const { title, detail } = problem;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
      .join("; ");
  }
  return title ?? `Request failed (${status})`;
}

const isServer = typeof window === "undefined";

/**
 * Same-origin in the browser (Next rewrites /api/* to FastAPI); direct to the API service when
 * rendering on the server, where relative URLs do not resolve.
 */
export const API_BASE = isServer ? (process.env.API_ORIGIN ?? "http://127.0.0.1:8000").replace(/\/+$/, "") : "";

export const api = createClient<paths>({ baseUrl: API_BASE });

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Unwrap an openapi-fetch result, turning error bodies into a typed {@link ApiError}. */
export async function unwrap<T>(promise: Promise<Result<T>>): Promise<T> {
  let result: Result<T>;
  try {
    result = await promise;
  } catch {
    throw new ApiError(0, UNREACHABLE_PROBLEM);
  }
  const { data, error, response } = result;
  if (error !== undefined || !response.ok) {
    throw new ApiError(response.status, toProblem(response.status, error));
  }
  return data as T;
}

export function authHeaders(token: string | null | undefined): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Plain GET for endpoints that are untyped in OpenAPI (GeoJSON layers return free-form dicts). */
export async function getJSON<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError(0, UNREACHABLE_PROBLEM);
  }
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    let body: unknown = text;
    try {
      body = JSON.parse(text);
    } catch {
      // Not JSON: a hosting or gateway error page.
    }
    throw new ApiError(response.status, toProblem(response.status, body));
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(0, UNREACHABLE_PROBLEM);
  }
}
