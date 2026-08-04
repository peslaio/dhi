#!/usr/bin/env python3
"""Resolve and validate digest-pinned functional-test fixture images."""

import argparse
import json
import pathlib
import re
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "tests" / "functional" / "fixtures.lock.json"
EXPECTED_FIXTURES = {
    "dotnet-sdk-8.0",
    "dotnet-sdk-9.0",
    "dotnet-sdk-10.0",
    "harness-python",
    "java-builder",
    "php-nginx",
}
EXPECTED_PLATFORMS = ["linux/amd64", "linux/arm64"]
REFERENCE_PATTERN = re.compile(
    r"^[^\s@]+:[^\s@]+@sha256:[0-9a-f]{64}$"
)


class FixtureError(RuntimeError):
    pass


def load_lock():
    try:
        with LOCK_PATH.open(encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureError(f"cannot read {LOCK_PATH.relative_to(ROOT)}: {exc}")

    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "updatedAt",
        "fixtures",
    }:
        raise FixtureError("fixture lock must contain schemaVersion, updatedAt, and fixtures")
    if value["schemaVersion"] != 1:
        raise FixtureError("fixture lock schemaVersion must equal 1")
    if not isinstance(value["updatedAt"], str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", value["updatedAt"]
    ):
        raise FixtureError("fixture lock updatedAt must be YYYY-MM-DD")
    fixtures = value["fixtures"]
    if not isinstance(fixtures, dict) or set(fixtures) != EXPECTED_FIXTURES:
        missing = sorted(EXPECTED_FIXTURES - set(fixtures or {}))
        extra = sorted(set(fixtures or {}) - EXPECTED_FIXTURES)
        raise FixtureError(f"fixture lock key mismatch; missing={missing}, extra={extra}")

    references = set()
    for name, fixture in fixtures.items():
        if not isinstance(fixture, dict) or set(fixture) != {"reference", "platforms"}:
            raise FixtureError(f"fixture {name} must contain reference and platforms")
        reference = fixture["reference"]
        if not isinstance(reference, str) or not REFERENCE_PATTERN.fullmatch(reference):
            raise FixtureError(f"fixture {name} is not pinned by tag and sha256 digest")
        if reference in references:
            raise FixtureError(f"fixture reference is duplicated: {reference}")
        references.add(reference)
        if fixture["platforms"] != EXPECTED_PLATFORMS:
            raise FixtureError(
                f"fixture {name} must declare {', '.join(EXPECTED_PLATFORMS)}"
            )
    return fixtures


def online_platforms(reference):
    command = ["docker", "buildx", "imagetools", "inspect", reference, "--raw"]
    try:
        completed = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
        manifest = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise FixtureError(f"cannot inspect fixture {reference}: {exc}")

    platforms = set()
    for descriptor in manifest.get("manifests", []):
        platform = descriptor.get("platform", {})
        candidate = f"{platform.get('os')}/{platform.get('architecture')}"
        if candidate in EXPECTED_PLATFORMS:
            platforms.add(candidate)
    return sorted(platforms, key=EXPECTED_PLATFORMS.index)


def command_validate(fixtures, online):
    if online:
        for name, fixture in fixtures.items():
            actual = online_platforms(fixture["reference"])
            if actual != fixture["platforms"]:
                raise FixtureError(
                    f"fixture {name} platform mismatch: expected "
                    f"{fixture['platforms']}, found {actual}"
                )
    print(
        json.dumps(
            {
                "schemaVersion": 1,
                "fixtures": len(fixtures),
                "online": online,
                "status": "pass",
            },
            separators=(",", ":"),
        )
    )


def parse_args():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--online", action="store_true")
    resolve = commands.add_parser("resolve")
    resolve.add_argument("name")
    return parser.parse_args()


def main():
    args = parse_args()
    fixtures = load_lock()
    if args.command == "validate":
        command_validate(fixtures, args.online)
    else:
        try:
            print(fixtures[args.name]["reference"])
        except KeyError:
            raise FixtureError(f"unknown fixture: {args.name}")


if __name__ == "__main__":
    try:
        main()
    except FixtureError as exc:
        print(f"fixturectl: {exc}", file=sys.stderr)
        raise SystemExit(1)
