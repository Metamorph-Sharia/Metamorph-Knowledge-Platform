import pytest

from metamorph_platform.config import ConfigurationError, Settings


def test_settings_come_from_the_environment() -> None:
    settings = Settings.from_environment({"METAMORPH_DATABASE_URL": "postgresql://u:p@db/metamorph"})

    assert settings.database_url == "postgresql://u:p@db/metamorph"


def test_a_missing_setting_is_named() -> None:
    with pytest.raises(ConfigurationError, match="METAMORPH_DATABASE_URL"):
        Settings.from_environment({})
