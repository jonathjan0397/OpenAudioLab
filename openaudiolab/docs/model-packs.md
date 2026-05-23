# Model Packs

## Overview

Model packs define which models are available for each worker type. The backend is model-agnostic.

## Packs

- **model-pack-lite**: CPU-safe test pack for pipeline validation
- **model-pack-community-gpu**: Community Edition GPU worker with verified models
- **model-pack-studio-cloud**: High-quality pack for cloud GPUs (24 GB VRAM+)
- **model-pack-commercial-safe**: Models verified for commercial use

## Model Registry Entry

Each model must include: model_id, display_name, engine, task, version, source_url, license, license_url, redistributable_status, commercial_safe_status, capabilities, min_vram_gb, recommended_vram_gb, default_container_policy, notes.

## License Statuses

- `verified`: License verified for redistribution and/or commercial use
- `needs_review`: License status unclear; requires review
- `not_allowed`: Cannot be redistributed or used commercially
- `user_supplied_only`: User must provide the model themselves
