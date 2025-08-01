# Copyright 2019-2020 SURF, GÉANT.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import secrets
import string
from pathlib import Path
from typing import Literal

from pydantic import Field, NonNegativeInt, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings

from oauth2_lib.settings import oauth2lib_settings
from orchestrator.services.settings_env_variables import expose_settings
from orchestrator.utils.expose_settings import SecretStr as OrchSecretStr
from pydantic_forms.types import strEnum


class ExecutorType(strEnum):
    WORKER = "celery"
    THREADPOOL = "threadpool"


class AppSettings(BaseSettings):
    TESTING: bool = True
    SESSION_SECRET: OrchSecretStr = "".join(secrets.choice(string.ascii_letters) for i in range(16))  # type: ignore
    CORS_ORIGINS: str = "*"
    CORS_ALLOW_METHODS: list[str] = ["GET", "PUT", "PATCH", "POST", "DELETE", "OPTIONS", "HEAD"]
    CORS_ALLOW_HEADERS: list[str] = ["If-None-Match", "Authorization", "If-Match", "Content-Type"]
    CORS_EXPOSE_HEADERS: list[str] = [
        "Cache-Control",
        "Content-Language",
        "Content-Length",
        "Content-Type",
        "Expires",
        "Last-Modified",
        "Pragma",
        "Content-Range",
        "ETag",
    ]
    ENVIRONMENT: str = "local"
    EXECUTOR: str = ExecutorType.THREADPOOL
    WORKFLOWS_SWAGGER_HOST: str = "localhost"
    WORKFLOWS_GUI_URI: str = "http://localhost:3000"
    DATABASE_URI: PostgresDsn = "postgresql://nwa:nwa@localhost/orchestrator-core"  # type: ignore
    MAX_WORKERS: int = 5
    MAIL_SERVER: str = "localhost"
    MAIL_PORT: int = 25
    MAIL_STARTTLS: bool = False
    CACHE_URI: RedisDsn = "redis://localhost:6379/0"  # type: ignore
    CACHE_HMAC_SECRET: OrchSecretStr | None = None  # HMAC signing key, used when pickling results in the cache
    REDIS_RETRY_COUNT: NonNegativeInt = Field(
        2, description="Number of retries for redis connection errors/timeouts, 0 to disable"
    )  # More info: https://redis-py.readthedocs.io/en/stable/retry.html
    ENABLE_DISTLOCK_MANAGER: bool = True
    DISTLOCK_BACKEND: str = "memory"
    CC_NOC: int = 0
    SERVICE_NAME: str = "orchestrator-core"
    LOGGING_HOST: str = "localhost"
    LOG_LEVEL: str = "DEBUG"
    SLACK_ENGINE_SETTINGS_HOOK_ENABLED: bool = False
    SLACK_ENGINE_SETTINGS_HOOK_URL: str = ""
    TRACING_ENABLED: bool = False
    TRACE_HOST: str = "http://localhost:4317"
    TRANSLATIONS_DIR: Path | None = None
    WEBSOCKET_BROADCASTER_URL: OrchSecretStr = "memory://"  # type: ignore
    ENABLE_WEBSOCKETS: bool = True
    DISABLE_INSYNC_CHECK: bool = False
    DEFAULT_PRODUCT_WORKFLOWS: list[str] = ["modify_note"]
    SKIP_MODEL_FOR_MIGRATION_DB_DIFF: list[str] = []
    SERVE_GRAPHQL_UI: bool = True
    FEDERATION_ENABLED: bool = False
    DEFAULT_CUSTOMER_FULLNAME: str = "Default::Orchestrator-Core Customer"
    DEFAULT_CUSTOMER_SHORTCODE: str = "default-cust"
    DEFAULT_CUSTOMER_IDENTIFIER: str = "59289a57-70fb-4ff5-9c93-10fe67b12434"
    TASK_LOG_RETENTION_DAYS: int = 3
    ENABLE_GRAPHQL_DEPRECATION_CHECKER: bool = True
    ENABLE_GRAPHQL_PROFILING_EXTENSION: bool = False
    ENABLE_GRAPHQL_STATS_EXTENSION: bool = False
    ENABLE_PROMETHEUS_METRICS_ENDPOINT: bool = False
    VALIDATE_OUT_OF_SYNC_SUBSCRIPTIONS: bool = False
    FILTER_BY_MODE: Literal["partial", "exact"] = "exact"
    EXPOSE_SETTINGS: bool = False
    EXPOSE_OAUTH_SETTINGS: bool = False


app_settings = AppSettings()

# Set oauth2lib_settings variables to the same (default) value of settings
oauth2lib_settings.SERVICE_NAME = app_settings.SERVICE_NAME
oauth2lib_settings.ENVIRONMENT = app_settings.ENVIRONMENT

if app_settings.EXPOSE_SETTINGS:
    expose_settings("app_settings", app_settings)  # type: ignore
if app_settings.EXPOSE_OAUTH_SETTINGS:
    expose_settings("oauth2lib_settings", oauth2lib_settings)  # type: ignore
