"use client";

import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { Box, Check } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { useLiveEvent } from "@/components/providers";
import { TokenField, useIngestToken } from "@/components/token-field";
import { StatusPill } from "@/components/ui/primitives";
import { Thumb } from "@/components/ui/thumb";
import { api, ApiError, authHeaders, unwrap } from "@/lib/api/client";
import type { AssetBrief, TwinMethod } from "@/lib/api/types";

const SPLAT_MIN = 8;

const METHODS: { value: TwinMethod; title: string; detail: string }[] = [
  {
    value: "depth-relief",
    title: "Depth relief",
    detail: "Monocular depth estimation turns each photo into a coloured 3D relief. Works from a single image.",
  },
  {
    value: "gaussian-splat",
    title: "Gaussian splat",
    detail: `Full scene reconstruction from ${SPLAT_MIN}+ overlapping photos walked around the monument.`,
  },
];

/** Queues a `reconstruct3d` job for the GPU worker (Colab T4/A100) and follows it over SSE. */
export function TwinBuilder({ slug, photos }: { slug: string; photos: AssetBrief[] }) {
  const token = useIngestToken();
  const [selected, setSelected] = useState<Set<number>>(() => new Set(photos.slice(0, 1).map((p) => p.id)));
  const [method, setMethod] = useState<TwinMethod>("depth-relief");
  const [title, setTitle] = useState("");
  const [jobStatus, setJobStatus] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/sites/{slug}/twins", {
          params: { path: { slug } },
          body: { asset_ids: [...selected], method, title: title.trim() || null },
          headers: authHeaders(token),
        }),
      ),
    onSuccess: (job) => setJobStatus(job.status),
  });

  const jobId = mutation.data?.id;
  useLiveEvent((event) => {
    if (event.kind === "job" && event.data.id === jobId) setJobStatus(event.data.status);
  });

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const splatBlocked = method === "gaussian-splat" && selected.size < SPLAT_MIN;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!selected.size || splatBlocked) return;
    mutation.mutate();
  };
  const authFailed = mutation.error instanceof ApiError && mutation.error.isAuth;

  if (!photos.length) {
    return <p className="text-sm text-muted">Upload processed photographs of this site to build a digital twin.</p>;
  }

  return (
    <form onSubmit={submit} className="space-y-4" aria-describedby="twin-help">
      <p id="twin-help" className="text-sm text-ink-soft">
        Pick the photographs to reconstruct from. The job is queued for a GPU worker; the model appears here
        automatically when it is ready.
      </p>

      <fieldset>
        <legend className="mb-2 text-sm font-semibold">
          Source photographs <span className="font-normal text-muted">({selected.size} selected)</span>
        </legend>
        <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {photos.map((p) => {
            const on = selected.has(p.id);
            return (
              <li key={p.id}>
                <label
                  className={clsx(
                    "relative block cursor-pointer overflow-hidden rounded-lg border-2 transition-colors focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-indigo-ink",
                    on ? "border-terracotta" : "border-transparent",
                  )}
                >
                  <input type="checkbox" className="sr-only" checked={on} onChange={() => toggle(p.id)} />
                  <Thumb src={p.thumb_url} alt={p.title} className="aspect-square w-full" />
                  {on && (
                    <span className="absolute top-1 right-1 rounded-full bg-terracotta p-0.5 text-white">
                      <Check aria-hidden className="size-3.5" />
                    </span>
                  )}
                </label>
              </li>
            );
          })}
        </ul>
      </fieldset>

      <fieldset className="grid gap-2 sm:grid-cols-2">
        <legend className="mb-2 text-sm font-semibold">Reconstruction method</legend>
        {METHODS.map((m) => (
          <label
            key={m.value}
            className="flex cursor-pointer gap-2 rounded-lg border border-sandstone bg-white p-3 has-checked:border-indigo-ink has-checked:ring-1 has-checked:ring-indigo-ink"
          >
            <input
              type="radio"
              name="method"
              value={m.value}
              checked={method === m.value}
              onChange={() => setMethod(m.value)}
              className="mt-1 accent-indigo-ink"
            />
            <span>
              <span className="block font-semibold">{m.title}</span>
              <span className="block text-xs text-muted">{m.detail}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {splatBlocked && (
        <p className="text-sm text-danger" role="status">
          Select at least {SPLAT_MIN} photographs for Gaussian splatting ({selected.size} selected).
        </p>
      )}

      <div>
        <label htmlFor="twin-title" className="mb-1 block text-sm font-semibold">
          Title <span className="font-normal text-muted">(optional)</span>
        </label>
        <input
          id="twin-title"
          value={title}
          maxLength={200}
          onChange={(e) => setTitle(e.target.value)}
          className="field"
          placeholder="e.g. West gallery relief"
        />
      </div>

      <TokenField forceOpen={authFailed} />

      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" className="btn btn-primary" disabled={mutation.isPending || !selected.size || splatBlocked}>
          <Box aria-hidden className="size-4" />
          {mutation.isPending ? "Queuing…" : "Build digital twin"}
        </button>
        <div aria-live="polite" className="flex items-center gap-2 text-sm">
          {mutation.isError && <span className="text-danger">{mutation.error.message}</span>}
          {jobId !== undefined && jobStatus && (
            <>
              <StatusPill status={jobStatus} />
              <span>
                Job #{jobId}{" "}
                {jobStatus === "succeeded"
                  ? "finished. The new model is listed above."
                  : jobStatus === "queued"
                    ? "is waiting for a GPU worker."
                    : jobStatus === "leased"
                      ? "is running on a GPU worker."
                      : "did not complete."}{" "}
                <Link href="/archive/pipeline" className="font-semibold text-indigo-ink underline">
                  Pipeline
                </Link>
              </span>
            </>
          )}
        </div>
      </div>
    </form>
  );
}
