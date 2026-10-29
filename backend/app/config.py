from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_prefix="")

    data_dir: Path = Field(default=Path("./data"), alias="DEVPILOT_DATA_DIR")
    cors_origins: str = Field(default="http://localhost:3000", alias="DEVPILOT_CORS_ORIGINS")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="", alias="ANTHROPIC_MODEL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="", alias="OPENAI_MODEL")
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    # Tests only: allow cloning file:// / local bare repos as "GIT_URL" sources.
    allow_local_git_urls: bool = Field(default=False, alias="DEVPILOT_ALLOW_LOCAL_GIT_URLS")
    max_concurrent_missions: int = 3

    @field_validator("data_dir")
    @classmethod
    def _absolute(cls, v: Path) -> Path:
        # Always absolute: tools hand paths to subprocesses that run with a different cwd (the workspace).
        return Path(v).expanduser().resolve()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "devpilot.db"

    @property
    def workspaces_dir(self) -> Path:
        return self.data_dir / "workspaces"

    @property
    def repos_dir(self) -> Path:
        return self.data_dir / "repos"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.workspaces_dir, self.repos_dir, self.artifacts_dir, self.runs_dir):
            p.mkdir(parents=True, exist_ok=True)
