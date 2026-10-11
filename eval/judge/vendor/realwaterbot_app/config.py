"""
Pydantic settings which includes the env varibales
We use config.py to keep application settings in one place instead of scattering them across the codebase.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from uuid import uuid4

class Settings(BaseSettings):
    # Required — app won't start without these
    openai_api_key: str
    database_url: str
    # Optional with defaults
    session_secret: str = Field(default_factory=lambda: str(uuid4()))
    bot_name: str = "RealWaterBot"
    rate_limit_per_hour: int = 50
    rag_top_k: int = 5
    rag_similarity_threshold: float = 0.7
    transcript_storage_path: str | None = None
    cookie_domain: str | None = None
    sources_verifier_model: str = "gpt-4o-mini"
    default_locale: str = "en"

    class Config:
        env_file = ".env"
        # THE ONE DELIBERATE DEVIATION FROM UPSTREAM, vendored 2026-09-09 (see this
        # directory's README). Default pydantic-settings behaviour is extra="forbid": any
        # environment variable present that isn't a declared field raises. That is fine for
        # RealWaterBot's own deployment, which owns its .env exclusively. It is not fine here -
        # eval/judge/cli.py:main() already calls load_dotenv() on THIS repo's shared .env for
        # every subcommand, which populates os.environ with AWS_*, HF_TOKEN, PROD_URL,
        # REALWATER_DATABASE_URL and more before this class is ever constructed. None of that
        # changes what openai_api_key or database_url resolve to - it only stops construction
        # from raising on keys this model was never written to know about.
        extra = "ignore"

settings = Settings()