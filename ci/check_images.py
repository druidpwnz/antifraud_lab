"""Verify image metadata before archiving in CI and again before publishing."""

import json
import os
import subprocess

SERVICES = ("api", "admin", "rules", "generator")
SOURCE = "https://github.com/druidpwnz/antifraud_lab"


def validate(metadata, version):
    labels = metadata["Config"]["Labels"] or {}
    environment = metadata["Config"]["Env"]
    if (metadata["Os"], metadata["Architecture"]) != ("linux", "amd64"):
        raise ValueError("image must be linux/amd64")
    if labels.get("org.opencontainers.image.revision") != version:
        raise ValueError("image revision does not match the tested commit")
    if labels.get("org.opencontainers.image.source") != SOURCE:
        raise ValueError("image source does not match this repository")
    if f"BUILD_VERSION={version}" not in environment:
        raise ValueError("runtime build version does not match the tested commit")


def main():
    version = os.environ["BUILD_VERSION"]
    tag = os.environ.get("IMAGE_TAG", "local")
    for service in SERVICES:
        image = f"ghcr.io/druidpwnz/antifraud-{service}:{tag}"
        metadata = json.loads(subprocess.check_output(["docker", "image", "inspect", image]))[0]
        validate(metadata, version)
        print(f"PASS {image}: {metadata['Id']} ({version})")


if __name__ == "__main__":
    main()
