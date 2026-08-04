#!/usr/bin/env python3
"""Create and verify run-scoped archives of functionally tested images."""

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys


SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COMMON_RELEASE_PATHS = {
    ".github/workflows/reusable-aggregate-image-contract.yml",
    ".github/workflows/reusable-build-debian-image.yml",
    ".github/workflows/reusable-prepare-image-matrix.yml",
    ".github/workflows/reusable-publish-image-manifest.yml",
    ".github/workflows/reusable-publish-tested-image.yml",
    "tests/functional/contractctl.rb",
    "tests/functional/releasectl.py",
    "tests/functional/scan_result.py",
}


class ReleaseArchiveError(ValueError):
    """Raised when a release archive or its metadata is invalid."""


def require(condition, message):
    if not condition:
        raise ReleaseArchiveError(message)


def require_exact_keys(value, expected, context):
    require(isinstance(value, dict), f"{context} must be an object")
    actual = set(value)
    expected = set(expected)
    require(
        actual == expected,
        f"{context} keys must be exactly {', '.join(sorted(expected))}",
    )


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def platform_parts(platform):
    parts = platform.split("/")
    require(len(parts) in (2, 3), f"invalid platform: {platform}")
    require(all(parts), f"invalid platform: {platform}")
    return parts[0], parts[1], parts[2] if len(parts) == 3 else None


def release_relevant_path(image_name, path):
    require(IMAGE_NAME_RE.fullmatch(image_name), f"invalid image name: {image_name}")
    if path in COMMON_RELEASE_PATHS:
        return True
    if path.startswith(f"images/{image_name}/"):
        return True
    if not path.startswith(".github/workflows/"):
        return False
    basename = pathlib.PurePosixPath(path).name
    return basename in {
        f"{image_name}-image.yml",
        f"{image_name}-images.yml",
        f"{image_name}-image-release.yml",
        f"{image_name}-images-release.yml",
    }


def expected_values(arguments):
    os_name, architecture, variant = platform_parts(arguments.platform)
    require(
        arguments.debian_arch == architecture,
        f"Debian architecture {arguments.debian_arch} does not match {arguments.platform}",
    )
    primary_tag = (
        f"{arguments.image_ref}:{arguments.image_version}-{arguments.debian_suite}"
    )
    return {
        "provenance": {
            "repository": arguments.repository,
            "commitSha": arguments.commit_sha,
            "runId": arguments.run_id,
            "runAttempt": arguments.run_attempt,
        },
        "image": {
            "name": arguments.image_name,
            "version": arguments.image_version,
            "debianSuite": arguments.debian_suite,
            "debianArch": arguments.debian_arch,
            "platform": arguments.platform,
            "ref": arguments.image_ref,
            "primaryTag": primary_tag,
            "architectureTag": f"{primary_tag}-{arguments.debian_arch}",
            "os": os_name,
            "architecture": architecture,
            "variant": variant,
        },
    }


def inspect_image(reference):
    completed = subprocess.run(
        ["docker", "image", "inspect", reference],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ReleaseArchiveError(
            f"docker image inspect failed for {reference}: {completed.stderr.strip()}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ReleaseArchiveError(
            f"docker image inspect returned invalid JSON for {reference}: {error}"
        ) from error
    require(
        isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict),
        f"docker image inspect must return exactly one image for {reference}",
    )
    image = payload[0]
    image_id = image.get("Id")
    require(isinstance(image_id, str) and SHA256_RE.fullmatch(image_id), "invalid image ID")
    os_name = image.get("Os")
    architecture = image.get("Architecture")
    variant = image.get("Variant") or None
    require(isinstance(os_name, str) and os_name, "image OS is missing")
    require(isinstance(architecture, str) and architecture, "image architecture is missing")
    require(variant is None or isinstance(variant, str), "image variant is invalid")
    return {
        "id": image_id,
        "os": os_name,
        "architecture": architecture,
        "variant": variant,
    }


def create_document(arguments, archive, inspected):
    expected = expected_values(arguments)
    require(inspected["os"] == expected["image"]["os"], "image OS mismatch")
    require(
        inspected["architecture"] == expected["image"]["architecture"],
        "image architecture mismatch",
    )
    if expected["image"]["variant"] is not None:
        require(inspected["variant"] == expected["image"]["variant"], "image variant mismatch")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "provenance": expected["provenance"],
        "image": {
            **expected["image"],
            "id": inspected["id"],
            "variant": inspected["variant"],
        },
        "archive": {
            "file": archive.name,
            "sha256": sha256_file(archive),
            "sizeBytes": archive.stat().st_size,
        },
    }


def validate_document(document, arguments, archive):
    require_exact_keys(
        document,
        {"schemaVersion", "provenance", "image", "archive"},
        "metadata",
    )
    require(document["schemaVersion"] == SCHEMA_VERSION, "unsupported schemaVersion")
    require_exact_keys(
        document["provenance"],
        {"repository", "commitSha", "runId", "runAttempt"},
        "metadata.provenance",
    )
    require_exact_keys(
        document["image"],
        {
            "name",
            "version",
            "debianSuite",
            "debianArch",
            "platform",
            "ref",
            "primaryTag",
            "architectureTag",
            "id",
            "os",
            "architecture",
            "variant",
        },
        "metadata.image",
    )
    require_exact_keys(
        document["archive"],
        {"file", "sha256", "sizeBytes"},
        "metadata.archive",
    )

    expected = expected_values(arguments)
    require(document["provenance"] == expected["provenance"], "release provenance mismatch")
    for key, value in expected["image"].items():
        if key == "variant" and value is None:
            continue
        require(document["image"].get(key) == value, f"metadata.image.{key} mismatch")

    image_id = document["image"].get("id")
    require(isinstance(image_id, str) and SHA256_RE.fullmatch(image_id), "invalid image ID")
    require(document["archive"]["file"] == archive.name, "archive file name mismatch")
    require(
        isinstance(document["archive"]["sizeBytes"], int)
        and document["archive"]["sizeBytes"] > 0,
        "invalid archive size",
    )
    require(archive.is_file(), f"release archive does not exist: {archive}")
    require(
        archive.stat().st_size == document["archive"]["sizeBytes"],
        "release archive size mismatch",
    )
    require(
        sha256_file(archive) == document["archive"]["sha256"],
        "release archive digest mismatch",
    )
    return document["image"]


def published_document(metadata, digest):
    require(isinstance(digest, str) and SHA256_RE.fullmatch(digest), "invalid published digest")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "provenance": dict(metadata["provenance"]),
        "image": dict(metadata["image"]),
        "archiveSha256": metadata["archive"]["sha256"],
        "publishedDigest": digest,
    }


def validate_published_documents(documents, arguments):
    arches = arguments.debian_arches.split()
    require(arches, "debian architectures must not be empty")
    require(len(arches) == len(set(arches)), "debian architectures must be unique")
    require(all(arch in ("amd64", "arm64") for arch in arches), "unsupported Debian architecture")
    require(set(documents) == set(arches), "published architecture record set mismatch")

    primary_tag = (
        f"{arguments.image_ref}:{arguments.image_version}-{arguments.debian_suite}"
    )
    expected_provenance = {
        "repository": arguments.repository,
        "commitSha": arguments.commit_sha,
        "runId": arguments.run_id,
        "runAttempt": arguments.run_attempt,
    }
    source_refs = []
    digests = set()
    for arch in arches:
        document = documents[arch]
        require_exact_keys(
            document,
            {
                "schemaVersion",
                "provenance",
                "image",
                "archiveSha256",
                "publishedDigest",
            },
            f"published record {arch}",
        )
        require(document["schemaVersion"] == SCHEMA_VERSION, "unsupported published record schemaVersion")
        require_exact_keys(
            document["provenance"],
            {"repository", "commitSha", "runId", "runAttempt"},
            f"published record {arch}.provenance",
        )
        require(document["provenance"] == expected_provenance, f"published record {arch} provenance mismatch")
        require_exact_keys(
            document["image"],
            {
                "name",
                "version",
                "debianSuite",
                "debianArch",
                "platform",
                "ref",
                "primaryTag",
                "architectureTag",
                "id",
                "os",
                "architecture",
                "variant",
            },
            f"published record {arch}.image",
        )
        expected_image = {
            "name": arguments.image_name,
            "version": arguments.image_version,
            "debianSuite": arguments.debian_suite,
            "debianArch": arch,
            "platform": f"linux/{arch}",
            "ref": arguments.image_ref,
            "primaryTag": primary_tag,
            "architectureTag": f"{primary_tag}-{arch}",
            "os": "linux",
            "architecture": arch,
        }
        for key, value in expected_image.items():
            require(document["image"].get(key) == value, f"published record {arch} image {key} mismatch")
        image_id = document["image"].get("id")
        require(isinstance(image_id, str) and SHA256_RE.fullmatch(image_id), f"published record {arch} image ID is invalid")
        variant = document["image"].get("variant")
        require(variant is None or isinstance(variant, str), f"published record {arch} variant is invalid")
        archive_digest = document["archiveSha256"]
        require(
            isinstance(archive_digest, str) and SHA256_RE.fullmatch(archive_digest),
            f"published record {arch} archive digest is invalid",
        )
        digest = document["publishedDigest"]
        require(
            isinstance(digest, str) and SHA256_RE.fullmatch(digest),
            f"published record {arch} registry digest is invalid",
        )
        require(digest not in digests, "published architecture digests must be unique")
        digests.add(digest)
        source_refs.append(f"{arguments.image_ref}@{digest}")
    return source_refs


def load_document(path):
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseArchiveError(f"cannot read release metadata {path}: {error}") from error
    return document


def write_document(path, document):
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def command_create(arguments):
    archive = pathlib.Path(arguments.archive)
    metadata = pathlib.Path(arguments.metadata)
    archive.parent.mkdir(parents=True, exist_ok=True)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    expected = expected_values(arguments)
    require(
        isinstance(arguments.expected_image_id, str)
        and SHA256_RE.fullmatch(arguments.expected_image_id),
        "invalid expected tested image ID",
    )
    primary = inspect_image(expected["image"]["primaryTag"])
    inspected = inspect_image(expected["image"]["architectureTag"])
    require(
        primary["id"] == arguments.expected_image_id,
        "primary tag no longer identifies the image used by tests",
    )
    require(
        inspected["id"] == arguments.expected_image_id,
        "architecture tag no longer identifies the image used by tests",
    )
    subprocess.run(
        [
            "docker",
            "image",
            "save",
            "--output",
            str(archive),
            expected["image"]["architectureTag"],
        ],
        check=True,
    )
    document = create_document(arguments, archive, inspected)
    write_document(metadata, document)
    print(
        f"Exported {document['image']['architectureTag']} "
        f"({document['image']['id']}) to {archive}"
    )


def append_github_output(path, image):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"image_ref={image['ref']}\n")
        stream.write(f"architecture_tag={image['architectureTag']}\n")
        stream.write(f"image_id={image['id']}\n")


def command_verify(arguments):
    archive = pathlib.Path(arguments.archive)
    metadata = pathlib.Path(arguments.metadata)
    image = validate_document(load_document(metadata), arguments, archive)
    subprocess.run(["docker", "image", "load", "--input", str(archive)], check=True)
    inspected = inspect_image(image["architectureTag"])
    require(inspected["id"] == image["id"], "loaded image ID does not match tested image ID")
    require(inspected["os"] == image["os"], "loaded image OS mismatch")
    require(inspected["architecture"] == image["architecture"], "loaded image architecture mismatch")
    require(inspected["variant"] == image["variant"], "loaded image variant mismatch")
    append_github_output(pathlib.Path(arguments.github_output), image)
    print(f"Verified tested image {image['architectureTag']} ({image['id']})")


def command_record(arguments):
    archive = pathlib.Path(arguments.archive)
    metadata_path = pathlib.Path(arguments.metadata)
    metadata = load_document(metadata_path)
    validate_document(metadata, arguments, archive)
    document = published_document(metadata, arguments.digest)
    output = pathlib.Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_document(output, document)
    print(
        f"Recorded {document['image']['architectureTag']}@"
        f"{document['publishedDigest']} in {output}"
    )


def command_manifest_sources(arguments):
    records = pathlib.Path(arguments.records)
    require(records.is_dir(), f"published record directory does not exist: {records}")
    paths = list(records.glob("*.json"))
    documents = {path.stem: load_document(path) for path in paths}
    require(len(documents) == len(paths), "duplicate published architecture record names")
    source_refs = validate_published_documents(documents, arguments)
    output = pathlib.Path(arguments.github_output)
    with output.open("a", encoding="utf-8") as stream:
        stream.write("source_refs<<DHI_RELEASE_REFS\n")
        for reference in source_refs:
            stream.write(f"{reference}\n")
        stream.write("DHI_RELEASE_REFS\n")
    print(f"Verified {len(source_refs)} immutable architecture digest records")


def command_guard_current(arguments):
    changed_files = pathlib.Path(arguments.changed_files)
    try:
        paths = [
            line.strip()
            for line in changed_files.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except OSError as error:
        raise ReleaseArchiveError(
            f"cannot read main-branch change list {changed_files}: {error}"
        ) from error
    relevant = [
        path for path in paths if release_relevant_path(arguments.image_name, path)
    ]
    require(
        not relevant,
        "refusing to publish because newer main changed release inputs: "
        + ", ".join(relevant),
    )
    print(
        f"No newer main commit changed release inputs for {arguments.image_name} "
        f"({len(paths)} paths checked)"
    )


def add_identity_arguments(parser):
    parser.add_argument("--image-name", required=True)
    parser.add_argument("--image-version", required=True)
    parser.add_argument("--debian-suite", required=True)
    parser.add_argument("--debian-arch", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="Export and describe a tested image")
    create.add_argument("--archive", required=True)
    create.add_argument("--metadata", required=True)
    create.add_argument("--expected-image-id", required=True)
    add_identity_arguments(create)
    create.set_defaults(handler=command_create)

    verify = commands.add_parser("verify", help="Verify and load a tested image archive")
    verify.add_argument("--archive", required=True)
    verify.add_argument("--metadata", required=True)
    verify.add_argument("--github-output", required=True)
    add_identity_arguments(verify)
    verify.set_defaults(handler=command_verify)

    record = commands.add_parser("record", help="Record a pushed tested-image digest")
    record.add_argument("--archive", required=True)
    record.add_argument("--metadata", required=True)
    record.add_argument("--output", required=True)
    record.add_argument("--digest", required=True)
    add_identity_arguments(record)
    record.set_defaults(handler=command_record)

    manifest = commands.add_parser(
        "manifest-sources", help="Verify immutable architecture digest records"
    )
    manifest.add_argument("--records", required=True)
    manifest.add_argument("--github-output", required=True)
    manifest.add_argument("--image-name", required=True)
    manifest.add_argument("--image-version", required=True)
    manifest.add_argument("--debian-suite", required=True)
    manifest.add_argument("--debian-arches", required=True)
    manifest.add_argument("--image-ref", required=True)
    manifest.add_argument("--repository", required=True)
    manifest.add_argument("--commit-sha", required=True)
    manifest.add_argument("--run-id", required=True)
    manifest.add_argument("--run-attempt", required=True)
    manifest.set_defaults(handler=command_manifest_sources)

    guard = commands.add_parser(
        "guard-current", help="Reject a release superseded by relevant main changes"
    )
    guard.add_argument("--image-name", required=True)
    guard.add_argument("--changed-files", required=True)
    guard.set_defaults(handler=command_guard_current)
    return root


def main(arguments=None):
    parsed = parser().parse_args(arguments)
    try:
        parsed.handler(parsed)
    except (ReleaseArchiveError, OSError, subprocess.CalledProcessError) as error:
        print(f"release archive error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
