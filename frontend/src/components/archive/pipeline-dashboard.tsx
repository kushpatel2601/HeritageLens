"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronLeft, ChevronRight, Cpu, Radio, RotateCcw, Server, Zap } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { useLive } from "@/components/providers";
import { TokenField, useIngestToken } from "@/components/token-field";
import { Badge, EmptyState, ErrorState, LoadingBlock, Stat, StatusPill } from "@/components/ui/primitives";
import { api, ApiError, authHeaders, unwrap } from "@/lib/api/client";
import { jobListQuery, keys, statsQuery, workersQuery } from "@/lib/api/queries";
import type { Job, JobListParams, JobStatus, LiveEvent, Worker } from "@/lib/api/types";
import { JOB_LABELS, formatDuration, formatNumber, formatRelative, jobLabel } from "@/lib/format";

const LIMIT = 25;
const STATUS_FILTERS: { value: JobStatus | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "queued", label: "Queued" },
  { value: "leased", label: "Running" },
  { value: "failed", label: "Retrying" },
  { value: "dead", label: "Gave up" },
  { value: "succeeded", label: "Done" },
];
const COLAB_URL = process.env.NEXT_PUBLIC_COLAB_URL;

export function PipelineDashboard() {
  const live = useLive();
  return (
    <div className="space-y-8">
      <Overview liveOpen={live.status === "open"} />
      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <JobsTable liveOpen={live.status === "open"} />
        <aside className="space-y-6">
          <LiveFeed />
          <ConnectWorker />
        </aside>
      </div>
      <Workers />
    </div>
  );
}

function Overview({ liveOpen }: { liveOpen: boolean }) {
  const { data: stats } = useQuery(statsQuery());
  const jobs = stats?.jobs_by_status ?? {};
  const depth = stats?.queue_depth ?? {};
  const running = jobs.leased ?? 0;
  const problems = (jobs.failed ?? 0) + (jobs.dead ?? 0);
  return (
    <section aria-label="Pipeline overview" className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <div className="card p-4">
        <Stat
          label="Waiting for a GPU"
          value={stats ? formatNumber(depth.gpu ?? 0) : "—"}
          hint={
            <span className="inline-flex items-center gap-1">
              <Zap aria-hidden className="size-3" /> OCR, translation, captions, twins
            </span>
          }
        />
      </div>
      <div className="card p-4">
        <Stat
          label="Waiting for the CPU"
          value={stats ? formatNumber(depth.cpu ?? 0) : "—"}
          hint={
            <span className="inline-flex items-center gap-1">
              <Cpu aria-hidden className="size-3" /> Extraction and indexing
            </span>
          }
        />
      </div>
      <div className="card p-4">
        <Stat
          label="Running now"
          value={stats ? formatNumber(running) : "—"}
          hint={stats ? `${formatNumber(jobs.succeeded ?? 0)} done · ${formatNumber(problems)} failed` : undefined}
        />
      </div>
      <div className="card p-4">
        <Stat
          label="Workers online"
          value={stats ? formatNumber(stats.workers_online) : "—"}
          hint={
            <span className={clsx("inline-flex items-center gap-1", liveOpen ? "text-moss" : "text-muted")}>
              <Radio aria-hidden className="size-3" /> {liveOpen ? "Live updates on" : "Live updates paused"}
            </span>
          }
        />
      </div>
    </section>
  );
}

function JobsTable({ liveOpen }: { liveOpen: boolean }) {
  const [status, setStatus] = useState<JobStatus | "">("");
  const [queue, setQueue] = useState("");
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);
  const token = useIngestToken();
  const queryClient = useQueryClient();

  const request: JobListParams = {
    status: (status || undefined) as JobListParams["status"],
    queue: (queue || undefined) as JobListParams["queue"],
    type: (type || undefined) as JobListParams["type"],
    limit: LIMIT,
    offset: (page - 1) * LIMIT,
  };
  const { data, error, isPending, isFetching, refetch } = useQuery({
    ...jobListQuery(request),
    refetchInterval: liveOpen ? false : 10_000,
  });
  const retry = useMutation({
    mutationFn: (jobId: number) =>
      unwrap(
        api.POST("/api/v1/jobs/{job_id}/retry", { params: { path: { job_id: jobId } }, headers: authHeaders(token) }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.jobs() });
      void queryClient.invalidateQueries({ queryKey: keys.stats() });
    },
  });
  const authFailed = retry.error instanceof ApiError && retry.error.isAuth;
  const pages = data ? Math.max(1, Math.ceil(data.total / LIMIT)) : 1;
  const filter = (apply: () => void) => {
    apply();
    setPage(1);
  };

  return (
    <section aria-labelledby="jobs-heading" className="min-w-0 space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="jobs-heading" className="text-xl font-semibold">
          Jobs
        </h2>
        <div className="flex gap-2">
          <label>
            <span className="sr-only">Queue</span>
            <select className="field py-1.5 text-sm" value={queue} onChange={(e) => filter(() => setQueue(e.target.value))}>
              <option value="">Both queues</option>
              <option value="gpu">GPU queue</option>
              <option value="cpu">CPU queue</option>
            </select>
          </label>
          <label>
            <span className="sr-only">Job type</span>
            <select className="field py-1.5 text-sm" value={type} onChange={(e) => filter(() => setType(e.target.value))}>
              <option value="">Every step</option>
              {Object.entries(JOB_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-1.5">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s.value}
            type="button"
            className="chip"
            aria-pressed={status === s.value}
            onClick={() => filter(() => setStatus(s.value))}
          >
            {s.label}
          </button>
        ))}
      </div>

      {error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <LoadingBlock label="Loading jobs…" />
      ) : data.items.length === 0 ? (
        <EmptyState title="No jobs here">Nothing matches these filters right now.</EmptyState>
      ) : (
        <div className={clsx("card overflow-x-auto transition-opacity", isFetching && "opacity-70")}>
          <table className="w-full text-left text-sm sm:min-w-[40rem]">
            <caption className="sr-only">
              Pipeline jobs, newest first. {formatNumber(data.total)} in total.
            </caption>
            <thead className="border-b border-sandstone text-xs tracking-wide text-muted uppercase">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-semibold">Step</th>
                <th scope="col" className="px-3 py-2.5 font-semibold">Working on</th>
                <th scope="col" className="hidden px-3 py-2.5 font-semibold sm:table-cell">Status</th>
                <th scope="col" className="hidden px-3 py-2.5 font-semibold sm:table-cell">Timing</th>
                <th scope="col" className="px-4 py-2.5">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-sand">
              {data.items.map((job) => (
                <JobRow
                  key={job.id}
                  job={job}
                  onRetry={() => retry.mutate(job.id)}
                  retrying={retry.isPending && retry.variables === job.id}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p aria-live="polite" className="text-sm text-danger empty:hidden">
        {retry.error?.message}
      </p>
      {authFailed && <TokenField forceOpen />}

      {pages > 1 && (
        <nav aria-label="Job pages" className="flex items-center justify-between gap-3 text-sm">
          <button type="button" className="btn btn-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            <ChevronLeft aria-hidden className="size-4" /> Newer
          </button>
          <span className="text-muted tabular-nums">
            Page {page} of {pages}
          </span>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={page >= pages}
            onClick={() => setPage(page + 1)}
          >
            Older <ChevronRight aria-hidden className="size-4" />
          </button>
        </nav>
      )}
    </section>
  );
}

function JobRow({ job, onRetry, retrying }: { job: Job; onRetry: () => void; retrying: boolean }) {
  const failed = job.status === "failed" || job.status === "dead";
  const timing =
    job.status === "queued"
      ? `queued ${formatRelative(job.created_at)}`
      : job.status === "leased"
        ? `started ${formatRelative(job.started_at)}`
        : `${formatDuration(job.started_at, job.finished_at)} · ${formatRelative(job.finished_at ?? job.updated_at)}`;
  return (
    <tr className="align-top">
      <td className="px-4 py-3">
        <div className="flex items-center gap-2 font-medium">
          {job.queue === "gpu" ? (
            <Zap aria-label="GPU queue" className="size-3.5 shrink-0 text-ochre" />
          ) : (
            <Cpu aria-label="CPU queue" className="size-3.5 shrink-0 text-muted" />
          )}
          {jobLabel(job.type)}
        </div>
        <div className="mt-0.5 font-mono text-xs text-muted">#{job.id}</div>
        <div className="mt-1.5 space-y-1 sm:hidden">
          <StatusPill status={job.status} />
          <p className="text-xs text-muted">
            {timing}
            {job.attempts > 1 && ` · attempt ${job.attempts}/${job.max_attempts}`}
          </p>
        </div>
        {failed && job.error && <p className="mt-1 max-w-md text-xs break-words text-danger">{job.error}</p>}
      </td>
      <td className="max-w-[16rem] px-3 py-3">
        <JobSubject job={job} href="#pipeline" className="line-clamp-2 text-indigo-ink" />
      </td>
      <td className="hidden px-3 py-3 sm:table-cell">
        <StatusPill status={job.status} />
        {job.attempts > 1 && (
          <div className="mt-1 text-xs text-muted">
            attempt {job.attempts}/{job.max_attempts}
          </div>
        )}
        {job.status === "leased" && job.lease_owner && (
          <div className="mt-1 max-w-[10rem] truncate text-xs text-muted" title={job.lease_owner}>
            on {job.lease_owner}
          </div>
        )}
      </td>
      <td className="hidden px-3 py-3 text-xs whitespace-nowrap text-muted sm:table-cell">{timing}</td>
      <td className="px-2 py-3 text-right sm:px-4">
        {failed && (
          <button type="button" className="btn btn-ghost px-2 py-1 text-xs" onClick={onRetry} disabled={retrying}>
            <RotateCcw aria-hidden className={clsx("size-3", retrying && "animate-spin")} /> Retry
          </button>
        )}
      </td>
    </tr>
  );
}

type JobTarget = Pick<Job, "asset_id" | "asset_title" | "site_id" | "site_name" | "site_slug">;

/** What a job is working on: the item title or site name (the API joins them in), falling back to the id. */
function JobSubject({ job, href = "", className }: { job: JobTarget; href?: string; className?: string }) {
  const linkClass = clsx("underline-offset-2 hover:underline", className);
  if (job.asset_id != null) {
    const label = job.asset_title || `Item ${job.asset_id}`;
    return (
      <Link href={`/assets/${job.asset_id}${href}`} className={linkClass} title={label}>
        {label}
      </Link>
    );
  }
  if (job.site_id != null) {
    const label = job.site_name || `Site ${job.site_id}`;
    return job.site_slug ? (
      <Link href={`/sites/${job.site_slug}`} className={linkClass} title={label}>
        {label}
      </Link>
    ) : (
      <span className={clsx("text-muted", className)}>{label}</span>
    );
  }
  return <span className="text-muted">—</span>;
}

function LiveFeed() {
  const { status, events } = useLive();
  const recent = events.slice(0, 12);
  return (
    <section aria-labelledby="feed-heading" className="card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 id="feed-heading" className="font-semibold">
          Live activity
        </h2>
        <Badge tone={status === "open" ? "moss" : "neutral"}>
          <span
            aria-hidden
            className={clsx("size-1.5 rounded-full", status === "open" ? "animate-pulse bg-moss" : "bg-muted")}
          />
          {status === "open" ? "Connected" : status === "unsupported" ? "Unavailable" : "Connecting"}
        </Badge>
      </div>
      {recent.length ? (
        <ol className="space-y-2.5 text-sm" aria-live="polite" aria-relevant="additions">
          {recent.map((event) => (
            <FeedItem key={`${event.kind}-${event.data.id}-${event.receivedAt}`} event={event} at={event.receivedAt} />
          ))}
        </ol>
      ) : (
        <p className="text-sm text-muted">
          Events appear here the moment a worker picks up or finishes a job. Upload something on the{" "}
          <Link href="/contribute" className="text-terracotta underline">
            contribute page
          </Link>{" "}
          to watch it move through the pipeline.
        </p>
      )}
    </section>
  );
}

function FeedItem({ event, at }: { event: LiveEvent; at: number }) {
  const when = formatRelative(new Date(at).toISOString());
  if (event.kind === "job") {
    const job = event.data;
    return (
      <li className="flex items-start gap-2">
        <StatusPill status={job.status} className="shrink-0" />
        <div className="min-w-0">
          <p className="truncate">{jobLabel(job.type)}</p>
          <p className="truncate text-xs text-muted">
            {(job.asset_id != null || job.site_id != null) && (
              <>
                <JobSubject job={job} />
                {" · "}
              </>
            )}
            {when}
          </p>
        </div>
      </li>
    );
  }
  const asset = event.data;
  return (
    <li className="flex items-start gap-2">
      <StatusPill status={asset.status} className="shrink-0" />
      <div className="min-w-0">
        <Link href={`/assets/${asset.id}`} className="block truncate underline-offset-2 hover:underline">
          {asset.title}
        </Link>
        <p className="text-xs text-muted">{when}</p>
      </div>
    </li>
  );
}

function ConnectWorker() {
  return (
    <section aria-labelledby="connect-heading" className="card p-4">
      <h2 id="connect-heading" className="mb-1 flex items-center gap-2 font-semibold">
        <Zap aria-hidden className="size-4 text-ochre" /> Add GPU capacity
      </h2>
      <p className="mb-3 text-sm text-ink-soft">
        OCR, translation, captions and 3D twins run on any free Colab T4. The worker pulls jobs over HTTPS, so it
        needs no open ports, and you can run several at once.
      </p>
      <ol className="list-decimal space-y-2.5 pl-5 text-sm marker:text-muted">
        <li>
          Expose this server: <Code>cloudflared tunnel --url http://localhost:8000</Code>
        </li>
        <li>
          Open{" "}
          {COLAB_URL ? (
            <a href={COLAB_URL} target="_blank" rel="noreferrer" className="text-terracotta underline">
              the worker notebook in Colab
            </a>
          ) : (
            <Code>notebooks/heritage_gpu_worker.ipynb</Code>
          )}{" "}
          on a T4 runtime.
        </li>
        <li>
          Add Colab secrets <Code>HERITAGE_API_URL</Code> (the tunnel URL) and <Code>HERITAGE_TOKEN</Code> (the
          server&apos;s <Code>HL_WORKER_TOKEN</Code>).
        </li>
        <li>Run all cells. The worker appears below within seconds and the GPU queue starts draining.</li>
      </ol>
      <p className="mt-3 border-t border-sand pt-3 text-xs text-muted">
        No GPU handy? <Code>python -m heritage_gpu run --fake</Code> runs model-free engines that speak the same
        protocol.
      </p>
    </section>
  );
}

function Code({ children }: { children: ReactNode }) {
  return <code className="rounded bg-sand px-1 py-0.5 font-mono text-[0.8em] break-all text-ink">{children}</code>;
}

function Workers() {
  const { data, error, isPending, refetch } = useQuery(workersQuery());
  const [showAll, setShowAll] = useState(false);
  const sorted = [...(data ?? [])].sort(
    (a, b) => Number(b.online) - Number(a.online) || b.last_seen_at.localeCompare(a.last_seen_at),
  );
  const online = sorted.filter((w) => w.online);
  const visible = showAll ? sorted : online.length ? online : sorted.slice(0, 3);
  const hidden = sorted.length - visible.length;

  return (
    <section aria-labelledby="workers-heading" className="space-y-4">
      <h2 id="workers-heading" className="text-xl font-semibold">
        Workers
      </h2>
      {error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <LoadingBlock label="Loading workers…" />
      ) : sorted.length === 0 ? (
        <EmptyState title="No workers have connected yet">Start the API server or a Colab worker.</EmptyState>
      ) : (
        <>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {visible.map((worker) => (
              <WorkerCard key={worker.id} worker={worker} />
            ))}
          </ul>
          {(hidden > 0 || showAll) && (
            <button type="button" className="btn btn-ghost text-sm" onClick={() => setShowAll(!showAll)}>
              {showAll ? "Show online workers only" : `Show ${hidden} offline ${hidden === 1 ? "worker" : "workers"}`}
            </button>
          )}
        </>
      )}
    </section>
  );
}

function WorkerCard({ worker }: { worker: Worker }) {
  const gpu = worker.queue === "gpu";
  return (
    <li className={clsx("card p-4", !worker.online && "opacity-70")}>
      <div className="flex items-start gap-3">
        <span
          className={clsx(
            "grid size-9 shrink-0 place-items-center rounded-lg",
            gpu ? "bg-ochre-soft text-ochre" : "bg-indigo-soft text-indigo-ink",
          )}
        >
          {gpu ? <Zap aria-hidden className="size-4" /> : <Server aria-hidden className="size-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold">{worker.name}</p>
          <p className="truncate font-mono text-xs text-muted" title={worker.id}>
            {worker.device} · {worker.id}
          </p>
        </div>
        <Badge tone={worker.online ? "moss" : "neutral"}>{worker.online ? "Online" : "Offline"}</Badge>
      </div>
      <div className="mt-3 flex flex-wrap gap-1">
        {worker.capabilities.map((c) => (
          <Badge key={c} title={jobLabel(c)}>
            {c}
          </Badge>
        ))}
      </div>
      <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div>
          <dt className="text-muted">Done</dt>
          <dd className="font-semibold tabular-nums">{formatNumber(worker.jobs_done)}</dd>
        </div>
        <div>
          <dt className="text-muted">Failed</dt>
          <dd className={clsx("font-semibold tabular-nums", worker.jobs_failed > 0 && "text-danger")}>
            {formatNumber(worker.jobs_failed)}
          </dd>
        </div>
        <div>
          <dt className="text-muted">Last seen</dt>
          <dd className="font-semibold">{formatRelative(worker.last_seen_at)}</dd>
        </div>
      </dl>
    </li>
  );
}
