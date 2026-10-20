# Remote worker deployments (ephemeral GPU nodes over WireGuard)

Status: mechanism implemented and validated on this host; a real Vast.ai node
was provisioned and confirmed to run the pushed image (see findings below).
Hub finalized on the home server (WireGuard hub + containerized backend, reachable over the tunnel).
Date: 2026-10-15.

## Model

GPU worker nodes are **temporary** (Vast.ai). Each node dials **out** to the
backend hub over WireGuard, so no inbound ports are opened on the NAT'd/dynamic
instance. Nothing durable lives on the node: inputs are pulled from backend
object storage and every result is **pushed back** to it. The ACE-Step engine
server is **co-located** on the node (worker→engine is `localhost`).

## Topology (hub-and-spoke)

- **Hub (backend)**: API (50555), dispatcher, PostgreSQL, Redis and the
  S3-compatible store. These are reachable only over the tunnel; the API is the
  only public entry point.
- **Worker node**: joins the mesh, pulls the prebuilt image, runs one container
  that supervises the private ACE-Step server (8001) plus the engine/training
  worker role(s).
- On this host the hub is a member of the existing "Simple Server Networks"
  WireGuard mesh (`10.201.0.0/24`, hub "mercury"); the node reaches it at the
  hub's mesh address (e.g. `10.201.0.2`).

## Base image (Docker Hub)

`stratastack/oal-worker:<runtime-tag>` (tag `ca1e85f-torch2.10-cu128`) is a
**single combined image**: the pinned ACE-Step 1.5 runtime (upstream `ca1e85f`,
torch via `uv.lock`) plus our worker dependencies. Built once and pushed to
Docker Hub; ephemeral nodes `docker pull` it (no on-node build). Our application
code is **not** baked — see the code bundle.

## int8 DiT + XL/SFT premium on Vast workers

Vast nodes run the int8-baked image `stratastack/oal-worker:house-v1-070-int8`
(`OAL_WORKER_IMAGE` in the hub's `.env.backend`, consumed by `scripts/autoscale.py`).
That is the `house-v1-070` base — which **bakes the HF-unavailable merged
`acestep-v15-house-turbo`**, the Vast default `OAL_ACESTEP_MODEL` — plus the env-gated
int8 DiT-quantization patch (`Dockerfile.worker_int8` overlay; the same patch is applied
from source with `git apply`+grep-guard in `Dockerfile.worker`). `Dockerfile.worker_int8_wg`
is a lighter `ca1e85f-torch2.10-cu128-wg` overlay for a hypothetical turbo-only fleet that
does **not** need the House model.

`autoscale.py::worker_env` gives engine nodes the premium/XL env (gated by
`OAL_VAST_PREMIUM`, default on): `ACESTEP_QUANTIZATION=int8_weight_only`,
`ACESTEP_OFFLOAD_TO_CPU=1`, `OAL_PREMIUM_PROFILES_ENABLED`, and the
`OAL_XL_CHECKPOINT_ID`/`OAL_XL_TURBO_CHECKPOINT_ID` ids. Nodes are already ≥24 GB
(`pick_offer` min_vram), profiles self-gate on `vram_required_mb`, and XL/SFT checkpoints
download from HuggingFace on the first premium job (Vast cannot bind-mount them), so
`OAL_VAST_DISK` is sized generously (160). Validated: a launched RTX 3090 (24576 MB)
pulled `house-v1-070-int8`, booted the int8 engine, fetched the app bundle, and registered
as a live worker before teardown.

## Code bundle (container-initiated over the tunnel)

`GET /internal/v1/worker/bundle` returns a `tar.gz` of `app/` plus a `REVISION`
file, with an `X-OAL-Revision` header. After WireGuard connects, the container
fetches it from the backend and unpacks it, so the backend is the source of
truth for the worker code revision and code iteration never rebuilds the heavy
image.

## Storage (durable across hosts)

Current hub (home server): the plain filesystem backend (`LocalObjectStorage`,
`OAL_STORAGE_BACKEND=local`) rooted at `/srv/oal-storage/oal` on the 1TB drive,
NFS-exported **to the WireGuard subnet only** (`10.203.0.0/24`). The baseline
worker bind-mounts the host's NFS automount (`/mnt/oal-storage` → `/data/oal`).
Vast burst nodes cannot mount NFS (Vast containers lack CAP_SYS_ADMIN *and*
NET_ADMIN -- kernel WireGuard and kernel NFS both fail, and userspace Tailscale
cannot route raw app TCP without the route), so they dial the hub's **public
IP** and write to container-local disk; an entrypoint sidecar rsync-pushes
`/data/oal/` to `administrator@hub:/srv/oal-storage/oal/` over ssh every 2 s
(`OAL_PUSH_TARGET` + `OAL_PUSH_PRIVKEY_B64`, deploy key `~/.ssh/oal_worker_deploy`
on the hub). Redis is public with `requirepass` (`OAL_REDIS_PASSWORD`);
Postgres uses password auth. LocalStack was dropped 2026-10-16: Community 3.8.1
does not persist S3 state (persistence is a Pro feature) and MinIO is not
anonymously pullable on these hosts. The `S3ObjectStorage` adapter remains for
a future VPS/managed-S3 hub. Workers push every artifact to the store; the API
proxies ranged reads so the bucket stays private. Trained LoRA adapters are
uploaded and recorded as an object prefix + file list, so a profile trained on
one node can be loaded (downloaded to a node-local cache) anywhere.

## Ephemeral node boot sequence

1. Join WireGuard; confirm reachability to the hub.
2. `docker pull` the worker image.
3. Start the container (`docker-compose.worker.yml`).
4. Container fetches the code bundle from the backend over the tunnel.
5. Provision pinned checkpoints to a volume (download + size-verify on boot).
6. ACE-Step server loads; the worker self-registers and consumes its queue.
7. Tear the node down: nothing durable is lost; the next job re-provisions.

## Files

- `Dockerfile.worker`, `docker/worker-entrypoint.sh` — combined image + bootstrap.
- `docker-compose.worker.yml`, `.env.worker.example` — node deployment.
- `deploy/wireguard/worker-peer.conf.template` — node peer config.
- `app/storage.py` (`S3ObjectStorage`, `build_storage`), `app/routes/internal.py`
  (bundle endpoint), training/engine adapter persistence in `app/training_worker.py`
  and `app/engine_worker.py`.

## Validation evidence (this host, real pushed image)

Ran the pushed `stratastack/oal-worker` image as a container (GPU, host network,
S3/DB/Redis/bundle at the hub, **no shared artifacts volume**):

| Step | Result |
| --- | --- |
| Container fetches code bundle over HTTP | revision `99c2999` unpacked |
| Co-located ACE-Step server | ready on 8001 (RTX PRO 4000) |
| Generation job | succeeded (engine worker in the container) |
| Artifact push-back | `owners/<owner>/jobs/<job>/<attempt>/mix_wav.wav` in S3 |
| API delivery from S3 | 200, valid RIFF, 2,304,044 bytes |

## Vast.ai provisioning findings (2026-10-15)

Provisioned a real on-demand instance (contract `56151437`) and confirmed it
loads and runs the pushed image on remote hardware, then destroyed it to avoid
idle spend. Findings for the go-live pass:

- **Offer class**: an RTX PRO 4000 (24 GB — same class as the dev host), Ontario
  CA, driver 590, reliability 1.00, ran at ~$0.285/hr on-demand. `vastai` CLI
  (`pip install vastai`) reads the key from `~/.config/vastai/vast_api_key`.
- **Image gaps**: the worker image has **no `sshd`** (so Vast's SSH launch mode
  refused) and **no `wireguard-tools`**. Go-live should either bake
  `wireguard-tools` into the image or run the container with `NET_ADMIN` + a
  `wg0.conf` and bring the tunnel up in the entrypoint.
- **Transport**: the hub is reachable only on the mesh address (`10.201.0.2`);
  the router does **not** forward 50555, so the public IP is not a fallback —
  the node must be on the WireGuard mesh.
- **Remaining go-live steps**: (1) add `wireguard-tools` to the image (or
  `NET_ADMIN` + entrypoint `wg-quick up`); (2) add the node as a peer on the
  mercury hub; (3) expose hub PostgreSQL/Redis on the tunnel (they are
  loopback-bound today); (4) run the container pointed at `10.201.0.2` and
  validate one real generation end-to-end.

## Known limits / deferred

- This host is a WireGuard **client** to the mercury mesh; admitting a new node
  peer depends on hub (mercury) routing. A dedicated hub (the future VPS) makes
  this a plain hub-and-spoke.
- MinIO image pulls on this host hit Docker Hub anonymous-pull limits; local
  validation used `moto_server`. Production runs MinIO on the hub.
- The combined container supervises the server + worker(s) with a simple
  `wait`; a full process supervisor (restart/backoff) is a later hardening step.
- Checkpoints download to a volume on first boot (slower cold start, smaller
  image); a pre-baked volume is an option for faster scale-out.

## Finalized hub configuration (home server)

Decision: the **home server** (`192.151.156.124`) is the WireGuard hub and hosts
the containerized backend; ephemeral worker nodes are WireGuard **clients** of
the home server (star topology), so they never need to be mercury peers.

- **Hub interface**: `wg2` on the home server, subnet **`10.203.0.0/24`**, hub
  address **`10.203.0.1`**, **UDP 51822** (UFW-allowed). `ip_forward` is already
  on; clients reach hub-local services directly (no NAT needed).
- **Worker client config**: `Endpoint = 192.151.156.124:51822`,
  `AllowedIPs = 10.203.0.0/24`, `PersistentKeepalive = 25`; the hub adds each
  node as a peer (`AllowedIPs = <node>/32`). See
  `deploy/wireguard/worker-peer.conf.template`.
- **Backend (containerized)**: `docker-compose.backend.yml` runs api, dispatcher,
  postgres, redis, object-storage (S3), migrate, bucket-init and maintenance on
  the hub, published on `0.0.0.0` so both tunnel peers and public-IP nodes reach
  them — API `:50555`, Postgres `:55432` (55432 avoids florist's
  `127.0.0.1:5432`), Redis `:6379`, S3 `:9000`. Image `stratastack/oal-backend:<rev>`
  (slim FastAPI, no torch). Tunnel peers (dev host) point `OAL_*` at `10.203.0.1`;
  Vast nodes point them at the public IP `192.151.156.124`.
- **S3 note**: localstack 3.8.1 is used here because MinIO is not pullable on
  these hosts (removed from Docker Hub; quay.io anonymous pulls 401; localstack
  2026.x needs a license token). Production should use MinIO (with a quay login)
  or managed S3.

Validation (2026-10-15): the dev host joined as a client (`10.203.0.2`),
handshook and pinged the hub (~42 ms); the containerized backend came up on the
home server and `GET /api/v1/health/live` and `/api/v1/health/ready` both
returned **200 over the tunnel** from the dev host (API + Postgres + Redis
reachable from a remote node).


## End-to-end validation (home-server hub, 2026-10-15)

A worker on the dev host (engine worker + the co-located ACE-Step server)
consumed a job from the home-server backend over the tunnel and completed a real
generation:

| Step | Result |
| --- | --- |
| Submit `POST /jobs` over the tunnel | 202 queued |
| Worker consumes from hub Redis (`10.203.0.1`) | job picked up |
| Generation via co-located ACE-Step | status **succeeded** |
| Artifact push-back to hub S3 | `owners/<owner>/jobs/<job>/<attempt>/mix_wav.wav` |
| API delivery over the tunnel | 200, 2,304,044 bytes, valid RIFF |

This confirms the full remote-worker flow against the containerized home-server
backend over the WireGuard overlay.

## Vast.ai end-to-end (public-IP hub, 2026-10-16)

Ran a real on-demand Vast node against the home-server hub and completed a full
generation end-to-end. Two findings changed the transport decision:

- **NET_ADMIN is not available** in Vast containers: `ip link add wg0 type
  wireguard` → `RTNETLINK answers: Operation not permitted`. Passing
  `--cap-add NET_ADMIN` or `--privileged` through the CLI `--env` string did not
  change this, so **in-container WireGuard is not usable on Vast** via the CLI.
- **Vast's default launch mode needs an `ssh` binary** the image lacks; without
  it `/.launch` loops on `ssh: command not found` and the image entrypoint never
  runs. Use **args launch mode** (`--args <cmd>`) so Vast runs the image
  entrypoint as-is (no sshd injection).

Therefore Vast workers connect to the hub over the hub's **public IP** (the home
server holds `192.151.156.124` directly on `ens18`, gateway `.121`, no router
NAT). `docker-compose.backend.yml` now publishes the worker-facing services on
`0.0.0.0` (API `:50555`, Redis `:6379`, S3 `:9000`, Postgres `:55432`) and UFW
allows them; the WireGuard overlay still serves trusted peers (the dev host).

Working recipe (cheapest NA Blackwell; image cached on the host → ~2–3 min to
consuming):

```
vastai create instance <offer> \
  --image stratastack/oal-worker:ca1e85f-torch2.10-cu128-wg --disk 40 \
  --env "-e OAL_BACKEND_URL=http://192.151.156.124:50555 \
         -e OAL_REDIS_URL=redis://192.151.156.124:6379/0 \
         -e OAL_DATABASE_URL=postgresql+psycopg2://oal:<pw>@192.151.156.124:55432/oal \
         -e OAL_STORAGE_BACKEND=s3 -e OAL_S3_ENDPOINT_URL=http://192.151.156.124:9000 \
         -e OAL_S3_BUCKET=oal -e OAL_S3_REGION=us-east-1 \
         -e OAL_S3_ACCESS_KEY=oal -e OAL_S3_SECRET_KEY=<s3secret> \
         -e OAL_SECRET_KEY=<secret> -e OAL_WORKER_ROLE=engine_worker \
         -e OAL_ACESTEP_BASE_URL=http://127.0.0.1:8001" \
  --args run
```

Evidence (contract `56173069`, RTX 5060 Ti 16 GB, ~$0.13–0.17/hr):

| Step | Result |
| --- | --- |
| Entrypoint fetches code bundle from public API | revision `ede182f` |
| Co-located ACE-Step on the node | ready on 8001 (RTX 5060 Ti) |
| `POST /jobs` over the public hub | 202 queued → consumed by the node |
| Generation | status **succeeded** |
| Artifact push-back to hub S3 | `owners/<owner>/jobs/<job>/<attempt>/mix_wav.wav` |
| API delivery over the public hub | 200, 2,304,044 bytes, valid RIFF |

Notes: the first generation is slow (the model loads on first request on the
consumer card); a warm node is faster. Exposing Redis/Postgres/S3 publicly is
fine for validation; production should firewall the hub to worker IPs (or use a
VPS hub) and MinIO/managed S3. The `wireguard-tools`/entrypoint wg bring-up stays
in the image for tunnel peers (dev host) even though Vast uses the public IP.

## Queue-depth autoscaling (local baseline + Vast burst)

Policy (multi-node, tiered scale-down): the dev host's GPU 0 runs an always-on
engine worker (the baseline, `OAL_SCALE_BASELINE_WORKERS`, default 1). Desired
Vast burst nodes are `0` while the engine queue `oal:queue:ace-step-1.5` is below
`OAL_SCALE_UP_DEPTH` (default 2), else `max(0, min(ceil(depth /
OAL_SCALE_JOBS_PER_NODE), OAL_SCALE_MAX_NODES) - baseline)` (defaults 2 and 3) —
`OAL_SCALE_MAX_NODES` caps **total** workers (baseline + Vast), so a deep queue
scales out to several nodes, adding at most one per 15s tick. Scale-down is
driven by how long demand has been low (depth < `OAL_SCALE_UP_DEPTH`): hold the
fleet for `OAL_SCALE_TO_ONE_SECONDS` (default 300s), then drop to **one hot
node**, then tear it down after `OAL_SCALE_DOWN_SECONDS` (default 1800s = 30 min)
of low demand; any spike back to ≥ `OAL_SCALE_UP_DEPTH` resets the timer. A node
younger than `OAL_VAST_MIN_UPTIME` (default 180s) is never removed.
`scripts/autoscale.py` runs on the **hub (home server)** — it needs `vastai` +
hub reachability (redis is local there) and no GPU — polls every 15s, and
persists its managed node list to a state file so restarts don't orphan instances.
A create is tracked whenever Vast returns a `new_contract` (even if the CLI prints
`success: False`), so a booted-but-reported-failed node is never leaked.

- **Offer selection**: among North-American offers passing `gpu_ram>=16`,
  `cuda_max_good>=12.8`, `verification=verified`, `reliability2>=0.95` and
  `compute_cap>=7.5` (excludes Volta, which the cu128 ACE-Step build isn't
  validated on), it ranks by **cost-per-download-Mbps** (`dph_total / inet_down`)
  and takes the best — the cheapest node that is also **fastest to pull** (cold
  start is the dominant burst cost), not the cheapest-but-slowest one.
- **Cold-start caveat**: a Vast node re-pulls the ~13 GB image (minutes) and
  lazy-loads the model, so a burst worker only pays off for sustained load; a
  short burst is usually drained by the local baseline before the node is warm.
  A pre-baked checkpoint volume or a kept-warm node mitigates this.

## Baseline-first tiered queues (dev worker is the entry point)

A single shared FIFO queue let a warm Vast node out-race the cold baseline (in a
20-job test the dev worker took 1 job while a warm Vast node did 18 at ~3 s each).
The queue is therefore split into two tiers so the always-on dev worker always
gets first claim:

- **`main`** (`oal:queue:ace-step-1.5`) — the baseline tier.
- **`burst`** (`oal:queue:ace-step-1.5:burst`) — the overflow tier.
- The **dispatcher** fills `main` up to `OAL_DISPATCH_BASELINE_RESERVE` (default 20)
  pending jobs, then routes new jobs to `burst`.
- Worker tier via `OAL_WORKER_TIER`: `baseline` (dev) does `BRPOP [main, burst]`
  (prefers `main`, helps `burst` when idle); `burst` (Vast) does `BRPOP [burst]`
  only, so Vast can never steal a `main` job.
- The autoscaler counts **both** tiers for depth and uses the same per-worker
  batch `OAL_SCALE_JOBS_PER_NODE` (default 20): `≤20` jobs run on the baseline
  alone (no Vast); the fleet only scales out once depth reaches 21. Keep the
  reserve and `JOBS_PER_NODE` equal.

## Worker cold/idle lifecycle (GPU freed between jobs)

The engine worker now **owns** the co-located ACE-Step server: it starts the
server lazily on the first job and **stops it after `OAL_ENGINE_IDLE_STOP_SECONDS`
(default 600s) of no jobs**, so an idle baseline worker holds neither the GPU nor
host RAM (the process is stopped, not merely offloaded to CPU). The first job
after an idle gap pays a full cold load (~30–80s from the checkpoint cache); jobs
within the idle window stay warm, so a burst does not thrash. Ephemeral Vast
nodes set `OAL_ENGINE_IDLE_STOP_SECONDS=0` (never stop) to stay hot for their
short life. Because `/health` is intentionally down while idle, the worker image's
`HEALTHCHECK` now watches a **worker heartbeat file** (`/tmp/oal_worker_heartbeat`,
touched every ~5s) instead of the ACE-Step endpoint. Set `OAL_ENGINE_AUTOSTART=0`
to revert to the old external-server mode.

Launch (on the hub / home server):

```
set -a; . .env.backend; set +a
OAL_REDIS_URL=redis://127.0.0.1:6379/0 VASTAI=.venv/bin/vastai \
  OAL_AUTOSCALE_STATE=/tmp/oal_autoscale_state.json \
  .venv/bin/python scripts/autoscale.py
```

Validated (2026-10-16): enqueuing 20 jobs drove depth to ~20 → the autoscaler
scaled out to the cap (baseline + 2 Vast nodes), all 20 jobs succeeded with valid
`mix_wav` artifacts, and the autoscaler tiered the fleet back down (one hot node,
then teardown) after the cooldown.

## Baseline fallback and standard OAL LLM (2026-10-19)

The autoscaler now treats the dev-host baseline worker as a health-checked
resource, not just a static count. A baseline is unavailable only when
`OAL_BASELINE_WORKER_ID` has a stale/missing heartbeat, is drained, is marked
unhealthy, or its engine start/OOM state prevents work; a busy GPU with active
job attempts is healthy. If the baseline stays unavailable for
`OAL_BASELINE_UNAVAILABLE_GRACE_SECONDS` (default 300s), the autoscaler creates
one fallback node with `OAL_BASELINE_FALLBACK_ROLE` (default
`engine_worker,audio_worker`) and `OAL_WORKER_TIER=baseline`, so it consumes the
main queue while the dev worker is down. When the baseline returns, the fallback
is destroyed after `OAL_BASELINE_RESTORE_GRACE_SECONDS` (default 300s).

Fallback offers are stricter than burst offers: North America only,
`OAL_BASELINE_FALLBACK_MAX_DPH` (default `$0.15/hr`),
`OAL_BASELINE_FALLBACK_MIN_VRAM` (default 24 GB), and
`OAL_BASELINE_FALLBACK_MIN_COMPUTE_CAP` (default 7.0, allowing V100/V100S when
generation smoke tests pass). The fallback also starts the standard OAL LLM:
Qwen3-4B Q4_K_M GGUF served by `llama.cpp` on container port 8082. The
autoscaler maps that port through Vast's public port binding and writes the
reachable endpoint to `site_settings.llm_base_url`; on restore it resets the
endpoint to `OAL_PRIMARY_LLM_BASE_URL`.

Validated (2026-10-19): stopping the baseline worker caused the autoscaler to
create Vast contract `56795630` (Tesla V100, Utah, `$0.148/hr`), register
`http://67.182.226.160:20680/v1` as the LLM endpoint, complete `/llm/title`,
`/llm/draft`, `/llm/lyrics`, and `/llm/style-prompt`, and complete generation job
`e2b1d3fc-7a55-4268-80ae-5f10e9939ceb`. Restarting the baseline worker restored
`http://10.203.0.2:8082/v1` and destroyed the fallback after the restore grace.

## House LoRA merge A/B nodes (2026-10-20)

House LoRA merge/A-B runs use standalone Vast nodes from
`stratastack/acestep-train:v5-house-ab`. These nodes are not OAL queue workers;
they pull adapters from the hub, build merged ACE-Step checkpoints, generate a
fixed A/B prompt set, and rsync results back to the hub.

The corrected merge procedure is documented in `docs/HOUSE_LORA_TRAINING.md`.
The important operational lesson is that node-to-hub checkpoint upload can be
much slower than hub-to-node download, so the agent now pushes audio and metadata
before merged checkpoints.

Validated (2026-10-20): one-adapter sanity contract `56826462` and corrected
full A/B contract `56827635` completed successfully. Corrected results were
rsynced to `/Cold-Archive/OpenAudioLab/house-lora-ab/2026-10-19-v2/`.
