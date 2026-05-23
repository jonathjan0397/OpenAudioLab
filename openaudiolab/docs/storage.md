# Storage Documentation

## Storage Interface

```python
class StorageProvider:
    def upload_file(self, local_path, remote_key, metadata): ...
    def download_file(self, remote_key, local_path): ...
    def generate_signed_download_url(self, remote_key, expires_in): ...
    def delete_file(self, remote_key): ...
    def file_exists(self, remote_key): ...
```

## Adapters

- **Local**: Filesystem storage at `LOCAL_STORAGE_PATH`
- **MinIO**: S3-compatible object storage
- **S3 Compatible**: Any S3-compatible provider

## Object Layout

```
/jobs/{job_id}/input/request.json
/jobs/{job_id}/lyrics/lyrics_final.txt
/jobs/{job_id}/audio/draft.wav
/jobs/{job_id}/audio/final_master.wav
/jobs/{job_id}/exports/final.zip
/jobs/{job_id}/logs/pipeline.log
/jobs/{job_id}/metadata/job_manifest.json
```

## Retention

- Default: 7 days
- Classes: temp_worker_file (immediate), failed_intermediate (24h), completed_job_assets (7d), debug_logs (7d)
