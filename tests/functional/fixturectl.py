#!/usr/bin/env python3
"""Resolve and validate digest-pinned functional-test fixture images."""

import argparse
import json
import pathlib
import re
import subprocess
import sys
import time


ROOT = pathlib.Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "tests" / "functional" / "fixtures.lock.json"
TIMEOUT_PATH = ROOT / "tests" / "functional" / "timeout.py"
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
PLATFORM_PATTERN = re.compile(r"^linux/(amd64|arm64)(?:/[^/\s]+)?$")
PULL_ATTEMPTS = 3
PULL_TIMEOUT_SECONDS = 180
PULL_BACKOFF_SECONDS = 5


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


def pull_fixture(name, reference, platform):
    last_status = None
    for attempt in range(1, PULL_ATTEMPTS + 1):
        print(
            f"Pulling fixture {name} (attempt {attempt}/{PULL_ATTEMPTS})",
            file=sys.stderr,
            flush=True,
        )
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(TIMEOUT_PATH),
                    "--timeout",
                    str(PULL_TIMEOUT_SECONDS),
                    "--kill-after",
                    "5",
                    "--",
                    "docker",
                    "pull",
                    "--platform",
                    platform,
                    reference,
                ],
                check=False,
            )
        except OSError as exc:
            raise FixtureError(f"cannot execute fixture pull for {name}: {exc}") from exc
        last_status = completed.returncode
        if completed.returncode == 0:
            return
        if attempt < PULL_ATTEMPTS:
            delay = PULL_BACKOFF_SECONDS * attempt
            print(
                f"Fixture pull for {name} exited {completed.returncode}; "
                f"retrying in {delay}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)
    raise FixtureError(
        f"cannot pull fixture {name} after {PULL_ATTEMPTS} attempts "
        f"(last status {last_status}): {reference}"
    )


def command_pull(fixtures, names, platform):
    if len(names) != len(set(names)):
        raise FixtureError("fixture pull names must be unique")
    match = PLATFORM_PATTERN.fullmatch(platform)
    if not match:
        raise FixtureError(f"unsupported fixture pull platform: {platform}")
    base_platform = f"linux/{match.group(1)}"
    for name in names:
        try:
            reference = fixtures[name]["reference"]
        except KeyError:
            raise FixtureError(f"unknown fixture: {name}") from None
        if base_platform not in fixtures[name]["platforms"]:
            raise FixtureError(f"fixture {name} does not declare platform {platform}")
        pull_fixture(name, reference, platform)


def parse_args():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--online", action="store_true")
    resolve = commands.add_parser("resolve")
    resolve.add_argument("name")
    pull = commands.add_parser("pull")
    pull.add_argument("--platform", required=True)
    pull.add_argument("names", nargs="+")
    return parser.parse_args()


def main():
    args = parse_args()
    fixtures = load_lock()
    if args.command == "validate":
        command_validate(fixtures, args.online)
    elif args.command == "resolve":
        try:
            print(fixtures[args.name]["reference"])
        except KeyError:
            raise FixtureError(f"unknown fixture: {args.name}")
    else:
        command_pull(fixtures, args.names, args.platform)


if __name__ == "__main__":
    try:
        main()
    except FixtureError as exc:
        print(f"fixturectl: {exc}", file=sys.stderr)
        raise SystemExit(1)
