#!/usr/bin/env python3
"""Run a functional Compose contract through host-controlled stop and restart phases."""

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import time


EXIT_ASSERTION = 10
EXIT_READINESS = 11
EXIT_TIMEOUT = 13
EXIT_INFRASTRUCTURE = 14
ASSERTION_PREFIX = "DHI_ASSERTION_SUMMARY "
ASSERTION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class LifecycleError(RuntimeError):
    def __init__(self, message, exit_code=EXIT_INFRASTRUCTURE):
        super().__init__(message)
        self.exit_code = exit_code


def load_assertion_contract(path, family):
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError(f"assertion contract is unreadable: {exc}") from exc
    if not isinstance(document, dict) or set(document) != {
        "schemaVersion",
        "family",
        "suite",
        "requiredAssertions",
    }:
        raise LifecycleError("assertion contract has an invalid shape")
    required = document["requiredAssertions"]
    if (
        document["schemaVersion"] != 1
        or document["family"] != family
        or not isinstance(document["suite"], str)
        or not ASSERTION_ID_RE.fullmatch(document["suite"])
        or not isinstance(required, list)
        or not required
        or any(not isinstance(item, str) or not ASSERTION_ID_RE.fullmatch(item) for item in required)
        or len(required) != len(set(required))
    ):
        raise LifecycleError("assertion contract is invalid or belongs to another family")
    return document


def parse_assertion_summary(output, assertion_contract, phase):
    encoded = [
        line[len(ASSERTION_PREFIX) :]
        for line in output.splitlines()
        if line.startswith(ASSERTION_PREFIX)
    ]
    if len(encoded) != 1:
        raise LifecycleError(
            f"{phase} verifier emitted {len(encoded)} assertion summaries; expected exactly one",
            EXIT_ASSERTION,
        )
    try:
        summary = json.loads(encoded[0])
    except json.JSONDecodeError as exc:
        raise LifecycleError(
            f"{phase} verifier assertion summary is invalid JSON: {exc}", EXIT_ASSERTION
        ) from exc
    if not isinstance(summary, dict) or set(summary) != {
        "assertions",
        "counts",
        "outcome",
        "schemaVersion",
        "suite",
    }:
        raise LifecycleError(f"{phase} verifier assertion summary has an invalid shape", EXIT_ASSERTION)
    assertions = summary["assertions"]
    if not isinstance(assertions, list) or not assertions:
        raise LifecycleError(f"{phase} verifier reported no assertions", EXIT_ASSERTION)
    assertion_ids = []
    for record in assertions:
        if (
            not isinstance(record, dict)
            or set(record) != {"id", "status"}
            or not isinstance(record.get("id"), str)
            or not ASSERTION_ID_RE.fullmatch(record["id"])
            or record.get("status") != "pass"
        ):
            raise LifecycleError(
                f"{phase} verifier assertion record is invalid or non-passing",
                EXIT_ASSERTION,
            )
        assertion_ids.append(record["id"])
    counts = summary["counts"]
    expected_ids = assertion_contract["requiredAssertions"]
    if (
        len(assertion_ids) != len(set(assertion_ids))
        or set(assertion_ids) != set(expected_ids)
        or not isinstance(counts, dict)
        or set(counts) != {"fail", "pass"}
        or type(counts["fail"]) is not int
        or type(counts["pass"]) is not int
        or counts != {"fail": 0, "pass": len(assertion_ids)}
        or summary["outcome"] != "pass"
        or summary["schemaVersion"] != 1
        or summary["suite"] != assertion_contract["suite"]
    ):
        raise LifecycleError(
            f"{phase} verifier assertion summary does not satisfy the family contract",
            EXIT_ASSERTION,
        )
    return summary


def utc_now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Controller:
    def __init__(self, arguments):
        self.arguments = arguments
        self.started = time.monotonic()
        self.deadline = self.started + arguments.timeout
        self.compose = [
            "docker",
            "compose",
            "--ansi",
            "never",
            "--project-name",
            arguments.project,
            "--file",
            arguments.compose_file,
        ]
        self.assertion_contract = None
        self.result = {
            "schemaVersion": 1,
            "contract": {
                "family": arguments.family,
                "version": arguments.version,
                "platform": arguments.platform,
                "project": arguments.project,
                "sutService": arguments.sut_service,
                "testService": arguments.test_service,
            },
            "identity": {
                "sourceImageId": arguments.source_image_id,
                "sutImageId": arguments.sut_image_id,
            },
            "assertionContract": self.assertion_contract,
            "phases": {},
            "outcome": {"status": "fail", "message": "controller did not complete"},
        }

    def remaining(self, maximum=None):
        value = self.deadline - time.monotonic()
        if value <= 0:
            raise LifecycleError("functional lifecycle deadline expired", EXIT_TIMEOUT)
        return value if maximum is None else min(value, maximum)

    def run(self, command, *, maximum=None, check=True, capture=True, echo=True):
        available = self.deadline - time.monotonic()
        if available <= 0:
            raise LifecycleError("functional lifecycle deadline expired", EXIT_TIMEOUT)
        deadline_limited = maximum is None or available <= maximum
        try:
            completed = subprocess.run(
                command,
                check=False,
                text=True,
                stdout=subprocess.PIPE if capture else None,
                stderr=subprocess.STDOUT if capture else None,
                timeout=self.remaining(maximum),
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired as exc:
            exit_code = EXIT_TIMEOUT if deadline_limited else EXIT_READINESS
            raise LifecycleError(
                f"command timed out: {' '.join(command)}", exit_code
            ) from exc
        if capture and echo and completed.stdout:
            print(completed.stdout, end="")
        if check and completed.returncode != 0:
            raise LifecycleError(
                f"command exited {completed.returncode}: {' '.join(command)}",
                EXIT_INFRASTRUCTURE,
            )
        return completed

    def service_container(self, service):
        completed = self.run(self.compose + ["ps", "--all", "--quiet", service], maximum=30)
        identifiers = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if len(identifiers) != 1:
            raise LifecycleError(
                f"expected exactly one container for {service}, found {len(identifiers)}",
                EXIT_READINESS,
            )
        return identifiers[0]

    def wait_container(self, container_id, *, maximum=None):
        completed = self.run(["docker", "wait", container_id], maximum=maximum)
        values = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if len(values) != 1 or not values[0].isdigit():
            raise LifecycleError(f"docker wait returned an invalid exit code for {container_id}")
        return int(values[0])

    def inspect_state(self, container_id):
        completed = self.run(
            [
                "docker",
                "inspect",
                container_id,
                "--format",
                "{{json .State}}",
            ],
            maximum=30,
        )
        try:
            state = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise LifecycleError(f"container state is not valid JSON: {container_id}") from exc
        if state.get("OOMKilled"):
            raise LifecycleError(f"container was OOM-killed: {container_id}", EXIT_READINESS)
        return state

    def service_names(self):
        completed = self.run(
            self.compose + ["config", "--services"], maximum=30, echo=False
        )
        names = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if self.arguments.test_service not in names or self.arguments.sut_service not in names:
            raise LifecycleError("Compose service inventory is incomplete")
        if len(names) != len(set(names)):
            raise LifecycleError("Compose service inventory contains duplicates")
        return names

    def long_lived_service_states(self, service_names, phase):
        records = []
        for service in service_names:
            if service == self.arguments.test_service:
                continue
            container_id = self.service_container(service)
            state = self.inspect_state(container_id)
            exit_code = state.get("ExitCode")
            if state.get("Status") != "running" or exit_code != 0:
                raise LifecycleError(
                    f"{phase} long-lived service {service} is not running cleanly",
                    EXIT_READINESS,
                )
            records.append(
                {
                    "name": service,
                    "containerId": container_id,
                    "state": state.get("Status"),
                    "exitCode": exit_code,
                    "oomKilled": bool(state.get("OOMKilled")),
                }
            )
        return records

    @staticmethod
    def verifier_exit(exit_code, phase):
        if exit_code == 0:
            return
        if exit_code in (1, EXIT_ASSERTION):
            raise LifecycleError(f"{phase} application assertions failed", EXIT_ASSERTION)
        if exit_code in (EXIT_READINESS, 126, 127):
            raise LifecycleError(f"{phase} setup or readiness failed", EXIT_READINESS)
        if exit_code == EXIT_TIMEOUT:
            raise LifecycleError(f"{phase} exceeded its execution deadline", EXIT_TIMEOUT)
        if exit_code == EXIT_INFRASTRUCTURE:
            raise LifecycleError(f"{phase} verifier infrastructure failed", EXIT_INFRASTRUCTURE)
        raise LifecycleError(f"{phase} verifier exited unexpectedly with {exit_code}", EXIT_READINESS)

    def execute(self):
        self.assertion_contract = load_assertion_contract(
            self.arguments.assertion_contract, self.arguments.family
        )
        self.result["assertionContract"] = self.assertion_contract
        service_names = self.service_names()
        topology_started_at = utc_now()
        self.run(
            self.compose
            + ["up", "--detach", "--no-build", "--pull", "never", "--no-recreate"],
            maximum=120,
        )
        test_container = self.service_container(self.arguments.test_service)
        initial_exit = self.wait_container(test_container)
        self.verifier_exit(initial_exit, "initial")
        initial_logs = self.run(
            ["docker", "logs", test_container], maximum=30, echo=False
        ).stdout
        initial_assertions = parse_assertion_summary(
            initial_logs, self.assertion_contract, "initial"
        )
        sut_container = self.service_container(self.arguments.sut_service)
        initial_state = self.inspect_state(sut_container)
        if initial_state.get("Status") != "running":
            raise LifecycleError("SUT stopped before lifecycle control", EXIT_READINESS)
        self.result["phases"]["initial"] = {
            "startedAt": topology_started_at,
            "finishedAt": utc_now(),
            "testContainerId": test_container,
            "testExitCode": initial_exit,
            "sutContainerId": sut_container,
            "sutState": initial_state.get("Status"),
            "assertions": initial_assertions,
            "services": self.long_lived_service_states(service_names, "initial"),
        }

        signal_started = time.monotonic()
        signal_started_at = utc_now()
        self.run(
            ["docker", "kill", "--signal", self.arguments.signal, sut_container],
            maximum=30,
        )
        sut_exit = self.wait_container(sut_container, maximum=self.arguments.shutdown_timeout)
        stopped_state = self.inspect_state(sut_container)
        if stopped_state.get("Status") != "exited":
            raise LifecycleError(
                f"SUT did not reach the exited state after {self.arguments.signal}",
                EXIT_READINESS,
            )
        if sut_exit not in self.arguments.allowed_exit_codes:
            raise LifecycleError(
                f"SUT exited {sut_exit} after {self.arguments.signal}; allowed: {self.arguments.allowed_exit_codes}",
                EXIT_READINESS,
            )
        self.result["phases"]["shutdown"] = {
            "signal": self.arguments.signal,
            "startedAt": signal_started_at,
            "finishedAt": utc_now(),
            "durationMs": int((time.monotonic() - signal_started) * 1000),
            "sutExitCode": sut_exit,
            "sutState": stopped_state.get("Status"),
            "oomKilled": bool(stopped_state.get("OOMKilled")),
        }

        restart_started = time.monotonic()
        restart_started_at = utc_now()
        self.run(self.compose + ["start", self.arguments.sut_service], maximum=120)
        restarted_container = self.service_container(self.arguments.sut_service)
        if restarted_container != sut_container:
            raise LifecycleError("Compose restart replaced the SUT container instead of restarting it")
        second = self.run(
            self.compose
            + [
                "run",
                "--rm",
                "--no-deps",
                "--pull",
                "never",
                "--env",
                "DHI_LIFECYCLE_PHASE=restart",
                self.arguments.test_service,
            ],
            check=False,
        )
        self.verifier_exit(second.returncode, "restart")
        restart_assertions = parse_assertion_summary(
            second.stdout or "", self.assertion_contract, "restart"
        )
        restarted_state = self.inspect_state(sut_container)
        if restarted_state.get("Status") != "running":
            raise LifecycleError("SUT is not running after the restart probe", EXIT_READINESS)
        self.result["phases"]["restart"] = {
            "startedAt": restart_started_at,
            "finishedAt": utc_now(),
            "durationMs": int((time.monotonic() - restart_started) * 1000),
            "testExitCode": second.returncode,
            "sutContainerId": sut_container,
            "sutState": restarted_state.get("Status"),
            "oomKilled": bool(restarted_state.get("OOMKilled")),
            "assertions": restart_assertions,
            "services": self.long_lived_service_states(service_names, "restart"),
        }
        self.result["outcome"] = {
            "status": "pass",
            "message": "initial application contract and host-controlled stop/restart probe passed",
        }


def parse_exit_codes(value):
    values = []
    for item in value.split(","):
        item = item.strip()
        if not item.isdigit():
            raise argparse.ArgumentTypeError("allowed exit codes must be comma-separated integers")
        number = int(item)
        if number < 0 or number > 255:
            raise argparse.ArgumentTypeError("allowed exit codes must be between 0 and 255")
        values.append(number)
    if not values:
        raise argparse.ArgumentTypeError("at least one allowed exit code is required")
    return sorted(set(values))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compose-file", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--sut-service", required=True)
    parser.add_argument("--test-service", required=True)
    parser.add_argument("--source-image-id", required=True)
    parser.add_argument("--sut-image-id", required=True)
    parser.add_argument("--assertion-contract", type=pathlib.Path, required=True)
    parser.add_argument("--timeout", type=int, required=True)
    parser.add_argument("--signal", default="SIGTERM")
    parser.add_argument("--shutdown-timeout", type=int, default=30)
    parser.add_argument("--allowed-exit-codes", type=parse_exit_codes, default=parse_exit_codes("0,143"))
    parser.add_argument("--output", type=pathlib.Path, required=True)
    arguments = parser.parse_args()
    if arguments.timeout < 1 or arguments.shutdown_timeout < 1:
        parser.error("timeouts must be positive")
    return arguments


def atomic_write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main():
    arguments = parse_args()
    controller = Controller(arguments)
    exit_code = 0
    try:
        controller.execute()
    except LifecycleError as exc:
        controller.result["outcome"] = {"status": "fail", "message": str(exc)}
        print(f"functional lifecycle failed: {exc}", file=sys.stderr)
        exit_code = exc.exit_code
    except Exception as exc:  # fail closed with a durable result
        controller.result["outcome"] = {
            "status": "fail",
            "message": f"unexpected controller failure: {exc}",
        }
        print(f"functional lifecycle infrastructure failed: {exc}", file=sys.stderr)
        exit_code = EXIT_INFRASTRUCTURE
    finally:
        controller.result["durationMs"] = int((time.monotonic() - controller.started) * 1000)
        atomic_write(arguments.output, controller.result)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
