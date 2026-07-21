from __future__ import annotations

from dataclasses import dataclass

from openai import APITimeoutError, AzureOpenAI
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.llm.executive_summary import ExecutiveSummaryPromptConfig


class AzureOpenAIConfigurationError(RuntimeError):
    pass


class InvalidSummaryOutputError(RuntimeError):
    pass


class AzureSummaryRequestError(RuntimeError):
    pass


class AzureSummaryTimeoutError(AzureSummaryRequestError):
    pass


class ExecutiveSummaryOutput(BaseModel):
    summary: str


@dataclass(frozen=True)
class AzureOpenAIClientSettings:
    endpoint: str
    api_key: str
    deployment: str
    timeout_seconds: float
    api_version: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "AzureOpenAIClientSettings":
        missing = [
            name
            for name, value in [
                ("AZURE_OPENAI_ENDPOINT", settings.azure_openai_endpoint),
                ("AZURE_OPENAI_API_KEY", settings.azure_openai_api_key),
                ("AZURE_OPENAI_DEPLOYMENT", settings.azure_openai_deployment),
                ("AZURE_OPENAI_API_VERSION", settings.azure_openai_api_version),
            ]
            if not value
        ]
        if missing:
            raise AzureOpenAIConfigurationError(
                f"Missing Azure OpenAI configuration: {', '.join(missing)}."
            )

        return cls(
            endpoint=settings.azure_openai_endpoint or "",
            api_key=settings.azure_openai_api_key or "",
            deployment=settings.azure_openai_deployment or "",
            timeout_seconds=settings.azure_openai_timeout_seconds,
            api_version=settings.azure_openai_api_version or "",
        )


class AzureExecutiveSummaryClient:
    def __init__(
        self,
        settings: AzureOpenAIClientSettings | None = None,
        client: AzureOpenAI | None = None,
    ) -> None:
        resolved_settings = settings or AzureOpenAIClientSettings.from_settings(get_settings())
        self.settings = resolved_settings
        self._client = client or AzureOpenAI(
            api_key=resolved_settings.api_key,
            api_version=resolved_settings.api_version,
            azure_endpoint=resolved_settings.endpoint,
        )

    @property
    def model_name(self) -> str:
        return self.settings.deployment

    def generate_summary(
        self,
        prompt: ExecutiveSummaryPromptConfig,
        payload: dict[str, object],
    ) -> str:
        user_prompt = prompt.render_user_prompt(payload)
        last_validation_error: ValidationError | None = None

        for attempt in range(2):
            raw_text = self._create_response(prompt.system, user_prompt)
            try:
                parsed = ExecutiveSummaryOutput.model_validate_json(raw_text)
            except ValidationError as exc:
                last_validation_error = exc
                if attempt == 0:
                    continue
                raise InvalidSummaryOutputError("Azure OpenAI returned invalid structured output.") from exc

            return parsed.summary.strip()

        raise InvalidSummaryOutputError("Azure OpenAI returned invalid structured output.") from last_validation_error

    def _create_response(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = self._client.responses.create(
                model=self.settings.deployment,
                instructions=system_prompt,
                input=user_prompt,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "executive_summary_response",
                        "schema": ExecutiveSummaryOutput.model_json_schema(),
                        "strict": True,
                    }
                },
                timeout=self.settings.timeout_seconds,
            )
        except APITimeoutError as exc:
            raise AzureSummaryTimeoutError("Azure OpenAI request timed out.") from exc
        except Exception as exc:
            raise AzureSummaryRequestError("Azure OpenAI request failed.") from exc

        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise InvalidSummaryOutputError("Azure OpenAI returned empty structured output.")
        return output_text
