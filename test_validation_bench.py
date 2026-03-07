"""Tests for validation_bench helper functions."""

import pytest
from validation_bench import derive_slug


@pytest.mark.parametrize("model, effort, expected", [
    # Anthropic models — various ID formats to friendly names
    ("anthropic/claude-opus-4-6", None, "claude-opus-4.6"),
    ("anthropic/claude-sonnet-4-20250514", None, "claude-sonnet-4.0"),
    ("anthropic/claude-sonnet-4-0", None, "claude-sonnet-4.0"),
    # Cloud providers — strip provider prefix, lowercase
    ("minimax/MiniMax-M2.5", None, "minimax-m2.5"),
    ("zai/glm-5", None, "glm-5"),
    ("moonshot/kimi-k2.5", None, "kimi-k2.5"),
    # OpenAI models
    ("openai/gpt-5.3-codex", None, "gpt-5.3-codex"),
    # Reasoning effort suffix
    ("openai/gpt-5.3-codex", "high", "gpt-5.3-codex-high"),
    ("openai/gpt-5.3-codex", "low", "gpt-5.3-codex-low"),
    # Strip "-latest" suffix
    ("mistral/devstral-latest", None, "devstral"),
    # GGUF filenames — strip quantization/shard suffixes
    ("openai/Qwen3.5-122B-A10B-UD-Q8_K_XL-00001-of-00004.gguf", None, "qwen3.5-122b-a10b"),
    ("openai/some-model.gguf", None, "some-model"),
    # Bare model names (local server, gets openai/ prefix before reaching derive_slug)
    ("openai/qwen2.5-coder-32b", None, "qwen2.5-coder-32b"),
    # No provider prefix
    ("some-model", None, "some-model"),
])
def test_derive_slug(model, effort, expected):
    assert derive_slug(model, effort) == expected
