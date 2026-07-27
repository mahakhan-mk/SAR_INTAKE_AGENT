from __future__ import annotations

from pathlib import Path

from app import config

CONFIG_ENV_KEYS = (
    "DATABASE_URL",
    "DATABASE_SCHEMA",
    "AZURE_BLOB_CONNECTION_STRING",
    "AZURE_BLOB_CONTAINER_NAME",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_TIMEOUT_SECONDS",
    "AZURE_OPENAI_API_VERSION",
)


def clear_config_env(monkeypatch) -> None:
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def write_env_file(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()),
        encoding="utf-8",
    )


def test_project_root_env_file_is_loaded_independent_of_cwd(monkeypatch, tmp_path):
    clear_config_env(monkeypatch)
    project_root = tmp_path / "project-root"
    project_root.mkdir()
    env_file = project_root / ".env"
    write_env_file(
        env_file,
        {
            "DATABASE_URL": "postgresql+asyncpg://root-env.example/sardb?ssl=require",
            "DATABASE_SCHEMA": "root_schema",
        },
    )
    monkeypatch.setattr(config, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    monkeypatch.chdir(tmp_path)

    settings = config.get_settings()

    assert settings.database_url == "postgresql+asyncpg://root-env.example/sardb?ssl=require"
    assert settings.database_schema == "root_schema"


def test_database_url_is_loaded_from_env_file(monkeypatch, tmp_path):
    clear_config_env(monkeypatch)
    env_file = tmp_path / ".env"
    write_env_file(env_file, {"DATABASE_URL": "postgresql+asyncpg://env-file.example/sardb?ssl=require"})
    monkeypatch.setattr(config, "ENV_FILE", env_file)

    settings = config.get_settings()

    assert settings.database_url == "postgresql+asyncpg://env-file.example/sardb?ssl=require"


def test_database_schema_is_loaded_from_env_file(monkeypatch, tmp_path):
    clear_config_env(monkeypatch)
    env_file = tmp_path / ".env"
    write_env_file(env_file, {"DATABASE_SCHEMA": "env_file_schema"})
    monkeypatch.setattr(config, "ENV_FILE", env_file)

    settings = config.get_settings()

    assert settings.database_schema == "env_file_schema"


def test_azure_settings_are_loaded_from_env_file(monkeypatch, tmp_path):
    clear_config_env(monkeypatch)
    env_file = tmp_path / ".env"
    write_env_file(
        env_file,
        {
            "AZURE_BLOB_CONNECTION_STRING": "UseDevelopmentStorage=true",
            "AZURE_BLOB_CONTAINER_NAME": "sar-documents",
            "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com",
            "AZURE_OPENAI_API_KEY": "test-api-key",
            "AZURE_OPENAI_DEPLOYMENT": "gpt-5.5-test",
            "AZURE_OPENAI_TIMEOUT_SECONDS": "45.5",
            "AZURE_OPENAI_API_VERSION": "2024-10-21",
        },
    )
    monkeypatch.setattr(config, "ENV_FILE", env_file)

    settings = config.get_settings()

    assert settings.azure_blob_connection_string == "UseDevelopmentStorage=true"
    assert settings.azure_blob_container_name == "sar-documents"
    assert settings.azure_openai_endpoint == "https://example.openai.azure.com"
    assert settings.azure_openai_api_key == "test-api-key"
    assert settings.azure_openai_deployment == "gpt-5.5-test"
    assert settings.azure_openai_timeout_seconds == 45.5
    assert settings.azure_openai_api_version == "2024-10-21"


def test_environment_variables_override_env_file_values(monkeypatch, tmp_path):
    clear_config_env(monkeypatch)
    env_file = tmp_path / ".env"
    write_env_file(
        env_file,
        {
            "DATABASE_URL": "postgresql+asyncpg://env-file.example/sardb?ssl=require",
            "DATABASE_SCHEMA": "env_file_schema",
            "AZURE_BLOB_CONNECTION_STRING": "UseDevelopmentStorage=true",
            "AZURE_OPENAI_ENDPOINT": "https://env-file.openai.azure.com",
        },
    )
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://process-env.example/sardb?ssl=require")
    monkeypatch.setenv("DATABASE_SCHEMA", "process_env_schema")
    monkeypatch.setenv("AZURE_BLOB_CONNECTION_STRING", "DefaultEndpointsProtocol=https")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://process-env.openai.azure.com")

    settings = config.get_settings()

    assert settings.database_url == "postgresql+asyncpg://process-env.example/sardb?ssl=require"
    assert settings.database_schema == "process_env_schema"
    assert settings.azure_blob_connection_string == "DefaultEndpointsProtocol=https"
    assert settings.azure_openai_endpoint == "https://process-env.openai.azure.com"


def test_defaults_apply_only_when_env_and_env_file_are_absent(monkeypatch, tmp_path):
    clear_config_env(monkeypatch)
    env_file = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", env_file)

    settings = config.get_settings()

    assert settings.database_url == "sqlite+aiosqlite:///./sar_assessment.db"
    assert settings.database_schema is None
    assert settings.azure_blob_connection_string is None
    assert settings.azure_blob_container_name is None
    assert settings.azure_openai_endpoint is None
    assert settings.azure_openai_api_key is None
    assert settings.azure_openai_deployment is None
    assert settings.azure_openai_timeout_seconds == 30.0
    assert settings.azure_openai_api_version is None
