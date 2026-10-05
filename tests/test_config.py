"""
Tests for config.py - configuration loading and validation.
"""

import importlib
import json

import pytest

VALID = {
    "labels": ["Finance", "Shopping"],
    "label_descriptions": {
        "Finance": "Bills and bank statements",
        "Shopping": "Order and shipping notifications",
    },
}


def _write(tmp_path, data):
    path = tmp_path / "classifier_config.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return str(path)


@pytest.mark.unit
class TestLoadClassifierConfig:
    """load_classifier_config requires labels and a description per label."""

    def test_valid_config(self, tmp_path):
        from config import load_classifier_config

        result = load_classifier_config(_write(tmp_path, VALID))
        assert result["labels"] == ["Finance", "Shopping"]
        assert result["label_descriptions"]["Finance"] == "Bills and bank statements"

    def test_legacy_classification_prompt_is_tolerated(self, tmp_path):
        from config import load_classifier_config

        legacy = {**VALID, "classification_prompt": "old prompt text"}
        result = load_classifier_config(_write(tmp_path, legacy))
        assert result["labels"] == ["Finance", "Shopping"]

    def test_missing_file(self):
        from config import load_classifier_config

        with pytest.raises(FileNotFoundError, match="classifier_config.example.json"):
            load_classifier_config("nonexistent_file.json")

    def test_invalid_json(self, tmp_path):
        from config import load_classifier_config

        with pytest.raises(ValueError, match="Invalid JSON"):
            load_classifier_config(_write(tmp_path, "{ invalid json }"))

    @pytest.mark.parametrize(
        "data,message",
        [
            ({"label_descriptions": {}}, "must contain 'labels'"),
            ({"labels": "Finance", "label_descriptions": {}}, "list of non-empty"),
            ({"labels": ["", "A"], "label_descriptions": {}}, "list of non-empty"),
            ({"labels": ["Finance"]}, "must contain 'label_descriptions'"),
            ({"labels": ["Finance"], "label_descriptions": "x"}, "must map"),
            ({"labels": ["Finance"], "label_descriptions": {"Finance": 1}}, "must map"),
            ({"labels": ["Finance"], "label_descriptions": {}}, "missing"),
            ({"labels": [], "label_descriptions": {}}, "At least one"),
            ({"labels": ["None"], "label_descriptions": {"None": "x"}}, "reserved"),
        ],
    )
    def test_rejects_invalid_shapes(self, tmp_path, data, message):
        from config import load_classifier_config

        with pytest.raises(ValueError, match=message):
            load_classifier_config(_write(tmp_path, data))


@pytest.fixture
def reload_config(monkeypatch):
    """
    Factory fixture: reload the config module with environment overrides applied.

    The reload is hermetic (a developer's .env is ignored), and the module is
    reloaded again at teardown so other tests see the normal state.
    """
    import config

    def _reload(**env):
        # Keep config.load_dotenv() from re-reading a real .env during reload
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
        for key in (
            "LLM_BASE_URL",
            "JEV_MODEL",
            "JEV_DECISIONS_URL",
            "JEV_LABEL_THRESHOLD",
            "JEV_FALLBACK_CONFIDENCE",
            "JEV_TIMEOUT_SECONDS",
            "JEV_REVIEW_LABEL",
            "DRY_RUN",
        ):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(config)

    yield _reload

    monkeypatch.undo()
    importlib.reload(config)


@pytest.mark.unit
class TestLLMBaseURL:
    """Tests for LLM_BASE_URL resolution in config.py."""

    OPENROUTER = "https://openrouter.ai/api/v1"

    def test_defaults_to_openrouter_when_unset(self, reload_config):
        config = reload_config()
        assert config.LLM_BASE_URL == self.OPENROUTER

    def test_uses_custom_url_when_set(self, reload_config):
        config = reload_config(LLM_BASE_URL="http://litellm:4000/v1")
        assert config.LLM_BASE_URL == "http://litellm:4000/v1"

    def test_strips_surrounding_whitespace(self, reload_config):
        config = reload_config(LLM_BASE_URL="  http://litellm:4000/v1 ")
        assert config.LLM_BASE_URL == "http://litellm:4000/v1"

    @pytest.mark.parametrize("empty_value", ["", "   "])
    def test_empty_value_falls_back_to_openrouter(self, reload_config, empty_value):
        config = reload_config(LLM_BASE_URL=empty_value)
        assert config.LLM_BASE_URL == self.OPENROUTER

    def test_api_key_still_read_from_openrouter_var(self, reload_config):
        """OPENROUTER_API_KEY is the bearer token regardless of base URL."""
        config = reload_config(
            LLM_BASE_URL="http://litellm:4000/v1",
            OPENROUTER_API_KEY="sk-litellm-virtual-key",
        )
        assert config.OPENROUTER_API_KEY == "sk-litellm-virtual-key"


@pytest.mark.unit
class TestJevSettings:
    """Jev endpoint, model, thresholds and dry-run flags."""

    def test_defaults(self, reload_config):
        config = reload_config()
        assert config.JEV_MODEL == "typesafe/jev-1.13"
        assert config.JEV_DECISIONS_URL == "https://openrouter.ai/api/alpha/decisions"
        assert config.JEV_LABEL_THRESHOLD == 0.7
        assert config.JEV_FALLBACK_CONFIDENCE == 0.5
        assert config.JEV_TIMEOUT_SECONDS == 30.0
        assert config.JEV_REVIEW_LABEL == ""
        assert config.DRY_RUN is False
        assert config.LABELS == ["AWS", "Finance", "Work", "Personal"]
        assert set(config.LABEL_DESCRIPTIONS) == set(config.LABELS)

    def test_decisions_url_derived_from_gateway_base_url(self, reload_config):
        config = reload_config(LLM_BASE_URL="http://litellm.lan:4000/v1")
        assert (
            config.JEV_DECISIONS_URL
            == "http://litellm.lan:4000/openrouter/alpha/decisions"
        )

    def test_explicit_decisions_url_wins(self, reload_config):
        config = reload_config(
            LLM_BASE_URL="http://litellm.lan:4000/v1",
            JEV_DECISIONS_URL=" https://openrouter.ai/api/alpha/decisions ",
        )
        assert config.JEV_DECISIONS_URL == "https://openrouter.ai/api/alpha/decisions"

    def test_overrides(self, reload_config):
        config = reload_config(
            JEV_MODEL="typesafe/jev-1.14",
            JEV_LABEL_THRESHOLD="0.8",
            JEV_FALLBACK_CONFIDENCE="0.6",
            JEV_TIMEOUT_SECONDS="10",
            JEV_REVIEW_LABEL=" Review ",
            DRY_RUN="TRUE",
        )
        assert config.JEV_MODEL == "typesafe/jev-1.14"
        assert config.JEV_LABEL_THRESHOLD == 0.8
        assert config.JEV_FALLBACK_CONFIDENCE == 0.6
        assert config.JEV_TIMEOUT_SECONDS == 10.0
        assert config.JEV_REVIEW_LABEL == "Review"
        assert config.DRY_RUN is True

    @pytest.mark.parametrize(
        "env",
        [
            {"JEV_LABEL_THRESHOLD": "1.5"},
            {"JEV_FALLBACK_CONFIDENCE": "-0.1"},
            {"JEV_TIMEOUT_SECONDS": "0"},
        ],
    )
    def test_out_of_range_values_fail_fast(self, reload_config, env):
        with pytest.raises(ValueError, match="must be between"):
            reload_config(**env)
