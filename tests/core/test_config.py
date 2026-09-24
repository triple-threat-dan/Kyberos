import json
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from kyberos.core import config

# Create aliases for clarity in tests
KyberosConfig = config.KyberosConfig
ConfigLoader = config.ConfigLoader
SecretsManager = config.SecretsManager

@pytest.fixture
def mock_cwd(tmp_path):
    """Fixture to provide a temporary current working directory."""
    with patch("kyberos.core.config.Path.cwd", return_value=tmp_path):
        yield tmp_path

@pytest.fixture
def mock_kyberosroot(tmp_path):
    """Fixture to mock KYBEROS_ROOT to a temporary path."""
    kyberosroot = tmp_path / ".kyberos"
    with patch("kyberos.core.config.KYBEROS_ROOT", kyberosroot), \
         patch.object(ConfigLoader, "DEFAULT_CONFIG_DIR", kyberosroot):
        yield kyberosroot

@pytest.fixture(autouse=True)
def reset_globals():
    """Reset global state between tests."""
    config._params = None
    config._secrets = None
    yield
    config._params = None
    config._secrets = None

# ==============================================================================
# Tests for find_kyberosroot
# ==============================================================================

def test_find_kyberosroot_in_cwd(mock_cwd):
    """Test find_kyberosroot when .kyberos is in cwd."""
    (mock_cwd / ".kyberos").mkdir()
    assert config.find_kyberosroot() == mock_cwd / ".kyberos"

def test_find_kyberosroot_not_found(mock_cwd):
    """Test find_kyberosroot when .kyberos does not exist."""
    # Since find_kyberosroot is now strictly local, it returns CWD / .kyberos
    # regardless of whether the directory exists or not.
    assert config.find_kyberosroot() == mock_cwd / ".kyberos"

# ==============================================================================
# Tests for ConfigLoader
# ==============================================================================

def test_config_loader_get_config_path(mock_kyberosroot):
    expected_path = mock_kyberosroot / ConfigLoader.CONFIG_FILENAME
    assert ConfigLoader.get_config_path() == expected_path

def test_config_loader_ensure_permissions_creates_parent(mock_kyberosroot):
    config_path = mock_kyberosroot / ConfigLoader.CONFIG_FILENAME
    assert not mock_kyberosroot.exists()
    
    ConfigLoader._ensure_permissions(config_path)
    
    assert mock_kyberosroot.exists()

def test_config_loader_ensure_permissions_parent_creation_fails(mock_kyberosroot):
    config_path = mock_kyberosroot / ConfigLoader.CONFIG_FILENAME
    
    with patch("pathlib.Path.mkdir", side_effect=Exception("mkdir failed")):
        with pytest.raises(Exception, match="mkdir failed"):
            ConfigLoader._ensure_permissions(config_path)

def test_config_loader_ensure_permissions_changes_mode(mock_kyberosroot, caplog):
    import logging
    caplog.set_level(logging.INFO)
    
    config_path = mock_kyberosroot / ConfigLoader.CONFIG_FILENAME
    mock_kyberosroot.mkdir()
    config_path.touch()
    
    # We must patch sys.platform because the logic bypasses chmod on win32
    with patch("sys.platform", "linux"):
        with patch("os.stat") as mock_stat, \
             patch("kyberos.core.config.os.chmod") as mock_chmod:
            mock_stat_obj = MagicMock()
            mock_stat_obj.st_mode = 0o100644 # Has group/other read permissions
            mock_stat.return_value = mock_stat_obj
            
            with patch.object(Path, "stat", return_value=mock_stat_obj):
                ConfigLoader._ensure_permissions(config_path)
    
    # Assert that os.chmod was called to set to 0o600
    mock_chmod.assert_called_once_with(config_path, 0o600)
    assert f"Fixed permissions for {config_path} to 0600." in caplog.text

def test_config_loader_ensure_permissions_chmod_fails(mock_kyberosroot, caplog):
    config_path = mock_kyberosroot / ConfigLoader.CONFIG_FILENAME
    mock_kyberosroot.mkdir()
    config_path.touch()
    
    with patch("os.chmod", side_effect=Exception("chmod failed")):
        # We also need to mock sys.platform if it's win32 since it skips chmod inside the method
        with patch("sys.platform", "linux"):
             # Set mode manually so it triggers chmod attempt
             with patch("os.stat") as mock_stat:
                 mock_stat_obj = MagicMock()
                 mock_stat_obj.st_mode = 0o100644
                 mock_stat.return_value = mock_stat_obj
                 with patch("pathlib.Path.stat", return_value=mock_stat_obj):
                     ConfigLoader._ensure_permissions(config_path)
    
    assert "Could not enforce permissions" in caplog.text

def test_config_loader_load_creates_default(mock_kyberosroot, caplog):
    import logging
    caplog.set_level(logging.INFO)
    
    config_path = mock_kyberosroot / ConfigLoader.CONFIG_FILENAME
    assert not config_path.exists()
    
    loaded_config = ConfigLoader.load()
    
    assert isinstance(loaded_config, KyberosConfig)
    assert config_path.exists()
    assert "Creating default" in caplog.text

def test_config_loader_load_existing_valid(mock_kyberosroot):
    config_path = mock_kyberosroot / ConfigLoader.CONFIG_FILENAME
    mock_kyberosroot.mkdir(parents=True, exist_ok=True)
    
    # Write some valid JSON5
    config_content = '{"debug": true}'
    config_path.write_text(config_content, encoding="utf-8")
    
    loaded_config = ConfigLoader.load()
    
    assert isinstance(loaded_config, KyberosConfig)
    assert loaded_config.debug is True

def test_config_loader_load_existing_invalid(mock_kyberosroot):
    config_path = mock_kyberosroot / ConfigLoader.CONFIG_FILENAME
    mock_kyberosroot.mkdir(parents=True, exist_ok=True)
    
    # Write invalid JSON
    config_path.write_text("{invalid json}", encoding="utf-8")
    
    with pytest.raises(ValueError, match="Invalid configuration file"):
        ConfigLoader.load()

def test_config_loader_save_new_file(mock_kyberosroot):
    config_path = mock_kyberosroot / ConfigLoader.CONFIG_FILENAME
    assert not config_path.exists()
    
    new_config = KyberosConfig(debug=True)
    ConfigLoader.save(new_config)
    
    assert config_path.exists()
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["debug"] is True

def test_config_loader_save_existing_file(mock_kyberosroot):
    config_path = mock_kyberosroot / ConfigLoader.CONFIG_FILENAME
    mock_kyberosroot.mkdir()
    config_path.write_text("{}", encoding="utf-8")
    
    new_config = KyberosConfig(debug=True)
    ConfigLoader.save(new_config)
    
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["debug"] is True

def test_config_loader_save_existing_file_chmod_fails(mock_kyberosroot):
    config_path = mock_kyberosroot / ConfigLoader.CONFIG_FILENAME
    mock_kyberosroot.mkdir()
    config_path.write_text("{}", encoding="utf-8")
    
    new_config = KyberosConfig(debug=True)
    with patch("kyberos.core.config.os.chmod", side_effect=Exception("chmod failed")):
        ConfigLoader.save(new_config)
        
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["debug"] is True

def test_config_loader_save_fails(mock_kyberosroot):
    new_config = KyberosConfig()
    with patch("kyberos.core.config.os.open", side_effect=Exception("open failed")):
        with pytest.raises(Exception, match="open failed"):
            ConfigLoader.save(new_config)

# ==============================================================================
# Tests for SecretsManager
# ==============================================================================

def test_secrets_manager_get_secret():
    test_config = KyberosConfig()
    test_config.keys.openai = "test-key"
    test_config.tools = {"custom_tool": {"secret": "tool-secret"}}
    
    sm = SecretsManager(test_config)
    
    assert sm.get_secret("keys.openai") == "test-key"
    assert sm.get_secret("tools.custom_tool.secret") == "tool-secret"

def test_secrets_manager_get_secret_not_found():
    test_config = KyberosConfig()
    sm = SecretsManager(test_config)
    
    assert sm.get_secret("keys.nonexistent") is None
    assert sm.get_secret("does.not.exist") is None

def test_secrets_manager_get_secret_not_string():
    test_config = KyberosConfig()
    test_config.tools = {"custom_tool": {"complex": {"nested": "dict"}}}
    
    sm = SecretsManager(test_config)
    # The value is a dictionary, not string/int/float/bool
    assert sm.get_secret("tools.custom_tool.complex") is None


def test_bedrock_settings_load_from_json_shape():
    test_config = KyberosConfig(**{
        "agents": {
            "models": {
                "smart_model": {
                    "provider": "bedrock",
                    "model": "bedrock/amazon.nova-pro-v1:0",
                }
            }
        },
        "keys": {
            "bedrock": "bedrock-api-key",
            "bedrock_access_key_id": "aws-access-key",
            "bedrock_secret_access_key": "aws-secret-key",
            "bedrock_session_token": "aws-session-token",
            "bedrock_region": "us-west-2",
        },
    })

    assert test_config.agents.models["smart_model"].provider == "bedrock"
    assert test_config.agents.models["smart_model"].model == "bedrock/amazon.nova-pro-v1:0"
    assert test_config.keys.bedrock == "bedrock-api-key"
    assert test_config.keys.bedrock_access_key_id == "aws-access-key"
    assert test_config.keys.bedrock_secret_access_key == "aws-secret-key"
    assert test_config.keys.bedrock_session_token == "aws-session-token"
    assert test_config.keys.bedrock_region == "us-west-2"

# ==============================================================================
# Tests for Global Accessors
# ==============================================================================

def test_load_config(mock_kyberosroot):
    loaded = config.load_config()
    assert isinstance(loaded, KyberosConfig)
    # Consecutive calls return the same instance
    assert config.load_config() is loaded

def test_get_secrets_manager(mock_kyberosroot):
    sm = config.get_secrets_manager()
    assert isinstance(sm, SecretsManager)
    # Consecutive calls return the same instance
    assert config.get_secrets_manager() is sm


def test_get_secrets_manager_initialization_fails():
    """Test when SecretsManager unexpectedly fails to initialize."""
    config._secrets = None
    config._params = None
    
    # Force load_config to set _secrets to None (which it wouldn't normally do)
    with patch("kyberos.core.config.load_config") as mock_load:
        def side_effect():
            config._secrets = None
        mock_load.side_effect = side_effect
        
        with pytest.raises(RuntimeError, match="Failed to initialize SecretsManager"):
            config.get_secrets_manager()
