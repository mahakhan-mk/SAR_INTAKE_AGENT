from __future__ import annotations

import pytest

from app.llm.client import AzureExecutiveSummaryClient, AzureOpenAIClientSettings, ExecutiveSummaryOutput
from app.llm.executive_summary import ExecutiveSummaryPromptConfig, PromptConfigurationError


def test_azure_client_uses_v1_base_url():
    settings = AzureOpenAIClientSettings(
        endpoint="https://example-resource.openai.azure.com/",
        api_key="test-key",
        deployment="gpt-5-5",
        timeout_seconds=30.0,
        api_version="2024-10-21",
    )

    client = AzureExecutiveSummaryClient(settings=settings)

    assert settings.base_url == "https://example-resource.openai.azure.com/openai/v1/"
    assert str(client._client.base_url) == "https://example-resource.openai.azure.com/openai/v1/"


def test_prompt_renderer_supports_only_input_json_and_escaped_braces():
    prompt = ExecutiveSummaryPromptConfig(
        id="executive-summary",
        version="v1",
        system="System prompt",
        user_template='Payload:\\n{input_json}\\nReturn exactly: {{\"summary\":\"string\"}}',
    )

    rendered = prompt.render_user_prompt({"example": "value"})

    assert '"summary":"string"' in rendered
    assert '"example": "value"' in rendered


def test_prompt_renderer_rejects_unsupported_placeholders():
    prompt = ExecutiveSummaryPromptConfig(
        id="executive-summary",
        version="v1",
        system="System prompt",
        user_template="Payload: {unsupported}",
    )

    with pytest.raises(PromptConfigurationError):
        prompt.render_user_prompt({"example": "value"})


def test_structured_output_schema_forbids_additional_properties():
    schema = ExecutiveSummaryOutput.model_json_schema()

    assert schema["additionalProperties"] is False
