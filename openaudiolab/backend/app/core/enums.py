from enum import Enum


class JobStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    WAITING_FOR_WORKER = "waiting_for_worker"
    PROVISIONING_WORKER = "provisioning_worker"
    ASSIGNED = "assigned"
    RUNNING = "running"
    STAGE_COMPLETED = "stage_completed"
    UPLOADING_RESULTS = "uploading_results"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class LyricsMode(str, Enum):
    AI = "ai"
    PROVIDED = "provided"
    HYBRID = "hybrid"
    INSTRUMENTAL = "instrumental"


class DispatchPreference(str, Enum):
    AUTO = "auto"
    LOCAL = "local"
    REMOTE_WORKER = "remote_worker"
    CLOUD_GPU = "cloud_gpu"
    CPU_TEST = "cpu_test"


class Quality(str, Enum):
    DRAFT = "draft"
    STANDARD = "standard"
    HIGH = "high"
    STUDIO = "studio"


class LyricReasoningMode(str, Enum):
    OFF = "off"
    FAST = "fast"
    BALANCED = "balanced"
    STRICT = "strict"
    STUDIO = "studio"


class WorkerStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    DRAINING = "draining"
    OFFLINE = "offline"
    REGISTERING = "registering"


class WorkerMode(str, Enum):
    LITE = "lite"
    GPU_BASE = "gpu_base"
    COMMUNITY_FULL = "community_full"
    STUDIO_FULL = "studio_full"


class StorageProviderType(str, Enum):
    LOCAL = "local"
    MINIO = "minio"
    S3_COMPATIBLE = "s3_compatible"


class AssetType(str, Enum):
    INPUT = "input"
    LYRICS = "lyrics"
    AUDIO_DRAFT = "audio_draft"
    AUDIO_MASTER = "audio_master"
    AUDIO_MP3 = "audio_mp3"
    EXPORT_ZIP = "export_zip"
    LOG = "log"
    METADATA = "metadata"
    WAVEFORM = "waveform"
    COMPOSITION_PLAN = "composition_plan"
    EFFECTS_CHAIN = "effects_chain"
    LOUDNESS_REPORT = "loudness_report"


class RetentionClass(str, Enum):
    TEMP_WORKER_FILE = "temp_worker_file"
    FAILED_INTERMEDIATE = "failed_intermediate"
    COMPLETED_JOB_ASSETS = "completed_job_assets"
    DEBUG_LOGS = "debug_logs"
    COMMERCIAL_EXTENDED = "commercial_extended"


class ModelLicenseStatus(str, Enum):
    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"
    NOT_ALLOWED = "not_allowed"
    USER_SUPPLIED_ONLY = "user_supplied_only"


class PipelineStage(str, Enum):
    JOB_INTAKE = "job_intake"
    PROMPT_VALIDATION = "prompt_validation"
    LYRICS_GENERATION_OR_INGESTION = "lyrics_generation_or_ingestion"
    LYRIC_BRAINSTORM = "lyric_brainstorm"
    LYRICS_STRUCTURE_VALIDATION = "lyrics_structure_validation"
    LYRICS_REASONING = "lyrics_reasoning"
    LYRICS_REVISION = "lyrics_revision"
    LYRICS_HUMANIZATION = "lyrics_humanization"
    GENRE_STYLE_CONTROL = "genre_style_control"
    COMPOSITION_PLANNING = "composition_planning"
    PERSONA_SELECTION = "persona_selection"
    AUDIO_GENERATION = "audio_generation"
    DAW_PROCESSING = "daw_processing"
    EFFECTS_PROCESSING = "effects_processing"
    MASTERING = "mastering"
    STEM_SEPARATION = "stem_separation"
    PREVIEW_WAVEFORM_GENERATION = "preview_waveform_generation"
    ZIP_EXPORT = "zip_export"
    STORAGE_UPLOAD = "storage_upload"
    SIGNED_DOWNLOAD_URL = "signed_download_url"
    RETENTION_CLEANUP = "retention_cleanup"


DEFAULT_PIPELINE = [
    PipelineStage.JOB_INTAKE,
    PipelineStage.PROMPT_VALIDATION,
    PipelineStage.LYRICS_GENERATION_OR_INGESTION,
    PipelineStage.LYRIC_BRAINSTORM,
    PipelineStage.LYRICS_STRUCTURE_VALIDATION,
    PipelineStage.LYRICS_REASONING,
    PipelineStage.LYRICS_REVISION,
    PipelineStage.LYRICS_HUMANIZATION,
    PipelineStage.GENRE_STYLE_CONTROL,
    PipelineStage.COMPOSITION_PLANNING,
    PipelineStage.PERSONA_SELECTION,
    PipelineStage.AUDIO_GENERATION,
    PipelineStage.DAW_PROCESSING,
    PipelineStage.EFFECTS_PROCESSING,
    PipelineStage.MASTERING,
    PipelineStage.STEM_SEPARATION,
    PipelineStage.PREVIEW_WAVEFORM_GENERATION,
    PipelineStage.ZIP_EXPORT,
    PipelineStage.STORAGE_UPLOAD,
    PipelineStage.SIGNED_DOWNLOAD_URL,
    PipelineStage.RETENTION_CLEANUP,
]
