import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, authHeaders } from "@/lib/api/client";
import { batches, buildForm, fileKey, isAccepted, MAX_FILES_PER_REQUEST, uploadForm } from "@/lib/upload";

describe("isAccepted", () => {
  it("accepts supported extensions case-insensitively", () => {
    for (const name of ["vav.JPG", "notebook.tiff", "survey.pdf", "talk.pptx", "diary.md"]) {
      expect(isAccepted(name)).toBe(true);
    }
  });

  it("rejects everything else, including disguised names", () => {
    for (const name of ["setup.exe", "photo.jpg.exe", "archive.zip", "jpg"]) {
      expect(isAccepted(name)).toBe(false);
    }
  });
});

describe("batches", () => {
  it("splits into requests of at most the backend limit", () => {
    const sizes = batches(Array.from({ length: 120 }, (_, i) => i)).map((b) => b.length);
    expect(sizes).toEqual([MAX_FILES_PER_REQUEST, MAX_FILES_PER_REQUEST, 20]);
  });

  it("keeps order and handles empty input", () => {
    expect(batches([1, 2, 3], 2)).toEqual([[1, 2], [3]]);
    expect(batches([])).toEqual([]);
  });
});

describe("buildForm", () => {
  it("repeats the files field and keeps only non-blank metadata", () => {
    const a = new File(["a"], "a.jpg", { type: "image/jpeg" });
    const b = new File(["b"], "b.pdf", { type: "application/pdf" });
    const form = buildForm([a, b], { title: "  Rani ki Vav  ", site_id: 3, lat: 0, caption: "   ", kind: null, lon: undefined });
    expect(form.getAll("files").map((f) => (f as File).name)).toEqual(["a.jpg", "b.pdf"]);
    expect(form.get("title")).toBe("Rani ki Vav");
    expect(form.get("site_id")).toBe("3");
    expect(form.get("lat")).toBe("0");
    expect(form.has("caption")).toBe(false);
    expect(form.has("kind")).toBe(false);
    expect(form.has("lon")).toBe(false);
  });

  it("identifies files by name, size and modification time", () => {
    expect(fileKey({ name: "a.jpg", size: 10, lastModified: 5 })).toBe("a.jpg:10:5");
  });
});

class FakeXHR {
  static last: FakeXHR;
  method = "";
  url = "";
  responseType = "";
  status = 0;
  response: unknown = null;
  headers: Record<string, string> = {};
  body: unknown;
  upload: { onprogress: ((e: Partial<ProgressEvent>) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  send(body: unknown) {
    this.body = body;
    FakeXHR.last = this;
  }
  abort() {
    this.onabort?.();
  }
  respond(status: number, response: unknown) {
    this.status = status;
    this.response = response;
    this.onload?.();
  }
}

describe("uploadForm", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("posts with auth, reports progress and resolves with the results", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    const progress = vi.fn();
    const form = new FormData();
    const pending = uploadForm(form, "secret", progress);
    const xhr = FakeXHR.last;
    expect([xhr.method, xhr.url, xhr.responseType, xhr.body]).toEqual(["POST", "/api/v1/assets", "json", form]);
    expect(xhr.headers).toEqual(authHeaders("secret"));

    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 });
    xhr.upload.onprogress?.({ lengthComputable: false, loaded: 7, total: 0 });
    expect(progress).toHaveBeenCalledExactlyOnceWith(5, 10);

    const results = [{ created: true, job_ids: [1] }];
    xhr.respond(201, results);
    await expect(pending).resolves.toEqual(results);
  });

  it("rejects with an ApiError describing the server's problem", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    const pending = uploadForm(new FormData(), "", () => {});
    expect(FakeXHR.last.headers).toEqual({});
    FakeXHR.last.respond(413, { detail: "File exceeds 200 MB" });
    const error = await pending.catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 413, message: "File exceeds 200 MB" });
  });

  it("rejects with an AbortError when cancelled", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    const controller = new AbortController();
    const pending = uploadForm(new FormData(), "t", () => {}, controller.signal);
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });

  it("reports an unreachable server as status 0", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    const pending = uploadForm(new FormData(), "t", () => {});
    FakeXHR.last.onerror?.();
    await expect(pending).rejects.toMatchObject({ status: 0 });
  });
});
