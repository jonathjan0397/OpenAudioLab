from app.core.enums import DEFAULT_PIPELINE, LyricsMode


def get_pipeline_for_job(lyrics_mode: str, instrumental: bool) -> list[str]:
    pipeline = [s.value for s in DEFAULT_PIPELINE]

    if instrumental or lyrics_mode == LyricsMode.INSTRUMENTAL.value:
        skip_stages = {
            "lyrics_generation_or_ingestion",
            "lyric_brainstorm",
            "lyrics_structure_validation",
            "lyrics_reasoning",
            "lyrics_revision",
            "lyrics_humanization",
        }
        pipeline = [s for s in pipeline if s not in skip_stages]
    elif lyrics_mode == LyricsMode.PROVIDED.value:
        skip_stages = {
            "lyrics_generation_or_ingestion",
            "lyrics_reasoning",
            "lyrics_revision",
            "lyrics_humanization",
        }
        pipeline = [s for s in pipeline if s not in skip_stages]
    elif lyrics_mode == LyricsMode.HYBRID.value:
        skip_stages = {
            "lyrics_generation_or_ingestion",
        }
        pipeline = [s for s in pipeline if s not in skip_stages]
    elif lyrics_mode == LyricsMode.AI.value:
        pass

    return pipeline


def get_skipped_stages(lyrics_mode: str, instrumental: bool) -> list[str]:
    all_stages = [s.value for s in DEFAULT_PIPELINE]
    active_stages = get_pipeline_for_job(lyrics_mode, instrumental)
    return [s for s in all_stages if s not in active_stages]
