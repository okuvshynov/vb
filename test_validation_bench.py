"""Tests for validation_bench helper functions."""

import json
import threading
import pytest
from pathlib import Path
from validation_bench import derive_slug, claim_attempt_dir, InfraFailure


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


def test_claim_attempt_dir_sequential(tmp_path):
    """claim_attempt_dir assigns sequential indices."""
    attempts_dir = tmp_path / "attempts"
    idx0, dir0 = claim_attempt_dir(attempts_dir)
    idx1, dir1 = claim_attempt_dir(attempts_dir)
    idx2, dir2 = claim_attempt_dir(attempts_dir)

    assert idx0 == 0
    assert idx1 == 1
    assert idx2 == 2
    assert dir0.name == "0"
    assert dir1.name == "1"
    assert dir2.name == "2"
    assert dir0.is_dir()
    assert dir1.is_dir()
    assert dir2.is_dir()


def test_claim_attempt_dir_race_safety(tmp_path):
    """Concurrent calls to claim_attempt_dir never collide."""
    attempts_dir = tmp_path / "attempts"
    n_threads = 20
    results = [None] * n_threads
    errors = []

    def claim(i):
        try:
            results[i] = claim_attempt_dir(attempts_dir)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errors during concurrent claims: {errors}"

    indices = [r[0] for r in results]
    dirs = [r[1] for r in results]

    # All indices unique
    assert len(set(indices)) == n_threads
    # All dirs unique
    assert len(set(str(d) for d in dirs)) == n_threads
    # All dirs exist
    for d in dirs:
        assert d.is_dir()


def test_claim_attempt_dir_creates_parent(tmp_path):
    """claim_attempt_dir creates the attempts directory if it doesn't exist."""
    attempts_dir = tmp_path / "deep" / "nested" / "attempts"
    assert not attempts_dir.exists()
    idx, d = claim_attempt_dir(attempts_dir)
    assert idx == 0
    assert d.is_dir()


def test_infra_failure_dataclass():
    """InfraFailure stores error details."""
    f = InfraFailure(
        timestamp="2025-01-01T00:00:00+00:00",
        turn=2,
        error_type="api_error",
        error_message="Connection refused",
    )
    assert f.turn == 2
    assert f.error_type == "api_error"
