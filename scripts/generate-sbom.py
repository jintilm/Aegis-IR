#!/usr/bin/env python3
"""Generate a deterministic CycloneDX JSON SBOM for the release archive."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import subprocess
import uuid
from pathlib import Path


def command_version(command: list[str], pattern: str = r"\d+\.\d+\.\d+") -> str:
    if shutil.which(command[0]) is None:
        return "unknown"
    result = subprocess.run(
        command, text=True, capture_output=True, check=False)
    text = (result.stdout or result.stderr).strip()
    match = re.search(pattern, text)
    return match.group(0) if match else "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    if epoch <= 0:
        epoch = int(dt.datetime.now(dt.timezone.utc).timestamp())
    timestamp = dt.datetime.fromtimestamp(
        epoch, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    serial = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"https://github.com/jintilm/Aegis-IR/{args.commit}/{args.version}")

    components = [
        {
            "type": "application",
            "bom-ref": "pkg:aegis-ir",
            "name": "aegis-ir",
            "version": args.version,
            "licenses": [{"license": {"id": "Apache-2.0"}}],
            "properties": [{"name": "commit", "value": args.commit}],
        },
        {
            "type": "platform",
            "bom-ref": "pkg:ubuntu-24.04",
            "name": "ubuntu",
            "version": "24.04",
        },
        {
            "type": "framework",
            "bom-ref": "pkg:llvm",
            "name": "llvm",
            "version": command_version(["llvm-config-23", "--version"]),
        },
        {
            "type": "application",
            "bom-ref": "pkg:clang",
            "name": "clang",
            "version": command_version(["clang++-23", "--version"]),
        },
        {
            "type": "application",
            "bom-ref": "pkg:python",
            "name": "python",
            "version": platform.python_version(),
        },
        {
            "type": "application",
            "bom-ref": "pkg:cmake",
            "name": "cmake",
            "version": command_version(["cmake", "--version"]),
        },
        {
            "type": "application",
            "bom-ref": "pkg:ninja",
            "name": "ninja",
            "version": command_version(["ninja", "--version"], r"\d+\.\d+\.\d+"),
        },
    ]
    refs = [component["bom-ref"] for component in components[1:]]
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "timestamp": timestamp,
            "component": components[0],
            "tools": {
                "components": [{
                    "type": "application",
                    "name": "aegis-ir-generate-sbom",
                    "version": "1",
                }],
            },
        },
        "components": components[1:],
        "dependencies": [{
            "ref": components[0]["bom-ref"],
            "dependsOn": refs,
        }],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(bom, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
