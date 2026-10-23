"""Batch 6.5: local review page + reference clip helpers."""

from __future__ import annotations

from pathlib import Path


def test_build_review_page_lists_pairs_and_references(tmp_path: Path) -> None:
    from app.review import build_review_page

    dest = tmp_path / "rv"
    dest.mkdir()
    (dest / "baseline-summer.mp3").write_bytes(b"aa")
    (dest / "candidate-summer.mp3").write_bytes(b"bb")
    (dest / "reference-1-alabama-x.mp3").write_bytes(b"cc")
    (dest / "acceptance-sample.mp3").write_bytes(b"dd")
    page = build_review_page(
        dest,
        bundle={"name": "voice-v1", "version": "v1", "kind": "adapter",
                "base_model": "acestep-v15-turbo", "sha256": "abcdef012345",
                "seed": 42, "duration_seconds": 30},
        samples=[{"mode": "baseline", "prompt": "summer", "caption": "warm sun",
                  "file": "baseline-summer.mp3", "bytes": 2, "sha256": "x"},
                 {"mode": "candidate", "prompt": "summer", "caption": "warm sun",
                  "file": "candidate-summer.mp3", "bytes": 2, "sha256": "y"}],
        references=[{"file": "reference-1-alabama-x.mp3", "label": "Alabama - X"}])
    html = Path(page).read_text()
    assert "voice-v1" in html and "baseline-summer.mp3" in html
    assert "candidate-summer.mp3" in html and "Alabama - X" in html
    assert "acceptance-sample.mp3" in html and "acestep-v15-turbo" in html


def test_write_reference_clips_skips_missing_and_bad_dataset(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from app.models import MlDataset, new_uuid
    from app.review import write_reference_clips

    class _S:
        def __init__(self, ds): self._d = ds
        def get(self, _m, _i): return self._d

    bundle = SimpleNamespace(bundle_json={"dataset_id": "d1"})
    assert write_reference_clips(_S(None), bundle, tmp_path) == []
    ds = MlDataset(id=new_uuid(), name="x", frozen_sha256="f",
                   manifest_json={"entries": [{"path": str(tmp_path / "gone.mp3"),
                                               "lyrics": "a", "caption": "Gone"}]})
    bundle = SimpleNamespace(bundle_json={"dataset_id": ds.id})
    assert write_reference_clips(_S(ds), bundle, tmp_path) == []


def test_reference_clip_trims_real_audio(tmp_path: Path) -> None:
    import subprocess

    from types import SimpleNamespace

    from app.review import write_reference_clips

    src = tmp_path / "Song One.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=120", "-c:a", "libmp3lame",
                    str(src)], check=True)
    ds = SimpleNamespace(manifest_json={"entries": [
        {"path": str(src), "lyrics": "yes", "caption": "Alabama - Song One"}]})

    class _S:
        def get(self, _m, _i): return ds

    out = tmp_path / "rv"
    out.mkdir()
    refs = write_reference_clips(_S(), SimpleNamespace(bundle_json={"dataset_id": "d"}), out)
    assert len(refs) == 1 and refs[0]["file"].startswith("reference-1-alabama")
    assert (out / refs[0]["file"]).stat().st_size < src.stat().st_size


def test_review_bundle_dir_empty_setting_is_off(tmp_path: Path) -> None:
    from app.review import review_bundle_dir

    assert review_bundle_dir("", "b1") is None
    got = review_bundle_dir(tmp_path / "review", "b1")
    assert got is not None and got.is_dir()
