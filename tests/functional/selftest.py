#!/usr/bin/env python3
"""Fast, daemon-free negative tests for the functional contract control plane."""

import copy
import io
import json
import pathlib
import re
import subprocess
import tempfile
import types
import unittest
from unittest import mock

import fixturectl
import releasectl
import result as contract_result
import scan_result


IMAGE_ID = "sha256:" + ("a" * 64)


def discover_runtime_closure_workflows(workflow_dir):
    discovered = {}
    workflow_paths = sorted(
        set(workflow_dir.glob("*.yml")) | set(workflow_dir.glob("*.yaml"))
    )
    for path in workflow_paths:
        workflow = path.read_text(encoding="utf-8")
        for line in workflow.splitlines():
            match = re.match(r"^\s*runtime_closure:\s*(.*?)\s*$", line)
            if not match or not match.group(1):
                continue
            if match.group(1) != "true":
                raise AssertionError(
                    f"{path.name}: runtime_closure must be the literal true"
                )
            discovered[path.name] = workflow
    return discovered


def passing_result():
    return {
        "schemaVersion": 1,
        "legId": "redis:7.0:linux/amd64",
        "run": {
            "id": "selftest",
            "project": "dhi-selftest",
            "startedAt": "2026-08-03T00:00:00Z",
            "finishedAt": "2026-08-03T00:00:01Z",
            "durationMs": 1000,
            "timeoutSeconds": 600,
            "buildTimeoutSeconds": 600,
        },
        "contract": {
            "family": "redis",
            "version": "7.0",
            "platform": "linux/amd64",
            "suite": "tests/functional/redis",
            "sutService": "app",
            "testService": "test",
        },
        "image": {
            "requestedRef": "local/redis:test",
            "sourceAlias": "localhost/dhi-functional-source/redis:selftest",
            "expectedId": IMAGE_ID,
            "containerImageId": IMAGE_ID,
            "os": "linux",
            "architecture": "amd64",
            "variant": None,
            "identity": {
                "mode": "exact-container-image",
                "verified": True,
                "sourceLayerCount": 1,
                "containerLayerCount": 1,
                "message": "verified",
            },
        },
        "outcome": {
            "status": "pass",
            "classification": "pass",
            "phase": "complete",
            "exitCode": 0,
            "rawExitCode": 0,
            "message": "passed",
        },
        "services": [
            {
                "name": "app",
                "role": "sut",
                "containerId": "sut-container",
                "containerName": "/dhi-selftest-app-1",
                "image": "local/redis:test",
                "imageId": IMAGE_ID,
                "state": "exited",
                "health": None,
                "exitCode": 0,
                "oomKilled": False,
            },
            {
                "name": "test",
                "role": "test",
                "containerId": "test-container",
                "containerName": "/dhi-selftest-test-1",
                "image": "local/harness:test",
                "imageId": "sha256:" + ("b" * 64),
                "state": "exited",
                "health": None,
                "exitCode": 0,
                "oomKilled": False,
            },
        ],
        "cleanup": {"status": "success", "residualResources": []},
        "evidence": dict(contract_result.EVIDENCE_PATHS),
        "secondaryFailures": [],
        "warnings": [],
    }


def passing_scan_report():
    return {
        "SchemaVersion": 2,
        "ArtifactName": "local/redis:test",
        "ArtifactType": "container_image",
        "Metadata": {
            "OS": {"Family": "debian", "Name": "12.11"},
            "ImageID": IMAGE_ID,
        },
        "Results": [
            {
                "Target": "local/redis:test (debian 12.11)",
                "Class": "os-pkgs",
                "Type": "debian",
                "Packages": [
                    {"Name": "base-files", "Version": "12.4+deb12u11"},
                    {"Name": "redis-server", "Version": "5:7.0.15-1"},
                ],
                "Vulnerabilities": None,
            }
        ],
    }


def create_evidence(root):
    for relative_path in contract_result.EVIDENCE_PATHS.values():
        path = root / relative_path
        if relative_path == "containers":
            path.mkdir(parents=True)
        else:
            path.write_text("selftest\n", encoding="utf-8")

    identity = passing_result()["image"]["identity"]
    (root / "identity.json").write_text(
        json.dumps(identity), encoding="utf-8"
    )
    source_image = {
        "Id": IMAGE_ID,
        "Os": "linux",
        "Architecture": "amd64",
        "RootFS": {"Layers": ["sha256:source-layer"]},
        "Config": {"Labels": {}},
    }
    (root / "source-image.inspect.json").write_text(
        json.dumps([source_image]), encoding="utf-8"
    )
    (root / "sut-image.inspect.json").write_text(
        json.dumps([source_image]), encoding="utf-8"
    )
    app_inspect = {
        "Id": "sut-container",
        "Name": "/dhi-selftest-app-1",
        "Image": IMAGE_ID,
        "State": {"Status": "exited", "ExitCode": 0, "OOMKilled": False},
    }
    test_inspect = {
        "Id": "test-container",
        "Name": "/dhi-selftest-test-1",
        "Image": "sha256:" + ("b" * 64),
        "State": {"Status": "exited", "ExitCode": 0, "OOMKilled": False},
    }
    (root / "containers" / "app.json").write_text(
        json.dumps([app_inspect]), encoding="utf-8"
    )
    (root / "containers" / "test.json").write_text(
        json.dumps([test_inspect]), encoding="utf-8"
    )
    compose_ps = [
        {
            "Service": "app",
            "ID": "sut-container",
            "Name": "dhi-selftest-app-1",
            "Image": "local/redis:test",
            "State": "exited",
            "ExitCode": 0,
        },
        {
            "Service": "test",
            "ID": "test-container",
            "Name": "dhi-selftest-test-1",
            "Image": "local/harness:test",
            "State": "exited",
            "ExitCode": 0,
        },
    ]
    (root / "compose-ps.json").write_text(
        json.dumps(compose_ps), encoding="utf-8"
    )
    source_alias = passing_result()["image"]["sourceAlias"]
    compose_config = {
        "services": {
            "app": {
                "image": source_alias,
                "platform": "linux/amd64",
                "pull_policy": "never",
                "labels": {
                    "io.pesla.dhi.functional.role": "sut",
                    "io.pesla.dhi.functional.identity-mode": "exact-container-image",
                },
            },
            "test": {
                "image": "local/harness:test",
                "pull_policy": "never",
                "labels": {"io.pesla.dhi.functional.role": "test"},
            },
        }
    }
    (root / "compose-config.json").write_text(
        json.dumps(compose_config), encoding="utf-8"
    )
    lock_path = pathlib.Path(__file__).with_name("fixtures.lock.json")
    (root / "fixtures.lock.json").write_text(
        lock_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    fixture_count = len(json.loads(lock_path.read_text(encoding="utf-8"))["fixtures"])
    (root / "fixture-validation.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "fixtures": fixture_count,
                "online": False,
                "status": "pass",
            }
        ),
        encoding="utf-8",
    )


class ResultContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name)
        create_evidence(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_canonical_pass_is_accepted(self):
        contract_result.validate_result(passing_result(), self.root)

    def test_fabricated_passes_are_rejected(self):
        mutations = {
            "missing run fields": lambda value: value.__setitem__("run", {}),
            "assertion exit": lambda value: value["services"][1].__setitem__(
                "exitCode", 10
            ),
            "oom killed": lambda value: value["services"][0].__setitem__(
                "oomKilled", True
            ),
            "swapped role": lambda value: value["services"][0].__setitem__(
                "role", "test"
            ),
            "wrong exact image": lambda value: value["image"].__setitem__(
                "containerImageId", "sha256:" + ("c" * 64)
            ),
            "missing evidence": lambda value: value["evidence"].pop(
                "identityProof"
            ),
            "aliased evidence": lambda value: value["evidence"].__setitem__(
                "identityProof", "compose.log"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                value = copy.deepcopy(passing_result())
                mutate(value)
                with self.assertRaises(ValueError):
                    contract_result.validate_result(value, self.root)

    def test_schema_and_validator_evidence_keys_match(self):
        schema_path = pathlib.Path(__file__).with_name("result.schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        evidence_schema = schema["properties"]["evidence"]
        schema_keys = set(evidence_schema["properties"])
        self.assertEqual(schema_keys, set(contract_result.EVIDENCE_PATHS))
        for key, relative_path in contract_result.EVIDENCE_PATHS.items():
            self.assertEqual(
                evidence_schema["properties"][key], {"const": relative_path}
            )
        pass_evidence = set(
            schema["allOf"][0]["then"]["properties"]["evidence"]["required"]
        )
        self.assertEqual(pass_evidence, contract_result.PASS_EVIDENCE)

    def test_empty_evidence_directory_is_rejected(self):
        (self.root / "containers" / "app.json").unlink()
        (self.root / "containers" / "test.json").unlink()
        with self.assertRaises(ValueError):
            contract_result.validate_result(passing_result(), self.root)

    def test_structured_evidence_is_cross_bound(self):
        mutations = {
            "identity": (self.root / "identity.json", {"verified": True}),
            "source inspect": (self.root / "source-image.inspect.json", {}),
            "compose state": (self.root / "compose-ps.json", []),
            "fixture validation": (
                self.root / "fixture-validation.json",
                {"schemaVersion": 1, "fixtures": 6, "online": False, "status": "fail"},
            ),
        }
        for name, (path, replacement) in mutations.items():
            with self.subTest(name=name):
                original = path.read_text(encoding="utf-8")
                path.write_text(json.dumps(replacement), encoding="utf-8")
                try:
                    with self.assertRaises((ValueError, json.JSONDecodeError)):
                        contract_result.validate_result(passing_result(), self.root)
                finally:
                    path.write_text(original, encoding="utf-8")

    def test_invalid_pass_evidence_emits_terminal_failure(self):
        identity = passing_result()["image"]["identity"]
        (self.root / "identity.json").write_text(
            json.dumps(identity), encoding="utf-8"
        )
        services = passing_result()["services"]
        services[0]["oomKilled"] = True
        environment = {
            "DHI_RESULT_ARTIFACT_DIR": str(self.root),
            "DHI_RESULT_LEG_ID": "redis:7.0:linux/amd64",
            "DHI_RESULT_RUN_ID": "selftest",
            "DHI_RESULT_PROJECT": "dhi-selftest",
            "DHI_RESULT_STARTED_AT": "2026-08-03T00:00:00Z",
            "DHI_RESULT_FINISHED_AT": "2026-08-03T00:00:01Z",
            "DHI_RESULT_DURATION_MS": "1000",
            "DHI_RESULT_TIMEOUT_SECONDS": "600",
            "DHI_RESULT_BUILD_TIMEOUT_SECONDS": "600",
            "DHI_RESULT_FAMILY": "redis",
            "DHI_RESULT_VERSION": "7.0",
            "DHI_RESULT_PLATFORM": "linux/amd64",
            "DHI_RESULT_SUITE": "tests/functional/redis",
            "DHI_RESULT_SUT_SERVICE": "app",
            "DHI_RESULT_TEST_SERVICE": "test",
            "DHI_RESULT_REQUESTED_REF": "local/redis:test",
            "DHI_RESULT_SOURCE_ALIAS": "localhost/dhi-functional-source/redis:selftest",
            "DHI_RESULT_EXPECTED_ID": IMAGE_ID,
            "DHI_RESULT_CONTAINER_IMAGE_ID": IMAGE_ID,
            "DHI_RESULT_IMAGE_OS": "linux",
            "DHI_RESULT_IMAGE_ARCH": "amd64",
            "DHI_RESULT_IMAGE_VARIANT": "",
            "DHI_RESULT_IDENTITY_MODE": "exact-container-image",
            "DHI_RESULT_STATUS": "pass",
            "DHI_RESULT_CLASSIFICATION": "pass",
            "DHI_RESULT_PHASE": "complete",
            "DHI_RESULT_EXIT_CODE": "0",
            "DHI_RESULT_RAW_EXIT_CODE": "0",
            "DHI_RESULT_MESSAGE": "passed",
            "DHI_RESULT_CLEANUP_STATUS": "success",
        }
        output = self.root / "result.json"
        with mock.patch.dict("os.environ", environment, clear=True), mock.patch.object(
            contract_result, "service_results", return_value=services
        ), mock.patch("sys.stderr", io.StringIO()):
            status = contract_result.command_emit(
                types.SimpleNamespace(output=str(output))
            )

        self.assertEqual(status, 15)
        emitted = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(emitted["outcome"]["classification"], "evidence_cleanup_failure")
        self.assertEqual(emitted["outcome"]["exitCode"], 15)
        self.assertTrue(emitted["secondaryFailures"])
        contract_result.validate_result(emitted, self.root)


class ScanResultTests(unittest.TestCase):
    def test_os_package_scan_evidence_is_accepted(self):
        summary = scan_result.validate_report(
            passing_scan_report(),
            "debian",
            "local/redis:test",
            IMAGE_ID,
            {"base-files", "redis-server"},
        )
        self.assertEqual(summary["status"], "pass")
        self.assertEqual(summary["trivySchemaVersion"], 2)
        self.assertEqual(summary["osFamily"], "debian")
        self.assertEqual(summary["packageCount"], 2)

    def test_false_green_scan_reports_are_rejected(self):
        mutations = {
            "old schema": lambda value: value.__setitem__("SchemaVersion", 1),
            "future schema": lambda value: value.__setitem__("SchemaVersion", 3),
            "wrong artifact type": lambda value: value.__setitem__(
                "ArtifactType", "filesystem"
            ),
            "missing metadata": lambda value: value.pop("Metadata"),
            "missing OS metadata": lambda value: value["Metadata"].pop("OS"),
            "unsupported OS": lambda value: value["Metadata"]["OS"].__setitem__(
                "Family", "none"
            ),
            "empty OS version": lambda value: value["Metadata"]["OS"].__setitem__(
                "Name", ""
            ),
            "no OS result": lambda value: value.__setitem__("Results", []),
            "language result only": lambda value: value["Results"][0].__setitem__(
                "Class", "lang-pkgs"
            ),
            "wrong OS result type": lambda value: value["Results"][0].__setitem__(
                "Type", "ubuntu"
            ),
            "no packages": lambda value: value["Results"][0].__setitem__(
                "Packages", []
            ),
            "package without name": lambda value: value["Results"][0][
                "Packages"
            ][0].pop("Name"),
            "package with whitespace name": lambda value: value["Results"][0][
                "Packages"
            ][0].__setitem__("Name", "   "),
            "package without version": lambda value: value["Results"][0][
                "Packages"
            ][0].pop("Version"),
            "package with whitespace version": lambda value: value["Results"][0][
                "Packages"
            ][0].__setitem__("Version", "   "),
            "wrong artifact": lambda value: value.__setitem__(
                "ArtifactName", "local/other:test"
            ),
            "wrong image ID": lambda value: value["Metadata"].__setitem__(
                "ImageID", "sha256:" + ("b" * 64)
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                value = copy.deepcopy(passing_scan_report())
                mutate(value)
                with self.assertRaises(scan_result.ScanResultError):
                    scan_result.validate_report(
                        value,
                        "debian",
                        "local/redis:test",
                        IMAGE_ID,
                    )

    def test_expected_package_separators_are_normalized(self):
        self.assertEqual(
            scan_result.parse_expected_packages(
                "base-files,,redis-server\n redis-tools"
            ),
            {"base-files", "redis-server", "redis-tools"},
        )

    def test_runtime_package_inventory_must_match(self):
        with self.assertRaisesRegex(
            scan_result.ScanResultError,
            "missing=redis-tools.*unexpected=redis-server",
        ):
            scan_result.validate_report(
                passing_scan_report(),
                "debian",
                "local/redis:test",
                IMAGE_ID,
                {"base-files", "redis-tools"},
            )

    def test_scan_result_cli_rejects_missing_or_malformed_reports(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            malformed = temporary / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            reports = (temporary / "missing.json", malformed)
            for report in reports:
                with self.subTest(report=report.name):
                    completed = subprocess.run(
                        [
                            "python3",
                            "tests/functional/scan_result.py",
                            "--report",
                            str(report),
                            "--expected-family",
                            "debian",
                            "--expected-artifact-name",
                            "local/redis:test",
                            "--expected-image-id",
                            IMAGE_ID,
                        ],
                        cwd=root,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 1)
                    self.assertIn("scan_result:", completed.stderr)


class FixtureLockTests(unittest.TestCase):
    def test_lock_is_strict_and_digest_pinned(self):
        fixtures = fixturectl.load_lock()
        self.assertEqual(set(fixtures), fixturectl.EXPECTED_FIXTURES)


class PlannerTests(unittest.TestCase):
    def test_selected_families_cannot_hide_expected_legs(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            results = temporary / "results"
            results.mkdir()
            plan = temporary / "plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "selectedFamilies": ["redis"],
                        "expectedLegIds": [],
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    "ruby",
                    "tests/functional/contractctl.rb",
                    "aggregate",
                    "--results",
                    str(results),
                    "--plan",
                    str(plan),
                ],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("does not match selectedFamilies", completed.stderr)


class ReleaseArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name)
        self.archive = self.root / "image.tar"
        self.archive.write_bytes(b"tested-image-archive")
        self.arguments = types.SimpleNamespace(
            image_name="redis",
            image_version="7.0",
            debian_suite="trixie",
            debian_arch="amd64",
            platform="linux/amd64",
            image_ref="ghcr.io/peslaio/redis",
            repository="peslaio/dhi",
            commit_sha="1" * 40,
            run_id="1234",
            run_attempt="1",
        )
        self.inspected = {
            "id": IMAGE_ID,
            "os": "linux",
            "architecture": "amd64",
            "variant": None,
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_metadata_binds_exact_tested_archive_and_provenance(self):
        document = releasectl.create_document(
            self.arguments, self.archive, self.inspected
        )
        image = releasectl.validate_document(
            document, self.arguments, self.archive
        )
        self.assertEqual(image["id"], IMAGE_ID)
        self.assertEqual(
            image["architectureTag"], "ghcr.io/peslaio/redis:7.0-trixie-amd64"
        )

    def test_tampered_archive_or_provenance_is_rejected(self):
        document = releasectl.create_document(
            self.arguments, self.archive, self.inspected
        )
        self.archive.write_bytes(b"different-image")
        with self.assertRaises(releasectl.ReleaseArchiveError):
            releasectl.validate_document(document, self.arguments, self.archive)

        self.archive.write_bytes(b"tested-image-archive")
        document = releasectl.create_document(
            self.arguments, self.archive, self.inspected
        )
        document["provenance"]["runId"] = "different-run"
        with self.assertRaises(releasectl.ReleaseArchiveError):
            releasectl.validate_document(document, self.arguments, self.archive)

    def test_export_refuses_a_tag_that_no_longer_matches_tested_id(self):
        arguments = copy.copy(self.arguments)
        arguments.archive = str(self.root / "export.tar")
        arguments.metadata = str(self.root / "release-image.json")
        arguments.expected_image_id = IMAGE_ID
        replacement = dict(self.inspected)
        replacement["id"] = "sha256:" + ("c" * 64)
        with mock.patch.object(
            releasectl,
            "inspect_image",
            side_effect=[self.inspected, replacement],
        ), mock.patch.object(releasectl.subprocess, "run") as run:
            with self.assertRaises(releasectl.ReleaseArchiveError):
                releasectl.command_create(arguments)
        run.assert_not_called()

    def published_records(self):
        records = {}
        for arch, marker in (("amd64", "d"), ("arm64", "e")):
            arguments = copy.copy(self.arguments)
            arguments.debian_arch = arch
            arguments.platform = f"linux/{arch}"
            inspected = dict(self.inspected)
            inspected["id"] = "sha256:" + (marker * 64)
            inspected["architecture"] = arch
            metadata = releasectl.create_document(arguments, self.archive, inspected)
            records[arch] = releasectl.published_document(
                metadata, "sha256:" + (marker * 64)
            )
        return records

    def manifest_arguments(self):
        return types.SimpleNamespace(
            image_name=self.arguments.image_name,
            image_version=self.arguments.image_version,
            debian_suite=self.arguments.debian_suite,
            debian_arches="amd64 arm64",
            image_ref=self.arguments.image_ref,
            repository=self.arguments.repository,
            commit_sha=self.arguments.commit_sha,
            run_id=self.arguments.run_id,
            run_attempt=self.arguments.run_attempt,
        )

    def test_published_records_produce_ordered_immutable_sources(self):
        sources = releasectl.validate_published_documents(
            self.published_records(), self.manifest_arguments()
        )
        self.assertEqual(
            sources,
            [
                "ghcr.io/peslaio/redis@sha256:" + ("d" * 64),
                "ghcr.io/peslaio/redis@sha256:" + ("e" * 64),
            ],
        )

    def test_invalid_published_record_sets_are_rejected(self):
        mutations = {
            "missing architecture": lambda value: value.pop("arm64"),
            "extra architecture": lambda value: value.__setitem__(
                "s390x", copy.deepcopy(value["amd64"])
            ),
            "wrong provenance": lambda value: value["amd64"]["provenance"].__setitem__(
                "runAttempt", "2"
            ),
            "malformed digest": lambda value: value["amd64"].__setitem__(
                "publishedDigest", "latest"
            ),
            "duplicate digest": lambda value: value["arm64"].__setitem__(
                "publishedDigest", value["amd64"]["publishedDigest"]
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                records = self.published_records()
                mutate(records)
                with self.assertRaises(releasectl.ReleaseArchiveError):
                    releasectl.validate_published_documents(
                        records, self.manifest_arguments()
                    )

    def test_release_freshness_matches_family_and_common_inputs(self):
        selected = {
            ".github/workflows/redis-image.yml",
            ".github/workflows/redis-image-release.yml",
            ".github/workflows/reusable-build-debian-image.yml",
            "images/redis/7.0/image.yaml",
            "tests/functional/releasectl.py",
        }
        ignored = {
            "README.md",
            ".github/workflows/apache-image.yml",
            "images/apache/2.4/image.yaml",
            "tests/functional/redis/compose.yaml",
        }
        for path in selected:
            with self.subTest(selected=path):
                self.assertTrue(releasectl.release_relevant_path("redis", path))
        for path in ignored:
            with self.subTest(ignored=path):
                self.assertFalse(releasectl.release_relevant_path("redis", path))


class WorkflowPolicyTests(unittest.TestCase):
    CORE_WORKFLOWS = {
        "apache-image.yml",
        "caddy-image.yml",
        "dotnet-aspnet-images.yml",
        "dotnet-runtime-images.yml",
        "haproxy-image.yml",
        "java-jre-image.yml",
        "mariadb-image.yml",
        "memcached-image.yml",
        "mongodb-image.yml",
        "nginx-image.yml",
        "node-image.yml",
        "php-fpm-image.yml",
        "postgresql-image.yml",
        "python-image.yml",
        "rabbitmq-image.yml",
        "redis-image.yml",
    }

    PUBLISHER_WORKFLOWS = {
        "reusable-publish-image-manifest.yml",
        "reusable-publish-tested-image.yml",
    }

    def test_runtime_closure_patterns_are_expanded_only_inside_the_rootfs(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        build_workflow = (
            workflow_dir / "reusable-build-debian-image.yml"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            "for binary_pattern in $RUNTIME_CLOSURE_BINARIES",
            build_workflow,
        )
        self.assertNotIn(
            "for closure_path in $RUNTIME_CLOSURE_PATHS",
            build_workflow,
        )
        self.assertIn(
            'compgen -G "${rootfs}${binary_pattern}"',
            build_workflow,
        )
        self.assertIn(
            'compgen -G "${rootfs}${closure_path}"',
            build_workflow,
        )
        self.assertIn(
            'readlink -f "$path"',
            build_workflow,
        )
        self.assertIn("runtime_remove_paths:", build_workflow)
        self.assertIn(
            'resolved_remove_target="$(realpath -m "$runtime_remove_target")"',
            build_workflow,
        )
        self.assertIn('"$final_rootfs"/*)', build_workflow)
        self.assertIn("Runtime removal path does not exist", build_workflow)
        rabbitmq_workflow = (
            workflow_dir / "rabbitmq-image.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "runtime_remove_paths: /var/lib/rabbitmq/.erlang.cookie",
            rabbitmq_workflow,
        )
        self.assertIn(
            'cmd: \'["/usr/lib/rabbitmq/bin/rabbitmq-server"]\'',
            rabbitmq_workflow,
        )
        self.assertIn("smoke_tcp_port: \"5672\"", rabbitmq_workflow)
        self.assertIn(
            "smoke_startup_timeout_seconds: \"120\"",
            rabbitmq_workflow,
        )
        self.assertNotIn('exposed_ports: "5672 15672"', rabbitmq_workflow)

    def test_running_smoke_command_retry_is_deadline_bounded(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        build_workflow = (
            workflow_dir / "reusable-build-debian-image.yml"
        ).read_text(encoding="utf-8")
        running_retry = build_workflow.rsplit(
            'if [ -n "$SMOKE_COMMAND" ]; then', 1
        )[1]

        self.assertIn("smoke_command_deadline=", running_retry)
        self.assertIn(
            'timeout --signal=KILL "$smoke_command_attempt_timeout"',
            running_retry,
        )
        self.assertIn(
            'grep -q "$SMOKE_EXPECTED_OUTPUT" /tmp/dif-smoke-output',
            running_retry,
        )
        self.assertIn(
            'smoke_container_status="$(docker inspect',
            running_retry,
        )
        self.assertIn("Smoke command did not become ready", running_retry)
        self.assertIn(
            "smoke_startup_timeout_seconds must be a positive integer",
            build_workflow,
        )

        rabbitmq_workflow = (
            workflow_dir / "rabbitmq-image.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "smoke_command: /usr/sbin/rabbitmq-diagnostics -q ping --timeout 5",
            rabbitmq_workflow,
        )

    def test_vulnerability_scans_are_coverage_gated(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        build_workflow = (
            workflow_dir / "reusable-build-debian-image.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("/etc/debian_version", build_workflow)
        self.assertIn("/etc/os-release", build_workflow)
        self.assertIn(
            "Runtime closure is missing a readable Debian OS identity",
            build_workflow,
        )
        self.assertIn("Runtime closure package database is empty", build_workflow)
        for post_removal_check in (
            "Runtime closure is missing a readable Debian OS identity",
            "Runtime closure package database is empty",
        ):
            with self.subTest(post_removal_check=post_removal_check):
                self.assertGreater(
                    build_workflow.index(post_removal_check),
                    build_workflow.index('sudo rm -rf -- "$runtime_remove_target"'),
                )
        self.assertIn("format: json", build_workflow)
        self.assertIn("output: artifacts/security/trivy-report.json", build_workflow)
        self.assertIn("list-all-pkgs: true", build_workflow)
        self.assertIn("tests/functional/scan_result.py", build_workflow)

        input_policy_step = build_workflow.split(
            "\n      - name: Validate build policy inputs\n", 1
        )[1].split("\n      - name: Install rootfs build dependencies\n", 1)[0]
        functional_upload_step = build_workflow.split(
            "\n      - name: Upload functional contract evidence\n", 1
        )[1].split("\n      - name: Enforce functional application contract\n", 1)[0]
        scan_step = build_workflow.split(
            "\n      - name: Scan image\n", 1
        )[1].split("\n      - name: Validate vulnerability scan coverage\n", 1)[0]
        coverage_step = build_workflow.split(
            "\n      - name: Validate vulnerability scan coverage\n", 1
        )[1].split("\n      - name: Upload vulnerability scan evidence\n", 1)[0]
        upload_step = build_workflow.split(
            "\n      - name: Upload vulnerability scan evidence\n", 1
        )[1].split("\n      - name: Enforce vulnerability scan\n", 1)[0]
        enforcement_step = build_workflow.split(
            "\n      - name: Enforce vulnerability scan\n", 1
        )[1].split("\n      - name: Export fully tested image for release\n", 1)[0]
        export_step = build_workflow.split(
            "\n      - name: Export fully tested image for release\n", 1
        )[1].split("\n      - name:", 1)[0]

        self.assertIn(
            "runtime_closure=true requires a non-empty allowed_packages inventory",
            input_policy_step,
        )
        self.assertIn('if [ "$EXPORT_IMAGE" = "true" ]', input_policy_step)
        for required_gate in (
            "functional_test",
            "generate_sbom",
            "scan",
            "fail_on_vulnerabilities",
        ):
            with self.subTest(release_gate=required_gate):
                self.assertIn(
                    f"missing_release_gates+=({required_gate})",
                    input_policy_step,
                )
        self.assertIn(
            "if: ${{ always() && inputs.functional_test && "
            "(steps.functional.outcome == 'success' || "
            "hashFiles('artifacts/functional/**') != '') }}",
            functional_upload_step,
        )
        self.assertIn("if-no-files-found: error", functional_upload_step)

        self.assertIn("id: vulnerability-scan", scan_step)
        self.assertIn("if: inputs.scan", scan_step)
        self.assertIn("continue-on-error: true", scan_step)
        self.assertIn("id: vulnerability-coverage", coverage_step)
        self.assertIn("if: ${{ always() && inputs.scan }}", coverage_step)
        self.assertIn("continue-on-error: true", coverage_step)
        self.assertIn('--expected-artifact-name "$PRIMARY_TAG"', coverage_step)
        self.assertIn('--expected-image-id "$TESTED_IMAGE_ID"', coverage_step)
        self.assertIn(
            "if: ${{ always() && inputs.scan && "
            "(steps.vulnerability-coverage.outcome == 'success' || "
            "hashFiles('artifacts/security/trivy-report.json') != '') }}",
            upload_step,
        )
        self.assertIn("if-no-files-found: error", upload_step)
        self.assertIn("if: ${{ always() && inputs.scan }}", enforcement_step)
        self.assertIn(
            "steps.vulnerability-scan.outcome", enforcement_step
        )
        self.assertIn(
            "steps.vulnerability-coverage.outcome", enforcement_step
        )
        self.assertIn(
            "Vulnerability scan coverage outcome: $COVERAGE_OUTCOME",
            enforcement_step,
        )
        self.assertIn("if: inputs.export_image", export_step)
        self.assertNotIn("always()", export_step)
        self.assertNotIn("continue-on-error", export_step)

        closure_workflows = discover_runtime_closure_workflows(workflow_dir)
        self.assertTrue(closure_workflows)
        for workflow_name, workflow in closure_workflows.items():
            with self.subTest(workflow=workflow_name):
                allowed_packages = next(
                    line.partition(":")[2].strip().split(",")
                    for line in workflow.splitlines()
                    if line.strip().startswith("allowed_packages:")
                )
                self.assertIn("base-files", allowed_packages)

    def test_closure_allowlists_match_package_inventory(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        inventory_lines = (
            (root / "docs" / "package-inventory.md")
            .read_text(encoding="utf-8")
            .split("## Runtime-Closure Images", 1)[1]
            .split("## Full-Rootfs Images", 1)[0]
            .splitlines()
        )
        scorecard_measurement_lines = (
            (root / "docs" / "image-quality-scorecard.md")
            .read_text(encoding="utf-8")
            .split("## Measurable Gains Over Regular Images", 1)[1]
            .split("## Strengths That Matter", 1)[0]
            .splitlines()
        )
        closure_workflows = {}
        for workflow_name, workflow in discover_runtime_closure_workflows(
            workflow_dir
        ).items():
            image_name = next(
                line.partition(":")[2].strip()
                for line in workflow.splitlines()
                if line.strip().startswith("image_name:")
            )
            closure_workflows[image_name] = workflow_name

        inventory_rows = {
            columns[0].replace("`", ""): columns
            for line in inventory_lines
            if line.startswith("| `")
            for columns in [
                [column.strip() for column in line.strip("|").split("|")]
            ]
        }
        scorecard_rows = {
            columns[0].replace("`", ""): columns
            for line in scorecard_measurement_lines
            if line.startswith("| `")
            for columns in [
                [column.strip() for column in line.strip("|").split("|")]
            ]
        }
        self.assertEqual(set(inventory_rows), set(closure_workflows))
        self.assertEqual(set(scorecard_rows), set(closure_workflows))

        for image_name, workflow_name in closure_workflows.items():
            with self.subTest(image=image_name):
                workflow_lines = (
                    workflow_dir / workflow_name
                ).read_text(encoding="utf-8").splitlines()
                allowed_line = next(
                    line.strip()
                    for line in workflow_lines
                    if line.strip().startswith("allowed_packages:")
                )
                workflow_packages = allowed_line.partition(":")[2].strip().split(",")

                columns = inventory_rows[image_name]
                inventory_count = int(columns[2])
                inventory_packages = columns[3].replace("`", "").split(", ")
                scorecard_columns = scorecard_rows[image_name]
                scorecard_count = int(scorecard_columns[1])
                upstream_count = int(scorecard_columns[2])
                scorecard_reduction = int(scorecard_columns[3].removesuffix("%"))
                expected_reduction = round(
                    (upstream_count - scorecard_count) * 100 / upstream_count
                )

                self.assertEqual(inventory_count, len(workflow_packages))
                self.assertEqual(inventory_packages, workflow_packages)
                self.assertEqual(scorecard_count, inventory_count)
                self.assertEqual(scorecard_reduction, expected_reduction)

    def test_php_fpm_declares_opcache_lock_tmpfs(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        compose = (
            root / "tests" / "functional" / "php-fpm" / "compose.yaml"
        ).read_text(encoding="utf-8")
        workflow = (
            root / ".github" / "workflows" / "php-fpm-image.yml"
        ).read_text(encoding="utf-8")
        image_spec = (
            root / "images" / "php-fpm" / "image.yaml"
        ).read_text(encoding="utf-8")

        self.assertIn("/tmp:uid=10001,gid=0,mode=1777", compose)
        writable_paths = next(
            line.partition(":")[2].strip().split()
            for line in workflow.splitlines()
            if line.strip().startswith("writable_paths:")
        )
        self.assertIn("/tmp", writable_paths)
        self.assertRegex(
            image_spec,
            r'(?m)^  - path: /tmp\n    owner: 10001:0\n    mode: "1777"$',
        )

    def test_workflows_use_node24_action_generations(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        workflow_paths = sorted(
            set(workflow_dir.glob("*.yml"))
            | set(workflow_dir.glob("*.yaml"))
        )
        action_refs = {
            match.group(1)
            for path in workflow_paths
            for match in re.finditer(
                r"(?m)^\s*(?:-\s*)?uses:\s*([^\s#]+)",
                path.read_text(encoding="utf-8"),
            )
            if not match.group(1).startswith("./")
        }
        minimum_node24_versions = {
            "actions/checkout": (6, 0, 0),
            "actions/download-artifact": (7, 0, 0),
            "actions/upload-artifact": (6, 0, 0),
            "anchore/sbom-action": (0, 24, 0),
            "azure/setup-helm": (5, 0, 0),
            "docker/login-action": (4, 0, 0),
        }
        audited_composite_actions = {
            "aquasecurity/trivy-action",
            "sigstore/cosign-installer",
        }
        action_names = {ref.rpartition("@")[0] for ref in action_refs}
        self.assertEqual(
            action_names,
            set(minimum_node24_versions) | audited_composite_actions,
        )

        for ref in action_refs:
            action_name, separator, version = ref.rpartition("@")
            self.assertEqual(separator, "@", ref)
            if action_name not in minimum_node24_versions:
                continue
            with self.subTest(action=ref):
                match = re.fullmatch(r"v(\d+)(?:\.(\d+))?(?:\.(\d+))?", version)
                self.assertIsNotNone(match, ref)
                parsed_version = tuple(
                    int(component or 0) for component in match.groups()
                )
                self.assertGreaterEqual(
                    parsed_version,
                    minimum_node24_versions[action_name],
                )

    def test_download_artifact_suppresses_only_upstream_buffer_warning(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        workflow_paths = sorted(
            set(workflow_dir.glob("*.yml"))
            | set(workflow_dir.glob("*.yaml"))
        )
        download_steps = []
        for path in workflow_paths:
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                uses_match = re.match(
                    r"^(\s*)(-\s*)?uses:\s*actions/download-artifact@",
                    line,
                )
                if uses_match is None:
                    continue
                if uses_match.group(2):
                    step_indent = len(uses_match.group(1))
                    start = index
                else:
                    step_indent = len(uses_match.group(1)) - 2
                    step_start = re.compile(
                        rf"^ {{{step_indent}}}-\s+(?:name|uses):"
                    )
                    start = next(
                        candidate
                        for candidate in range(index, -1, -1)
                        if step_start.match(lines[candidate])
                    )
                next_step = re.compile(rf"^ {{{step_indent}}}-\s+")
                end = next(
                    (
                        candidate
                        for candidate in range(index + 1, len(lines))
                        if next_step.match(lines[candidate])
                    ),
                    len(lines),
                )
                download_steps.append((path, index + 1, "\n".join(lines[start:end])))

        self.assertTrue(download_steps)
        for path, line_number, step in download_steps:
            with self.subTest(workflow=path.name, line=line_number):
                self.assertIn(
                    "NODE_OPTIONS: --disable-warning=DEP0005",
                    step,
                )
                self.assertIn("actions/download-artifact#484", step)

    def test_write_permissions_and_operations_are_confined_to_release_graph(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        release_workflows = {
            name.replace(".yml", "-release.yml")
            for name in self.CORE_WORKFLOWS
        }
        write_capable = set()
        for path in workflow_dir.glob("*.yml"):
            content = path.read_text(encoding="utf-8")
            if "id-token: write" in content or "packages: write" in content:
                write_capable.add(path.name)
        self.assertEqual(
            write_capable, release_workflows | self.PUBLISHER_WORKFLOWS
        )

        read_only_graph = self.CORE_WORKFLOWS | {
            "image-contracts.yml",
            "reusable-build-debian-image.yml",
            "reusable-prepare-image-matrix.yml",
            "reusable-aggregate-image-contract.yml",
        }
        for name in read_only_graph:
            with self.subTest(workflow=name):
                content = (workflow_dir / name).read_text(encoding="utf-8")
                self.assertNotIn("id-token: write", content)
                self.assertNotIn("packages: write", content)

        write_operations = (
            "docker/login-action@",
            "docker push ",
            "cosign sign ",
            "docker buildx imagetools create ",
        )
        operation_workflows = set()
        for path in workflow_dir.glob("*.yml"):
            content = path.read_text(encoding="utf-8")
            if any(operation in content for operation in write_operations):
                operation_workflows.add(path.name)
        self.assertEqual(operation_workflows, self.PUBLISHER_WORKFLOWS)

        for name in self.CORE_WORKFLOWS:
            with self.subTest(reusable_only=name):
                content = (workflow_dir / name).read_text(encoding="utf-8")
                self.assertNotIn("workflow_dispatch:", content)
                self.assertNotIn("branches:", content)
                self.assertNotIn("reusable-publish", content)
                self.assertIn("export_image:", content)

        build_workflow = (
            workflow_dir / "reusable-build-debian-image.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("Export fully tested image for release", build_workflow)
        self.assertIn("Capture image identity used by tests", build_workflow)
        self.assertIn('--expected-image-id "$TESTED_IMAGE_ID"', build_workflow)
        self.assertIn("actions/upload-artifact@", build_workflow)
        self.assertIn(
            "name: image-release-archive--${{ inputs.image_name }}--${{ inputs.image_version }}--${{ inputs.debian_suite }}--${{ inputs.debian_arch }}--attempt-${{ github.run_attempt }}",
            build_workflow,
        )
        self.assertIn(
            "artifact-name: sbom-${{ inputs.image_name }}-${{ inputs.image_version }}-${{ inputs.debian_suite }}-${{ inputs.debian_arch }}-attempt-${{ github.run_attempt }}",
            build_workflow,
        )
        self.assertNotIn("docker push ", build_workflow)
        self.assertNotIn("cosign sign ", build_workflow)

        publisher = (
            workflow_dir / "reusable-publish-tested-image.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "name: image-release-archive--${{ inputs.image_name }}--${{ matrix.version }}--${{ matrix.debian_suite }}--${{ matrix.debian_arch }}--attempt-${{ github.run_attempt }}",
            publisher,
        )
        self.assertIn(
            "name: image-release-digest--${{ inputs.image_name }}--${{ matrix.version }}--${{ matrix.debian_suite }}--${{ matrix.debian_arch }}--attempt-${{ github.run_attempt }}",
            publisher,
        )
        self.assertIn("Reject newer release inputs on main", publisher)
        self.assertIn("fetch-depth: 0", publisher)
        self.assertIn("git merge-base --is-ancestor", publisher)
        self.assertIn("git log --format= --name-only --no-renames", publisher)
        manifest_call = publisher.split("\n  publish-manifest:", 1)[1]
        self.assertIn("\n      actions: read", manifest_call)
        manifest_publisher = (
            workflow_dir / "reusable-publish-image-manifest.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Reject newer release inputs on main", manifest_publisher
        )
        self.assertIn("fetch-depth: 0", manifest_publisher)
        self.assertIn("git merge-base --is-ancestor", manifest_publisher)
        self.assertIn(
            "git log --format= --name-only --no-renames", manifest_publisher
        )
        self.assertIn(
            "pattern: image-release-digest--${{ inputs.image_name }}--${{ inputs.image_version }}--${{ inputs.debian_suite }}--*--attempt-${{ github.run_attempt }}",
            manifest_publisher,
        )
        self.assertNotIn("source_tags", manifest_publisher)
        download_step = publisher.split(
            "uses: actions/download-artifact@", 1
        )[1].split("\n      - name:", 1)[0]
        self.assertNotIn("github-token:", download_step)
        self.assertNotIn("repository:", download_step)
        self.assertNotIn("run-id:", download_step)

        for name in release_workflows:
            with self.subTest(release_wrapper=name):
                content = (workflow_dir / name).read_text(encoding="utf-8")
                family = name.removesuffix("-image-release.yml").removesuffix(
                    "-images-release.yml"
                )
                path_lines = content.split("\n    paths:\n", 1)[1].split(
                    "\n  workflow_dispatch:", 1
                )[0]
                release_paths = {
                    line.strip().removeprefix("- ")
                    for line in path_lines.splitlines()
                    if line.strip().startswith("- ")
                }
                expected_paths = releasectl.COMMON_RELEASE_PATHS | {
                    f".github/workflows/{name}",
                    f".github/workflows/{name.replace('-release.yml', '.yml')}",
                    f"images/{family}/**",
                }
                self.assertEqual(release_paths, expected_paths)
                release_build, release_publish = content.split(
                    "\n  release_publish:", 1
                )
                release_build = release_build.split("\n  release_build:", 1)[1]
                self.assertIn("export_image: true", release_build)
                self.assertNotIn("id-token: write", release_build)
                self.assertNotIn("packages: write", release_build)
                self.assertIn("id-token: write", release_publish)
                self.assertIn("packages: write", release_publish)
                self.assertNotIn("secrets: inherit", release_publish)
                self.assertIn(
                    "uses: ./.github/workflows/reusable-publish-tested-image.yml",
                    release_publish,
                )

    def test_every_reusable_workflow_call_declares_permissions(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        reusable_calls = 0
        discovered_calls = 0
        for path in workflow_dir.glob("*.yml"):
            content = path.read_text(encoding="utf-8")
            discovered_calls += sum(
                line.startswith("    uses: ./.github/workflows/")
                for line in content.splitlines()
            )
            if "\njobs:\n" not in content:
                continue
            job_lines = content.split("\njobs:\n", 1)[1].splitlines()
            blocks = []
            current = []
            for line in job_lines:
                if line and not line.startswith(" "):
                    break
                if line.startswith("  ") and not line.startswith("    "):
                    if current:
                        blocks.append("\n".join(current))
                    current = [line]
                elif current:
                    current.append(line)
            if current:
                blocks.append("\n".join(current))

            for block in blocks:
                if "\n    uses: ./.github/workflows/" not in block:
                    continue
                reusable_calls += 1
                with self.subTest(workflow=path.name, job=block.split(":", 1)[0].strip()):
                    self.assertIn("\n    permissions:", block)
        self.assertGreater(discovered_calls, 0)
        self.assertEqual(reusable_calls, discovered_calls)


if __name__ == "__main__":
    unittest.main()
