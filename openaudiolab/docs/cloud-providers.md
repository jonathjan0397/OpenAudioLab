# Cloud Providers

## Supported Providers

- **Vast.AI**: GPU marketplace for renting instances
- **RunPod**: Serverless GPU computing platform

## Provider Abstraction

```python
class CloudProvider:
    def list_available_gpus(self): ...
    def provision_worker(self, requirements): ...
    def terminate_worker(self, worker_id): ...
    def get_worker_status(self, worker_id): ...
```

## Provisioning Requirements

```json
{
  "min_vram_gb": 24,
  "preferred_gpu_classes": ["RTX 4090", "A10G", "A40", "A100", "L40S"],
  "model_pack": "model-pack-studio-cloud",
  "max_hourly_price": "configured",
  "idle_shutdown_minutes": 10
}
```

## Routing

Cloud workers are used when:
- `dispatch_preference=cloud_gpu`
- `dispatch_preference=auto` and no compatible local worker exists
- Job requires studio model pack unavailable locally
