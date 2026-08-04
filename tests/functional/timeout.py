#!/usr/bin/env python3
"""Run a command with a real wall-clock deadline and process-group cleanup."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--kill-after", type=float, default=10.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if args.timeout <= 0 or args.kill_after <= 0:
        parser.error("timeouts must be positive")
    if not args.command:
        parser.error("a command is required after --")
    return args


def terminate_group(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass


def normalized_returncode(returncode: int) -> int:
    return returncode if returncode >= 0 else 128 + abs(returncode)


def main() -> int:
    args = parse_args()
    process = subprocess.Popen(args.command, start_new_session=True)

    def forward(signum: int, _frame: object) -> None:
        terminate_group(process, signal.Signals(signum))

    signal.signal(signal.SIGINT, forward)
    signal.signal(signal.SIGTERM, forward)

    try:
        return normalized_returncode(process.wait(timeout=args.timeout))
    except subprocess.TimeoutExpired:
        print(
            f"command exceeded {args.timeout:g}s wall-clock timeout: {args.command[0]}",
            file=sys.stderr,
        )
        terminate_group(process, signal.SIGTERM)
        try:
            process.wait(timeout=args.kill_after)
        except subprocess.TimeoutExpired:
            terminate_group(process, signal.SIGKILL)
            process.wait()
        return 124
    finally:
        if process.poll() is None:
            terminate_group(process, signal.SIGTERM)
            try:
                process.wait(timeout=args.kill_after)
            except subprocess.TimeoutExpired:
                terminate_group(process, signal.SIGKILL)
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
