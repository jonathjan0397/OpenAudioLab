# Output and audio-export requirements

Confirmed deliverables: full-mix WAV, full-mix MP3, and individual stems in WAV. A full mix can be a vocal song or instrumental. Offer a ZIP containing the complete available WAV stem set and manifest. Users may request one or multiple output types from the same source version.

## Output contract

| Type | Required behavior |
| --- | --- |
| `mix_wav` | Preserve original native WAV; offer separately labeled export conversions |
| `mix_mp3` | Encode the chosen lossless mix version; selectable bitrate including 320 kbps |
| `stems_wav` | Individual aligned WAV files from native generation or an explicit separation operation |
| `stems_zip` | ZIP of available WAV stems plus manifest; no MP3 stems required |

Full-mix WAV/MP3 come from the same selected mix version. Never derive a WAV master from an MP3 when a lossless source exists. For an uploaded lossy source, record that lineage and avoid implying lossless recovery. Do not claim upsampling adds source detail.

Expose supported sample rates and PCM encodings/bit depths through capabilities. Native preservation is the default; offer 44.1/48 kHz and PCM16/PCM24 exports where conversion is implemented. A float intermediate is not an ordinary PCM24 download. Use dithering only when appropriate for a bit-depth reduction, documenting the recipe. Changing sample rate or bit depth produces a derived export and leaves the original intact.

## Stem integrity

Stem categories reflect actual engine output: vocals, drums, bass and other is a candidate set, not a universal promise. Finer categories appear only if the model supports them. Include `stem_source: native|separated`, separation model revision when applicable, category names, residual availability and quality warnings. Do not promise perfectly isolated instruments or an exact reconstruction from estimated stems.

Every stem in a package has the same start origin, sample rate, channel layout and exact sample count; retain leading/trailing silence needed for alignment. Use consistent bit depth. Do not normalize stems independently or apply nonlinear full-mix mastering to each stem and imply that they reproduce the mastered mix. Label stems as pre-master/processed as appropriate. Provide a separately labeled gain-adjusted preview if necessary.

## Export job and validation

An export request identifies an owned immutable source version and `outputs`, plus supported format settings. Example:

```json
{
  "source_version_id": "<owned-version-uuid>",
  "outputs": ["mix_wav", "mix_mp3", "stems_wav", "stems_zip"],
  "wav": {"sample_rate": "native", "encoding": "pcm16"},
  "mp3": {"bitrate_kbps": 320},
  "stem_set": "available"
}
```

This is a proposed contract, not an upstream engine API. Reject unsupported export settings before queuing. If stems require separation, create an explicit dependency job using an enabled licensed separator, record its usage separately and report its status. Do not silently drop requested outputs. All required outputs must be published/validated before the job succeeds; on failure report per-output outcomes and preserve usable assets as partial results without marking overall success.

Validate decoded duration, actual codec/encoding, channels, sample rate, samples, finite amplitude where applicable, byte size and checksum. ZIP creation uses safe server-generated names and includes no arbitrary filesystem paths. MP3 encoder delay/padding is recorded/handled where possible; use WAV stems for sample-accurate DAW alignment.

Manifest fields: job/attempt/source-version IDs, model/profile revisions, source/derived designation, format/codec, sample rate, encoding/bit depth, channels, sample count/duration, MP3 bitrate, stem category/source, processing recipe revision, bytes, checksum, creation/expiry and required license notices. Export metadata tags may include user-supplied title/artist/project, sanitized for file metadata and filenames.

Private download APIs support full mixes, individual stems and ZIP. WAV/MP3 playback uses authenticated or short-lived signed access with range requests. The frontend alone renders playback, download controls and export settings. Containers use reviewed FFmpeg builds: commercial permission and distribution/linking obligations are separate from encoder availability.
