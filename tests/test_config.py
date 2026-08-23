"""
Tests for config.py - configuration loading and validation.
"""

import json
import pytest


@pytest.mark.unit
class TestLoadModelConfig:
    """Tests for load_model_config function."""

    def test_valid_model_config(self, tmp_path):
        """Test loading a valid model configuration file."""
        # Create a temporary config file
        config_file = tmp_path / "model_config.json"
        config_data = {
            "model": "anthropic/claude-3.5-sonnet",
            "temperature": 0.0,
            "max_tokens": 1000,
        }
        config_file.write_text(json.dumps(config_data))

        # Import after creating the file to avoid import-time config loading
        from config import load_model_config

        # Load and verify
        result = load_model_config(str(config_file))
        assert result["model"] == "anthropic/claude-3.5-sonnet"
        assert result["temperature"] == 0.0
        assert result["max_tokens"] == 1000

    def test_missing_config_file(self):
        """Test error when config file doesn't exist."""
        from config import load_model_config

        with pytest.raises(FileNotFoundError) as exc_info:
            load_model_config("nonexistent_file.json")

        assert "Model config file not found" in str(exc_info.value)
        assert "model_config.example.json" in str(exc_info.value)

    def test_missing_model_field(self, tmp_path):
        """Test error when 'model' field is missing."""
        config_file = tmp_path / "model_config.json"
        config_data = {"temperature": 0.0, "max_tokens": 1000}
        config_file.write_text(json.dumps(config_data))

        from config import load_model_config

        with pytest.raises(ValueError) as exc_info:
            load_model_config(str(config_file))

        assert "must contain 'model' field" in str(exc_info.value)

    def test_missing_temperature_field(self, tmp_path):
        """Test error when 'temperature' field is missing."""
        config_file = tmp_path / "model_config.json"
        config_data = {
            "model": "anthropic/claude-3.5-sonnet",
            "max_tokens": 1000,
        }
        config_file.write_text(json.dumps(config_data))

        from config import load_model_config

        with pytest.raises(ValueError) as exc_info:
            load_model_config(str(config_file))

        assert "must contain 'temperature' field" in str(exc_info.value)

    def test_missing_max_tokens_field(self, tmp_path):
        """Test error when 'max_tokens' field is missing."""
        config_file = tmp_path / "model_config.json"
        config_data = {
            "model": "anthropic/claude-3.5-sonnet",
            "temperature": 0.0,
        }
        config_file.write_text(json.dumps(config_data))

        from config import load_model_config

        with pytest.raises(ValueError) as exc_info:
            load_model_config(str(config_file))

        assert "must contain 'max_tokens' field" in str(exc_info.value)

    def test_invalid_model_type(self, tmp_path):
        """Test error when 'model' is not a string."""
        config_file = tmp_path / "model_config.json"
        config_data = {"model": 123, "temperature": 0.0, "max_tokens": 1000}
        config_file.write_text(json.dumps(config_data))

        from config import load_model_config

        with pytest.raises(ValueError) as exc_info:
            load_model_config(str(config_file))

        assert "'model' must be a string" in str(exc_info.value)

    def test_invalid_temperature_type(self, tmp_path):
        """Test error when 'temperature' is not a number."""
        config_file = tmp_path / "model_config.json"
        config_data = {
            "model": "anthropic/claude-3.5-sonnet",
            "temperature": "not_a_number",
            "max_tokens": 1000,
        }
        config_file.write_text(json.dumps(config_data))

        from config import load_model_config

        with pytest.raises(ValueError) as exc_info:
            load_model_config(str(config_file))

        assert "'temperature' must be a number" in str(exc_info.value)

    def test_invalid_max_tokens_type(self, tmp_path):
        """Test error when 'max_tokens' is not an integer."""
        config_file = tmp_path / "model_config.json"
        config_data = {
            "model": "anthropic/claude-3.5-sonnet",
            "temperature": 0.0,
            "max_tokens": "not_an_int",
        }
        config_file.write_text(json.dumps(config_data))

        from config import load_model_config

        with pytest.raises(ValueError) as exc_info:
            load_model_config(str(config_file))

        assert "'max_tokens' must be an integer" in str(exc_info.value)

    def test_temperature_out_of_range_high(self, tmp_path):
        """Test error when temperature is above 2.0."""
        config_file = tmp_path / "model_config.json"
        config_data = {
            "model": "anthropic/claude-3.5-sonnet",
            "temperature": 2.5,
            "max_tokens": 1000,
        }
        config_file.write_text(json.dumps(config_data))

        from config import load_model_config

        with pytest.raises(ValueError) as exc_info:
            load_model_config(str(config_file))

        assert "'temperature' must be between 0 and 2" in str(exc_info.value)

    def test_temperature_out_of_range_low(self, tmp_path):
        """Test error when temperature is below 0.0."""
        config_file = tmp_path / "model_config.json"
        config_data = {
            "model": "anthropic/claude-3.5-sonnet",
            "temperature": -0.1,
            "max_tokens": 1000,
        }
        config_file.write_text(json.dumps(config_data))

        from config import load_model_config

        with pytest.raises(ValueError) as exc_info:
            load_model_config(str(config_file))

        assert "'temperature' must be between 0 and 2" in str(exc_info.value)

    def test_max_tokens_zero(self, tmp_path):
        """Test error when max_tokens is 0."""
        config_file = tmp_path / "model_config.json"
        config_data = {
            "model": "anthropic/claude-3.5-sonnet",
            "temperature": 0.0,
            "max_tokens": 0,
        }
        config_file.write_text(json.dumps(config_data))

        from config import load_model_config

        with pytest.raises(ValueError) as exc_info:
            load_model_config(str(config_file))

        assert "'max_tokens' must be greater than 0" in str(exc_info.value)

    def test_max_tokens_negative(self, tmp_path):
        """Test error when max_tokens is negative."""
        config_file = tmp_path / "model_config.json"
        config_data = {
            "model": "anthropic/claude-3.5-sonnet",
            "temperature": 0.0,
            "max_tokens": -100,
        }
        config_file.write_text(json.dumps(config_data))

        from config import load_model_config

        with pytest.raises(ValueError) as exc_info:
            load_model_config(str(config_file))

        assert "'max_tokens' must be greater than 0" in str(exc_info.value)

    def test_invalid_json(self, tmp_path):
        """Test error when config file contains invalid JSON."""
        config_file = tmp_path / "model_config.json"
        config_file.write_text("{ invalid json }")

        from config import load_model_config

        with pytest.raises(ValueError) as exc_info:
            load_model_config(str(config_file))

        assert "Invalid JSON in config file" in str(exc_info.value)

    def test_temperature_float(self, tmp_path):
        """Test that temperature can be a float."""
        config_file = tmp_path / "model_config.json"
        config_data = {
            "model": "anthropic/claude-3.5-sonnet",
            "temperature": 0.5,
            "max_tokens": 1000,
        }
        config_file.write_text(json.dumps(config_data))

        from config import load_model_config

        result = load_model_config(str(config_file))
        assert result["temperature"] == 0.5

    def test_temperature_int(self, tmp_path):
        """Test that temperature can be an integer."""
        config_file = tmp_path / "model_config.json"
        config_data = {
            "model": "anthropic/claude-3.5-sonnet",
            "temperature": 1,
            "max_tokens": 1000,
        }
        config_file.write_text(json.dumps(config_data))

        from config import load_model_config

        result = load_model_config(str(config_file))
        assert result["temperature"] == 1


@pytest.fixture
def reload_config(monkeypatch):
    """
    Factory fixture: reload the config module with environment overrides applied.

    The reload is hermetic (a developer's .env / model_config.json are ignored),
    and the module is reloaded again at teardown so other tests see the normal state.
    """
    import importlib
    import config

    def _reload(**env):
        # Keep config.load_dotenv() from re-reading a real .env during reload
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("MODEL_CONFIG_PATH", raising=False)
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
