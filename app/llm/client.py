from __future__ import annotations

from dataclasses import dataclass
import logging

from openai import APITimeoutError, OpenAI
from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import Settings, get_settings
from app.llm.executive_summary import ExecutiveSummaryPromptConfig

logger = logging.getLogger(__name__)


class AzureOpenAIConfigurationError(RuntimeError):
    pass


class InvalidSummaryOutputError(RuntimeError):
    pass


class AzureSummaryRequestError(RuntimeError):
    pass


class AzureSummaryTimeoutError(AzureSummaryRequestError):
    pass


class ExecutiveSummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str


class DocumentChecklistSummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_text: str


@dataclass(frozen=True)
class AzureOpenAIClientSettings:
    endpoint: str
    api_key: str
    deployment: str
    timeout_seconds: float
    api_version: str | None

    @classmethod
    def from_settings(cls, settings: Settings) -> "AzureOpenAIClientSettings":
        missing = [
            name
            for name, value in [
                ("AZURE_OPENAI_ENDPOINT", settings.azure_openai_endpoint),
                ("AZURE_OPENAI_API_KEY", settings.azure_openai_api_key),
                ("AZURE_OPENAI_DEPLOYMENT", settings.azure_openai_deployment),
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
            api_version=settings.azure_openai_api_version,
        )

    @property
    def base_url(self) -> str:
        return f"{self.endpoint.rstrip('/')}/openai/v1/"


class AzureExecutiveSummaryClient:
    def __init__(
        self,
        settings: AzureOpenAIClientSettings | None = None,
        client: OpenAI | None = None,
    ) -> None:
        resolved_settings = settings or AzureOpenAIClientSettings.from_settings(get_settings())
        self.settings = resolved_settings
        self._client = client or OpenAI(
            api_key=resolved_settings.api_key,
            base_url=resolved_settings.base_url,
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
        output_model = (
            DocumentChecklistSummaryOutput
            if prompt.response_field == "summary_text"
            else ExecutiveSummaryOutput
        )

        for attempt in range(2):
            raw_text = self._create_response(prompt, user_prompt, output_model)
            try:
                parsed = output_model.model_validate_json(raw_text)
            except ValidationError as exc:
                logger.exception(
                    "Azure OpenAI executive summary response parsing failed for deployment=%s configured_api_version=%s attempt=%s",
                    self.settings.deployment,
                    self.settings.api_version or "<none>",
                    attempt + 1,
                )
                last_validation_error = exc
                if attempt == 0:
                    continue
                raise InvalidSummaryOutputError("Azure OpenAI returned invalid structured output.") from exc

            return getattr(parsed, prompt.response_field).strip()

        raise InvalidSummaryOutputError("Azure OpenAI returned invalid structured output.") from last_validation_error

    def _create_response(
        self,
        prompt: ExecutiveSummaryPromptConfig,
        user_prompt: str,
        output_model: type[BaseModel],
    ) -> str:
        try:
            response = self._client.responses.create(
                model=self.settings.deployment,
                instructions=prompt.system,
                input=user_prompt,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": f"{prompt.id}_response",
                        "schema": output_model.model_json_schema(),
                        "strict": True,
                    }
                },
                timeout=self.settings.timeout_seconds,
            )
        except APITimeoutError as exc:
            logger.exception(
                "Azure OpenAI executive summary request timed out for deployment=%s base_url=%s configured_api_version=%s",
                self.settings.deployment,
                self.settings.base_url,
                self.settings.api_version or "<none>",
            )
            raise AzureSummaryTimeoutError("Azure OpenAI request timed out.") from exc
        except Exception as exc:
            logger.exception(
                "Azure OpenAI executive summary request failed for deployment=%s base_url=%s configured_api_version=%s",
                self.settings.deployment,
                self.settings.base_url,
                self.settings.api_version or "<none>",
            )
            raise AzureSummaryRequestError("Azure OpenAI request failed.") from exc

        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise InvalidSummaryOutputError("Azure OpenAI returned empty structured output.")
        return output_text
