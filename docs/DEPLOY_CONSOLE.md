# The Deploy Console

Publishing something on ServerKit — a template, a repository, an upload, a manual
redeploy — should be the signature experience of the product. Other panels become
black boxes the moment something goes wrong: you click deploy, a spinner spins, and
when it fails you get a one-line error. ServerKit's promise is the opposite: **you
can always see what the machine is doing, and when it breaks you can debug it from
the UI without SSH.**

The Deploy Console delivers that. One click (or one wizard) takes you to a single
full-page live console at **`/deployments/<jobId>`** that shows the whole deploy
happening in real time.

## What you see

- **Header** — a humanized title ("Installing Umami Analytics", "Deploying my-api"),
  a status pill (Queued / Running / Succeeded / Failed), a step counter, and a live
  elapsed timer.
- **Step rail** — the job plan as a checklist: ✓ with per-step duration when done,
  a spinner on the current step, ✗ on the failed one, ○ pending. Click a step to
  scroll the log to its first line.
- **Log pane** — a dark, monospace, terminal-style surface that streams real build
  output line-by-line, level-colored, with **Follow / Wrap / Timestamps**, a level
  filter, client-side **Search**, **Copy** and **Download .txt**. Follow disengages
  when you scroll up and re-engages via a "Jump to live" chip.
- **On failure** — a pinned error card shows the failed step, the **failure tail**
  (the last ~80 lines of the *real* build output, not a stripped stderr fragment),
  the one-line error, and — when a heuristic matches — a plain-language **hint**
  ("Another service is already using this port — change the port mapping and retry").
  Actions: **Retry deploy** (clones the job and swaps the console to the new run),
  **Copy error**, and **Ask AI** (opens the assistant seeded with the tail).
- **On success** — a completion banner with total duration, per-step timings, and
  the payoff actions: **Open app**, **View service**, **View runtime logs**.
- **Degraded** — if the websocket is unavailable the console says so and keeps
  working on a 2-second poll. It is never blank and never silently frozen.
- **History** — opening the console for a finished job renders everything from the
  database (full log, timings, error card). Console URLs are permanent, shareable
  links to a deploy.

## Every flow ends up here

Template one-click installs, Git-repo service creation, uploads with auto-deploy,
manual redeploys, and the Build tab's "Deploy Now" all enqueue a **DeploymentJob**
and navigate to the console. The `/deployments` index lists every past and active
run and deep-links each row to its console.

## How it works (architecture)

- **`RunLogStream`** (`backend/app/services/run_log_service.py`) is the single write
  seam for all deploy-path logging. It batches writes (one DB commit + one socket
  emit per flush — on 50 lines, 300 ms, a step change, or close), keeps a truthful
  80-line in-memory failure tail, records per-step timings, sanitizes ANSI escapes
  and `\r` progress overwrites, caps persisted rows at 5000 per job, and matches a
  failure hint. `RunLogStream.log()` never raises — a stuck "running" job is worse
  than a missing log line.
- **Persistence is the source of truth.** Every line is a `DeploymentJobLog` row;
  step timings, the failure tail and the hint live in the job's `result` JSON (no
  schema migration). The read API exposes incremental polling via
  `GET /deployment-jobs/<id>/logs?after_id=`.
- **Sockets are an accelerator.** `RunLogStream` emits `deploy_log` (a batch of
  persisted lines, each carrying its DB id) and `deploy_status` (the job summary) to
  room `deploy_{job_id}`. The frontend hook `useDeployJobStream` boots from a full
  snapshot, prefers the socket channel, de-dupes by id, re-syncs with `after_id` on
  every reconnect, and falls back to a 2-second poll — so the console is 100%
  functional with sockets disabled. In-process emits only (single-worker gateway
  constraint; see [ARCHITECTURE.md](ARCHITECTURE.md)).
- **Streaming builds.** `DockerService.compose_up_streaming` runs compose with
  `--ansi never --progress plain` under `Popen` and delivers output line-by-line, so
  template installs stream the real pull/build transcript and a failure persists a
  meaningful tail — historically the biggest reason install errors were unreadable.
- **Every deploy is a job.** `POST /apps/<id>/deploy` returns `202 {deploy_job_id}`
  (or runs synchronously with `?wait=true` for CLI/tests). Failed jobs can be retried
  via `POST /deployment-jobs/<id>/retry`, which clones the job and enqueues a fresh
  run on a new console URL.

## Follow-ups (not yet shipped)

- WordPress site creation adopting the console (via the plugins SDK).
- Agent-side line streaming for remote-server installs (a protocol addition in the
  `serverkit-agent` repo); until then remote installs render as a labeled output
  block.
- A cancel-running-deploy button (needs safe subprocess-kill semantics).
