import pytest

from metamorph_platform.config import ConfigurationError, Settings


def test_settings_come_from_the_environment() -> None:
    settings = Settings.from_environment({"METAMORPH_DATABASE_URL": "postgresql://u:p@db/metamorph"})

    assert settings.database_url == "postgresql://u:p@db/metamorph"


def test_a_missing_setting_is_named() -> None:
    with pytest.raises(ConfigurationError, match="METAMORPH_DATABASE_URL"):
        Settings.from_environment({})


def test_files_are_linked_for_the_address_browsers_use_when_it_differs() -> None:
    environment = {"METAMORPH_DATABASE_URL": "postgresql://u:p@db/metamorph"}
    local = {**environment, "METAMORPH_S3_ENDPOINT_URL": "http://objectstore:8333"}

    assert Settings.from_environment(environment).s3_public_endpoint_url is None  # AWS S3: one address
    assert (
        Settings.from_environment(
            {**local, "METAMORPH_S3_PUBLIC_ENDPOINT_URL": "http://localhost:8333"}
        ).s3_public_endpoint_url
        == "http://localhost:8333"
    )
