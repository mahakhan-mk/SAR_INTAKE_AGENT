from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.llm.client import AzureOpenAIClientSettings
from openai import OpenAI


def sanitize_message(message: str, secret: str | None) -> str:
    if not secret:
        return message
    return message.replace(secret, "[redacted]")


def main() -> int:
    settings = get_settings()
    client_settings = AzureOpenAIClientSettings.from_settings(settings)
    client = OpenAI(
        api_key=client_settings.api_key,
        base_url=client_settings.base_url,
    )

    print(f"deployment={client_settings.deployment}")
    print(f"configured_api_version={client_settings.api_version or '<none>'}")
    print(f"base_url={client_settings.base_url}")

    try:
        response = client.responses.create(
            model=client_settings.deployment,
            instructions="Return JSON only.",
            input='Return exactly {"summary":"ok"}.',
            text={
                "format": {
                    "type": "json_schema",
                    "name": "executive_summary_response",
                    "schema": {
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                        "required": ["summary"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                }
            },
            timeout=client_settings.timeout_seconds,
        )
        print("status_category=success")
        print(f"output_text={sanitize_message(getattr(response, 'output_text', ''), client_settings.api_key)}")
        return 0
    except Exception as exc:
        print("status_category=exception")
        print(f"exception_type={type(exc).__name__}")
        print(f"sanitized_error_message={sanitize_message(str(exc), client_settings.api_key)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
