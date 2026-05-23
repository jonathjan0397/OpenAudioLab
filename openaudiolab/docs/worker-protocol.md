# Worker Protocol

## Registration

Workers register with the backend using a registration token:

```
POST /api/workers/register
{
  "worker_name": "local-test-worker",
  "worker_mode": "lite",
  "registration_token": "token",
  "gpu": { "available": false, "name": null, "vram_gb": 0, "cuda_available": false },
  "capabilities": { "lyrics": true, "cpu_test_generation": true, ... },
  "model_packs": ["model-pack-lite"],
  "container_version": "0.1.0"
}
```

Response:
```
{
  "accepted": true,
  "worker_id": "abc123",
  "worker_api_token": "worker_xxx"
}
```

## Heartbeat

Workers send heartbeats every 10-30 seconds:

```
POST /api/workers/heartbeat
Headers: X-Worker-Token: worker_api_token
{
  "worker_id": "abc123",
  "status": "idle",
  "active_job_id": null,
  "container_version": "0.1.0",
  "draining": false
}
```

## Job Polling

Workers pull jobs:

```
POST /api/workers/request-job?worker_id=abc123
Headers: X-Worker-Token: worker_api_token
```

## Stage Updates

Workers update stage status:

```
POST /api/workers/jobs/{job_id}/stage-update
Headers: X-Worker-Token: worker_api_token
{
  "stage_name": "audio_generation",
  "status": "completed",
  "metadata": { "duration": 15 }
}
```
