import createClient from "openapi-fetch";

import type { paths } from "./types";

/** RFC 7807 problem details, as produced by backend/app/core/errors.py. */
export interface Problem {
  title?: string;
  status?: number;
  detail?: unknown;
  request_id?: string;
}

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
  } catch (cause) {
    throw new ApiError(0, { title: "The archive service is unreachable", detail: String(cause) });
  }
  const { data, error, response } = result;
  if (error !== undefined || !response.ok) {
    const problem = (error && typeof error === "object" ? error : { detail: error }) as Problem;
    throw new ApiError(response.status, problem);
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
  } catch (cause) {
    throw new ApiError(0, { title: "The archive service is unreachable", detail: String(cause) });
  }
  if (!response.ok) {
    const problem = (await response.json().catch(() => ({}))) as Problem;
    throw new ApiError(response.status, problem);
  }
  return (await response.json()) as T;
}
