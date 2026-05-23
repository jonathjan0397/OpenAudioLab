# Pipeline Documentation

## Default Pipeline Stages

1. `job_intake` - Receive and validate job request
2. `prompt_validation` - Validate prompt and parameters
3. `lyrics_generation_or_ingestion` - Generate AI lyrics or ingest provided lyrics
4. `lyrics_structure_validation` - Validate lyric structure (non-mutating for provided lyrics)
5. `lyrics_reasoning` - Analyze AI-generated lyrics for quality
6. `lyrics_revision` - Revise lyrics if reasoning score is below threshold
7. `lyrics_humanization` - Humanize AI-generated lyrics
8. `composition_planning` - Create composition plan (BPM, key, sections)
9. `audio_generation` - Generate audio from composition and lyrics
10. `daw_processing` - Trim, normalize, fade, crossfade
11. `effects_processing` - Apply effects chain
12. `mastering` - Master final audio
13. `preview_waveform_generation` - Generate waveform metadata
14. `zip_export` - Create final ZIP package
15. `storage_upload` - Upload artifacts to storage
16. `signed_download_url` - Generate signed download URL
17. `retention_cleanup` - Set expiration metadata

## Lyrics Mode Pipeline Variations

### AI Mode
All lyrics stages run: generation → structure validation → reasoning → revision → humanization

### Provided Mode
Only structure validation runs. All other lyrics stages are skipped. Lyrics are preserved exactly.

### Hybrid Mode
All lyrics stages run, but user-provided text may be transformed.

### Instrumental Mode
All lyrics stages are skipped.
