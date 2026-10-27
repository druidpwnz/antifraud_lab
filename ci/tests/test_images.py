"""Reject stale or wrongly targeted images before the registry login step."""

import pytest
from ci.check_images import SOURCE, validate

VERSION = "a" * 40


@pytest.fixture
def metadata():
    return {
        "Os": "linux", "Architecture": "amd64",
        "Config": {
            "Labels": {"org.opencontainers.image.revision": VERSION, "org.opencontainers.image.source": SOURCE},
            "Env": [f"BUILD_VERSION={VERSION}"],
        },
    }


def test_matching_image_passes(metadata):
    validate(metadata, VERSION)


def test_wrong_architecture_fails(metadata):
    metadata["Architecture"] = "arm64"
    with pytest.raises(ValueError, match="linux/amd64"):
        validate(metadata, VERSION)


def test_wrong_revision_fails(metadata):
    with pytest.raises(ValueError, match="revision"):
        validate(metadata, "b" * 40)


def test_wrong_source_fails(metadata):
    metadata["Config"]["Labels"]["org.opencontainers.image.source"] = "https://example.invalid/other"
    with pytest.raises(ValueError, match="source"):
        validate(metadata, VERSION)


def test_runtime_version_must_match_label(metadata):
    metadata["Config"]["Env"] = ["BUILD_VERSION=local"]
    with pytest.raises(ValueError, match="runtime build version"):
        validate(metadata, VERSION)
