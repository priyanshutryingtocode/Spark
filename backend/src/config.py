"""Central configuration: model names, defaults, and environment loading.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

DATABASE_URL = os.environ.get("DATABASE_URL")
DATASET_MODE = os.environ.get("DATASET_MODE", "synthetic").strip().lower()
if DATASET_MODE not in {"synthetic", "real"}:
    raise RuntimeError("DATASET_MODE must be synthetic or real")
APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
if APP_ENV not in {"development", "test", "demo", "production"}:
    raise RuntimeError("APP_ENV must be development, test, demo, or production")
AUTH_REQUIRED = os.environ.get("AUTH_REQUIRED", "true" if APP_ENV in {"demo", "production"} else "false").lower() == "true"
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET")
SUPABASE_JWKS_URL = os.environ.get("SUPABASE_JWKS_URL") or (
    f"{SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json" if SUPABASE_URL else None
)
SUPABASE_ISSUER = os.environ.get("SUPABASE_ISSUER") or (f"{SUPABASE_URL.rstrip('/')}/auth/v1" if SUPABASE_URL else None)
SUPABASE_JWT_AUDIENCE = os.environ.get("SUPABASE_JWT_AUDIENCE", "authenticated")
RUN_SCHEMA_ON_STARTUP = os.environ.get("RUN_SCHEMA_ON_STARTUP", "false" if APP_ENV == "production" else "true").lower() == "true"

GEN_MODEL = "gemini-2.5-flash-lite"

RANKING_MAX_OUTPUT_TOKENS = int(os.environ.get("RANKING_MAX_OUTPUT_TOKENS", "2048"))
if RANKING_MAX_OUTPUT_TOKENS <= 0:
    raise RuntimeError("RANKING_MAX_OUTPUT_TOKENS must be a positive integer")

EMBED_MODEL = os.environ.get("EMBED_MODEL", "gemini-embedding-001")

EMBED_DIMENSIONS = int(os.environ.get("EMBED_DIMENSIONS", "768"))
if EMBED_DIMENSIONS <= 0:
    raise RuntimeError("EMBED_DIMENSIONS must be a positive integer")

EMBED_TASK_DOCUMENT = os.environ.get("EMBED_TASK_DOCUMENT", "RETRIEVAL_DOCUMENT")
EMBED_TASK_QUERY = os.environ.get("EMBED_TASK_QUERY", "RETRIEVAL_QUERY")

EMBED_REQUEST_INTERVAL_SECONDS = float(os.environ.get("EMBED_REQUEST_INTERVAL_SECONDS", "1.0"))
if EMBED_REQUEST_INTERVAL_SECONDS < 0:
    raise RuntimeError("EMBED_REQUEST_INTERVAL_SECONDS cannot be negative")

DEFAULT_INFLUENCER_COUNT = 60
DEFAULT_TOP_K_RETRIEVAL = 10
DEFAULT_TOP_N_RANKED = 5

# How much the structured match score counts against the embedding similarity.
# The similarity scale is narrow -- a corpus sits in roughly a 0.78-0.88 band --
# so a small number is a large one. Chosen from the evaluation curve rather
# than guessed; see the `rerank_weight` block in the evaluation report.
RERANK_WEIGHT = float(os.environ.get("RERANK_WEIGHT", "0.25"))

# A free-text brief. The floor is enforced on write only, so stored runs whose
# brief was a short fixed label still validate when they are read back.
MIN_GOAL_LENGTH = int(os.environ.get("MIN_GOAL_LENGTH", "8"))
MAX_GOAL_LENGTH = int(os.environ.get("MAX_GOAL_LENGTH", "600"))
AUDIENCE_MAX_LENGTH = 300
VIBE_MAX_LENGTH = 500
if MIN_GOAL_LENGTH < 1 or MAX_GOAL_LENGTH < MIN_GOAL_LENGTH:
    raise RuntimeError("MIN_GOAL_LENGTH must be positive and no greater than MAX_GOAL_LENGTH")

MAX_INFLUENCER_COUNT = 5000
MAX_TOP_K = 50
MAX_MEMORY_JOBS = int(os.environ.get("MAX_MEMORY_JOBS", "2"))
MAX_MATCH_JOBS_PER_IP_PER_HOUR = int(os.environ.get("MAX_MATCH_JOBS_PER_IP_PER_HOUR", "20"))
if MAX_MEMORY_JOBS <= 0 or MAX_MATCH_JOBS_PER_IP_PER_HOUR <= 0:
    raise RuntimeError("Job limits must be positive integers")

GEMINI_TIMEOUT_MS = 120_000
GEMINI_RETRY_ATTEMPTS = 3
