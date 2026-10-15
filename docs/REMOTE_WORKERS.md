# Remote worker deployments (ephemeral GPU nodes over WireGuard)

Status: mechanism implemented and validated on this host; a real Vast.ai node
was provisioned and confirmed to run the pushed image (see findings below).
Remaining capstone: go-live over the WireGuard tunnel. Branch `impl/milestone-1`.
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

## Code bundle (container-initiated over the tunnel)

`GET /internal/v1/worker/bundle` returns a `tar.gz` of `app/` plus a `REVISION`
file, with an `X-OAL-Revision` header. After WireGuard connects, the container
fetches it from the backend and unpacks it, so the backend is the source of
truth for the worker code revision and code iteration never rebuilds the heavy
image.

## Storage (durable across hosts)

S3-compatible store on the hub (MinIO in production; `moto_server` for local
validation). Workers push every artifact there; the API proxies ranged reads so
the bucket stays private. Trained LoRA adapters are uploaded to the bucket and
recorded as an object prefix + file list, so a profile trained on one node can
be loaded (downloaded to a node-local cache) on any other node.

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
