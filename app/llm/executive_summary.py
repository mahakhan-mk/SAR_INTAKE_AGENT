from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError


class PromptConfigurationError(RuntimeError):
    pass


class ExecutiveSummaryPromptConfig(BaseModel):
    id: str
    version: str
    system: str
    user_template: str
    response_field: str = "summary"

    def render_user_prompt(self, payload: dict[str, object]) -> str:
        input_json = json.dumps(payload, indent=2, sort_keys=True)
        try:
            return self.user_template.format(input_json=input_json, **payload)
        except KeyError as exc:
            raise PromptConfigurationError(
                f"Executive summary prompt template is missing a supported placeholder: {exc.args[0]}."
            ) from exc


class ExecutiveSummaryPromptLoader:
    def __init__(self, prompt_path: Path | None = None) -> None:
        self.prompt_path = prompt_path or Path(__file__).resolve().parents[1] / "prompts" / "executive_summary.yaml"

    def load(self) -> ExecutiveSummaryPromptConfig:
        if not self.prompt_path.exists():
            raise PromptConfigurationError(
                f"Executive summary prompt file was not found at {self.prompt_path}."
            )

        raw_content = self.prompt_path.read_text(encoding="utf-8")
        if not raw_content.strip():
            raise PromptConfigurationError(
                f"Executive summary prompt file at {self.prompt_path} is empty."
            )

        try:
            payload = yaml.safe_load(raw_content)
        except yaml.YAMLError as exc:
            raise PromptConfigurationError(
                f"Executive summary prompt file at {self.prompt_path} is invalid YAML."
            ) from exc

        if not isinstance(payload, dict):
            raise PromptConfigurationError(
                f"Executive summary prompt file at {self.prompt_path} must define a mapping."
            )

        normalized_payload = dict(payload)
        if "system_prompt" in normalized_payload:
            normalized_payload["system"] = normalized_payload.pop("system_prompt")
        if "user_prompt_template" in normalized_payload:
            normalized_payload["user_template"] = normalized_payload.pop("user_prompt_template")
            normalized_payload.setdefault("response_field", "summary_text")
        normalized_payload.setdefault("id", self.prompt_path.stem)

        try:
            return ExecutiveSummaryPromptConfig.model_validate(normalized_payload)
        except ValidationError as exc:
            raise PromptConfigurationError(
                f"Executive summary prompt file at {self.prompt_path} is missing one or more required fields."
            ) from exc
