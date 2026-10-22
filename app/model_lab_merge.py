"""Model Lab M5: LoRA merge recipes and versioned model bundles.

Merges run through the configured merge command on a GPU worker context; the
API only validates inputs and records durable candidates. A merge is never a
silent success: without a configured command it fails closed.
"""

from __future__ import annotations

import json
import subprocess

from sqlalchemy import func, select

from .models import Lora, MlMergeRecipe, MlModelBundle, new_uuid, utcnow

MERGE_METHODS = ("slerp", "dare")
BUNDLE_STATES = ("building", "candidate", "released", "retired", "failed", "archived")
SATISFACTORY = ("win", "pass")


class MergeError(ValueError):
    pass


def create_recipe(session, name: str, base_model: str, adapter_ids: list[str],
                  method: str = "slerp", params: dict | None = None) -> MlMergeRecipe:
    if method not in MERGE_METHODS:
        raise MergeError(f"unknown merge method: {method}")
    if adapter_ids is None:
        raise MergeError("adapter_ids must be a list (zero adapters = anchor-only control)")
    for aid in adapter_ids:
        adapter = session.get(Lora, aid)
        if adapter is None:
            raise MergeError(f"unknown adapter: {aid}")
        if adapter.state not in ("active", "ready"):
            raise MergeError(f"adapter {aid} is not ready (state={adapter.state})")
    strengths = (params or {}).get("strengths")
    if strengths is not None:
        if not isinstance(strengths, list) or len(strengths) != len(adapter_ids):
            raise MergeError("params.strengths must be a list with one value per adapter")
        for value in strengths:
            if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
                raise MergeError("merge strengths must be within 0..1")
    recipe = MlMergeRecipe(id=new_uuid(), name=name, base_model=base_model,
                           adapter_ids_json=list(adapter_ids), method=method,
                           params_json=params or {})
    session.add(recipe)
    session.commit()
    return recipe


def next_bundle_version(session, name: str) -> str:
    count = session.execute(
        select(func.count()).select_from(MlModelBundle).where(MlModelBundle.name == name)
    ).scalar() or 0
    return f"v{count + 1}"


def start_merge_build(session, recipe: MlMergeRecipe, settings) -> MlModelBundle:
    """Create an immutable candidate placeholder in `building` state."""
    command = (getattr(settings, "model_lab_merge_command", "") or "").strip()
    if not command:
        raise MergeError("MERGE_UNAVAILABLE: no merge command configured")
    bundle = MlModelBundle(id=new_uuid(), name=recipe.name,
                           version=next_bundle_version(session, recipe.name),
                           kind="merged", base_model=recipe.base_model,
                           state="building",
                           bundle_json={"recipe_id": recipe.id, "method": recipe.method,
                                        "params": recipe.params_json,
                                        "adapter_ids": list(recipe.adapter_ids_json)})
    session.add(bundle)
    session.commit()
    return bundle


def finish_merge_build(session, bundle: MlModelBundle | None, *, ok: bool,
                       result: dict | None = None, error: str | None = None) -> None:
    if bundle is None:
        return
    if ok:
        result = result or {}
        bundle.revision = result.get("revision")
        bundle.artifact_key = result.get("artifact_key")
        bundle.sha256 = result.get("sha256")
        bundle.state = "candidate"
        bundle.bundle_json = {**(bundle.bundle_json or {}), "trainer_result": result}
    else:
        bundle.state = "failed"
        bundle.bundle_json = {**(bundle.bundle_json or {}), "error": (error or "")[-280:]}
    session.commit()


def run_merge(session, recipe: MlMergeRecipe, settings) -> MlModelBundle:
    """Synchronous merge (tests / controller-side); worker path uses the job."""
    import os

    command = (getattr(settings, "model_lab_merge_command", "") or "").strip()
    if not command:
        raise MergeError("MERGE_UNAVAILABLE: no merge command configured")
    env = dict(os.environ)
    env.update({"OAL_ML_RECIPE_ID": recipe.id, "OAL_ML_BASE_MODEL": recipe.base_model,
                "OAL_ML_ADAPTERS": ",".join(recipe.adapter_ids_json),
                "OAL_ML_METHOD": recipe.method})
    proc = subprocess.run(command, shell=True, capture_output=True, text=True,
                          timeout=3600, env=env, check=False)
    if proc.returncode != 0:
        raise MergeError(f"merge failed: {(proc.stderr or '')[-200:]}")
    result: dict = {}
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                result = json.loads(line)
            except json.JSONDecodeError:
                pass
            break
    if not result.get("sha256"):
        raise MergeError("MERGE_NO_ARTIFACT: merge reported success without an artifact")
    bundle = start_merge_build(session, recipe, settings)
    finish_merge_build(session, bundle, ok=True, result=result)
    return bundle


def transition_bundle(session, bundle: MlModelBundle, action: str) -> MlModelBundle:
    """Explicit lifecycle: candidate -> released -> retired (no auto-promotion)."""
    if action == "release":
        if bundle.state != "candidate":
            raise MergeError(f"only candidates can be released (state={bundle.state})")
        bundle.state = "released"
    elif action == "retire":
        if bundle.state != "released":
            raise MergeError(f"only released bundles can be retired (state={bundle.state})")
        bundle.state = "retired"
    elif action == "archive":
        if bundle.state not in ("retired", "candidate", "failed"):
            raise MergeError(f"cannot archive a {bundle.state} bundle")
        bundle.state = "archived"
    else:
        raise MergeError(f"unknown bundle action: {action}")
    session.commit()
    return bundle


def bundle_view(bundle: MlModelBundle) -> dict:
    return {"id": bundle.id, "name": bundle.name, "version": bundle.version,
            "kind": bundle.kind, "base_model": bundle.base_model, "state": bundle.state,
            "sha256": bundle.sha256, "artifact_key": bundle.artifact_key}
