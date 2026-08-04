#!/usr/bin/env python3
"""Fail closed when a Trivy report does not prove an OS package scan."""

import argparse
import json
import pathlib
import re
import sys


class ScanResultError(ValueError):
    """Raised when a vulnerability report lacks required scan evidence."""


def require(condition, message):
    if not condition:
        raise ScanResultError(message)


def parse_expected_packages(value):
    return {item for item in re.split(r"[\s,]+", value.strip()) if item}


def validate_report(
    report,
    expected_family,
    expected_artifact_name,
    expected_image_id,
    expected_packages=None,
):
    require(isinstance(report, dict), "Trivy report must be an object")
    schema_version = report.get("SchemaVersion")
    require(
        schema_version == 2,
        "Trivy report SchemaVersion must be exactly 2",
    )
    require(
        report.get("ArtifactType") == "container_image",
        "Trivy report must describe a container image",
    )
    require(
        report.get("ArtifactName") == expected_artifact_name,
        "Trivy report ArtifactName does not match the tested image; "
        f"actual={report.get('ArtifactName')!r} expected={expected_artifact_name!r}",
    )

    metadata = report.get("Metadata")
    require(isinstance(metadata, dict), "Trivy report Metadata must be an object")
    require(
        metadata.get("ImageID") == expected_image_id,
        "Trivy report ImageID does not match the tested image; "
        f"actual={metadata.get('ImageID')!r} expected={expected_image_id!r}",
    )
    os_metadata = metadata.get("OS")
    require(isinstance(os_metadata, dict), "Trivy report is missing OS metadata")
    os_family = os_metadata.get("Family")
    os_version = os_metadata.get("Name")
    require(
        os_family == expected_family,
        f"Trivy detected OS family {os_family!r}, expected {expected_family!r}",
    )
    require(
        isinstance(os_version, str) and os_version.strip(),
        "Trivy detected an empty OS version",
    )

    results = report.get("Results")
    require(isinstance(results, list), "Trivy report Results must be an array")
    os_results = [
        result
        for result in results
        if isinstance(result, dict)
        and result.get("Class") == "os-pkgs"
        and result.get("Type") == expected_family
    ]
    require(os_results, "Trivy report has no OS package result")

    package_names = set()
    for result in os_results:
        packages = result.get("Packages")
        require(
            isinstance(packages, list) and packages,
            "Trivy OS package result has no package inventory",
        )
        for package in packages:
            require(isinstance(package, dict), "Trivy package entry must be an object")
            package_name = package.get("Name")
            require(
                isinstance(package_name, str)
                and package_name.strip()
                and package_name == package_name.strip(),
                "Trivy package entry has an invalid Name",
            )
            package_version = package.get("Version")
            require(
                isinstance(package_version, str) and package_version.strip(),
                "Trivy package entry is missing Version",
            )
            package_names.add(package_name)

    expected_packages = set(expected_packages or ())
    if expected_packages:
        missing = expected_packages - package_names
        unexpected = package_names - expected_packages
        require(
            not missing and not unexpected,
            "Trivy package inventory differs from the runtime allowlist; "
            f"missing={','.join(sorted(missing)) or '-'} "
            f"unexpected={','.join(sorted(unexpected)) or '-'}",
        )

    return {
        "trivySchemaVersion": schema_version,
        "status": "pass",
        "artifactName": expected_artifact_name,
        "imageId": expected_image_id,
        "osFamily": os_family,
        "osVersion": os_version,
        "osResultCount": len(os_results),
        "packageCount": len(package_names),
    }


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=pathlib.Path, required=True)
    parser.add_argument("--expected-family", required=True)
    parser.add_argument("--expected-artifact-name", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--expected-packages", default="")
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    try:
        report = json.loads(arguments.report.read_text(encoding="utf-8"))
        summary = validate_report(
            report,
            arguments.expected_family,
            arguments.expected_artifact_name,
            arguments.expected_image_id,
            parse_expected_packages(arguments.expected_packages),
        )
    except (OSError, json.JSONDecodeError, ScanResultError) as exc:
        print(f"scan_result: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
