import os

import pytest

import hannah.utils.db as db_module
from hannah.settings_manager import SettingsManager


@pytest.fixture
def manager(tmp_path):
    db_module.DB_PATH = os.path.join(str(tmp_path), "h.db")
    db_module.init_db()
    return SettingsManager(db_module.get_db)


class TestScalarJsonFieldRoundtrip:
    """Regression for #113: BaseModel.create()/update() only re-encoded __json_fields__
    when the value was a list/dict, so a plain string (like llm.system_prompt) got written
    to the DB unencoded and crashed the next read with JSONDecodeError."""

    def test_string_value_survives_create_and_read(self, manager):
        cat_id = manager.ensure_category("llm")
        text = 'Du bist Hannah.\nZeile zwei mit "Anführungszeichen".'
        created = manager.create_setting(cat_id, "system_prompt", text)
        assert created is not None

        settings = manager.get_settings()
        stored = next(s for s in settings if s["name"] == "system_prompt")
        assert stored["value"] == text

    def test_string_value_survives_update_and_read(self, manager):
        cat_id = manager.ensure_category("llm")
        created = manager.create_setting(cat_id, "system_prompt", "initial")

        ok = manager.update_setting_value(created["id"], "updated\nwith a newline")
        assert ok is True

        settings = manager.get_settings()
        stored = next(s for s in settings if s["id"] == created["id"])
        assert stored["value"] == "updated\nwith a newline"

    def test_list_value_still_works(self, manager):
        """Guards against regressing the list/dict case the isinstance check used to cover."""
        cat_id = manager.ensure_category("ble")
        created = manager.create_setting(cat_id, "tags", ["a", "b"])

        settings = manager.get_settings()
        stored = next(s for s in settings if s["id"] == created["id"])
        assert stored["value"] == ["a", "b"]
