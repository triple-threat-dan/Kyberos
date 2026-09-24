import json
import logging
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from kyberos.core.pairing import PairingManager

@pytest.fixture
def temp_kyberosroot(tmp_path):
    return tmp_path

@pytest.fixture
def pairing_manager(temp_kyberosroot):
    with patch("kyberos.core.pairing.KYBEROS_ROOT", temp_kyberosroot):
        return PairingManager()

def test_init_creates_dir(temp_kyberosroot):
    with patch("kyberos.core.pairing.KYBEROS_ROOT", temp_kyberosroot):
        pm = PairingManager()
        assert (temp_kyberosroot / "credentials").exists()
        assert (temp_kyberosroot / "credentials").is_dir()

def test_get_pairing_file(pairing_manager, temp_kyberosroot):
    protocol = "discord"
    expected = temp_kyberosroot / "credentials" / "discord-pairing.json"
    assert pairing_manager._get_pairing_file(protocol) == expected

def test_get_allow_file(pairing_manager, temp_kyberosroot):
    protocol = "discord"
    expected = temp_kyberosroot / "credentials" / "discord-allowFrom.json"
    assert pairing_manager._get_allow_file(protocol) == expected

def test_load_json_returns_empty_if_not_exists(pairing_manager):
    assert pairing_manager._load_json(Path("non_existent_file.json")) == {}

def test_load_json_success(pairing_manager, temp_kyberosroot):
    test_file = temp_kyberosroot / "test.json"
    data = {"key": "value"}
    test_file.write_text(json.dumps(data), encoding="utf-8")
    assert pairing_manager._load_json(test_file) == data

def test_load_json_error(pairing_manager, temp_kyberosroot, caplog):
    test_file = temp_kyberosroot / "invalid.json"
    test_file.write_text("invalid json", encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        assert pairing_manager._load_json(test_file) == {}
        assert "Failed to load" in caplog.text

def test_save_json_success(pairing_manager, temp_kyberosroot):
    test_file = temp_kyberosroot / "save.json"
    data = {"hello": "world"}
    pairing_manager._save_json(test_file, data)
    assert test_file.exists()
    assert json.loads(test_file.read_text(encoding="utf-8")) == data

def test_save_json_error(pairing_manager, caplog):
    # Pass a path that can't be written to (e.g. a directory)
    bad_path = Path(".")
    with caplog.at_level(logging.ERROR):
        pairing_manager._save_json(bad_path, {"test": 1})
        assert "Failed to save" in caplog.text

def test_is_user_allowed_config(pairing_manager):
    assert pairing_manager.is_user_allowed("discord", "123", config_allowed=["123"]) is True
    assert pairing_manager.is_user_allowed("discord", "456", config_allowed=["123"]) is False

def test_is_user_allowed_file(pairing_manager, temp_kyberosroot):
    allow_file = pairing_manager._get_allow_file("discord")
    pairing_manager._save_json(allow_file, {"123": "user1"})
    
    assert pairing_manager.is_user_allowed("discord", "123") is True
    assert pairing_manager.is_user_allowed("discord", 123) is True # Should handle int conversion to string
    assert pairing_manager.is_user_allowed("discord", "456") is False

def test_create_request_new(pairing_manager, temp_kyberosroot, caplog):
    import logging
    protocol = "discord"
    user_id = "789"
    user_name = "test_user"
    
    with caplog.at_level(logging.INFO):
        code = pairing_manager.create_request(protocol, user_id, user_name)
        assert len(code) == 6
        assert isinstance(code, str)
        
        pending = pairing_manager.list_requests(protocol)
        assert code in pending
        assert pending[code]["user_id"] == "789"
        assert pending[code]["user_name"] == "test_user"
        
        assert f"New Pairing Request: test_user (789) -> Code: {code}" in caplog.text

def test_create_request_integer_id(pairing_manager):
    protocol = "discord"
    user_id = 999
    user_name = "int_user"
    code = pairing_manager.create_request(protocol, user_id, user_name)
    pending = pairing_manager.list_requests(protocol)
    assert pending[code]["user_id"] == "999"

def test_create_request_existing(pairing_manager):
    protocol = "discord"
    user_id = "789"
    
    code1 = pairing_manager.create_request(protocol, user_id, "user1")
    code2 = pairing_manager.create_request(protocol, user_id, "user1")
    
    assert code1 == code2
    assert len(pairing_manager.list_requests(protocol)) == 1

def test_list_requests_empty_if_no_file(pairing_manager):
    assert pairing_manager.list_requests("slack") == {}

def test_approve_request_success(pairing_manager):
    protocol = "discord"
    user_id = "111"
    user_name = "approved_user"
    
    code = pairing_manager.create_request(protocol, user_id, user_name)
    assert code in pairing_manager.list_requests(protocol)
    
    # Approve (case insensitive test)
    result = pairing_manager.approve_request(protocol, code.lower())
    assert result == user_name
    
    # Check pending removed
    assert code not in pairing_manager.list_requests(protocol)
    
    # Check added to allowFrom
    assert pairing_manager.is_user_allowed(protocol, user_id) is True

def test_approve_request_not_found(pairing_manager):
    assert pairing_manager.approve_request("discord", "NONEXISTENT") is None

