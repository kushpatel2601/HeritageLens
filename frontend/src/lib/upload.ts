/**
 * Multipart upload with progress. `fetch` cannot report upload progress, so this uses XHR and
 * maps failures onto the same {@link ApiError} the rest of the client throws.
 */
import { ApiError, authHeaders, type Problem } from "./api/client";
import type { UploadResult } from "./api/types";

export const ACCEPTED_EXTENSIONS = [
  ".jpg",
  ".jpeg",
  ".png",
  ".webp",
  ".tif",
  ".tiff",
  ".pdf",
  ".pptx",
  ".docx",
  ".txt",
  ".md",
] as const;

/** Backend limit per request (`MAX_FILES` in backend/app/api/routes/assets.py). */
export const MAX_FILES_PER_REQUEST = 50;

export function isAccepted(name: string): boolean {
  const lower = name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

export function fileKey(file: Pick<File, "name" | "size" | "lastModified">): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

export function batches<T>(items: readonly T[], size = MAX_FILES_PER_REQUEST): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

export type UploadFields = Record<string, string | number | null | undefined>;

export function buildForm(files: readonly File[], fields: UploadFields): FormData {
  const form = new FormData();
  for (const file of files) form.append("files", file, file.name);
  for (const [key, value] of Object.entries(fields)) {
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (text) form.append(key, text);
  }
  return form;
}

export function uploadForm(
  form: FormData,
  token: string,
  onProgress: (loaded: number, total: number) => void,
  signal?: AbortSignal,
): Promise<UploadResult[]> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/v1/assets");
    xhr.responseType = "json";
    for (const [k, v] of Object.entries(authHeaders(token))) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded, e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as UploadResult[]);
      else reject(new ApiError(xhr.status, ((xhr.response as Problem | null) ?? {}) as Problem));
    };
    xhr.onerror = () => reject(new ApiError(0, { title: "The archive service is unreachable" }));
    xhr.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(form);
  });
}
