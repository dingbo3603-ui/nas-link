from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = "19991108513@192.168.31.35"
DEFAULT_REMOTE_DIR = "/volume1/docker/nas-link"
DEFAULT_PUBLIC_URL = "http://192.168.31.35:8766"
ALLOWLIST = (
    ".env.example",
    ".gitignore",
    "docker-compose.yml",
    "README.md",
    "server/Dockerfile",
    "server/requirements.txt",
    "server/app/__init__.py",
    "server/app/config.py",
    "server/app/db.py",
    "server/app/deepseek.py",
    "server/app/extractors.py",
    "server/app/main.py",
    "server/app/organizer.py",
    "server/app/realtime.py",
    "server/app/schemas.py",
    "server/app/security.py",
    "server/app/storage.py",
)


def run(command: list[str], *, input_text: str | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        capture_output=capture,
    )


class Remote:
    def __init__(self, target: str):
        self.target = target
        self.base = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=10",
            target,
        ]

    def call(self, *args: str, input_text: str | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
        return run([*self.base, *args], input_text=input_text, capture=capture)

    def copy_from(self, remote_path: str, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        script = (
            "import base64,pathlib\n"
            f"path=pathlib.Path({remote_path!r})\n"
            "print(base64.b64encode(path.read_bytes()).decode('ascii'))\n"
        )
        result = self.call("python3", "-", input_text=script, capture=True)
        local_path.write_bytes(base64.b64decode(result.stdout.strip()))


def collect_payload() -> dict[str, str]:
    payload: dict[str, str] = {}
    for relative in ALLOWLIST:
        source = ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        payload[relative] = base64.b64encode(source.read_bytes()).decode("ascii")
    return payload


def deploy_script(payload: dict[str, str], remote_dir: str, public_url: str, stamp: str) -> str:
    return f"""
import base64
import json
import os
import pathlib
import secrets
import shutil

root = pathlib.Path({remote_dir!r})
backup = root / ".codex-backups" / {stamp!r}
payload = {json.dumps(payload)}
root.mkdir(parents=True, exist_ok=True)

for relative, encoded in payload.items():
    pure = pathlib.PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise RuntimeError(f"unsafe deploy path: {{relative}}")
    target = root.joinpath(*pure.parts)
    if target.exists():
        backup_target = backup.joinpath(*pure.parts)
        backup_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup_target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".codex-new")
    temporary.write_bytes(base64.b64decode(encoded))
    os.replace(temporary, target)

for relative in ("data", "data/index", "data/dropbox", "data/library", "data/backups"):
    (root / relative).mkdir(parents=True, exist_ok=True)

env_path = root / ".env"
env_was_present = env_path.exists()
if not env_was_present:
    token = secrets.token_urlsafe(48)
    env_path.write_text(
        "\\n".join([
            f"NAS_LINK_TOKEN={{token}}",
            "NAS_LINK_PORT=8766",
            "NAS_LINK_UID=1000",
            "NAS_LINK_GID=10",
            "NAS_LINK_DATA_ROOT=/data",
            "NAS_LINK_CLIPBOARD_TTL_MINUTES=60",
            "NAS_LINK_AUTO_ORGANIZE=true",
            "NAS_LINK_DEEPSEEK_CONTENT_MODE=snippet",
            "DEEPSEEK_API_KEY=",
            "DEEPSEEK_BASE_URL=https://api.deepseek.com",
            "DEEPSEEK_CLASSIFY_MODEL=deepseek-flash",
            "DEEPSEEK_ANSWER_MODEL=deepseek-v4-pro",
            "",
        ]),
        encoding="utf-8",
    )
    env_path.chmod(0o600)

values = {{}}
for line in env_path.read_text(encoding="utf-8").splitlines():
    if line and not line.lstrip().startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
token = values.get("NAS_LINK_TOKEN", "")
if len(token) < 24:
    raise RuntimeError("NAS_LINK_TOKEN must contain at least 24 characters")

bootstrap = root / "data" / "index" / "client-bootstrap.json"
bootstrap.write_text(json.dumps({{
    "serverUrl": {public_url!r},
    "token": token,
    "deviceName": "",
    "version": "0.1.0",
}}, ensure_ascii=False, indent=2), encoding="utf-8")
bootstrap.chmod(0o600)

print(json.dumps({{
    "uploaded_files": len(payload),
    "backup_created": backup.exists(),
    "env_created": not env_was_present,
    "remote_dir": str(root),
}}, ensure_ascii=False))
"""


def verify(remote: Remote, remote_dir: str) -> dict:
    quoted_dir = shlex.quote(remote_dir)
    command = (
        f"cd {quoted_dir} && "
        "docker compose config --quiet && "
        "test \"$(docker inspect -f '{{.State.Running}}' nas-link-server)\" = true && "
        "{ i=0; while [ $i -lt 10 ]; do "
        "curl -fsS --max-time 5 http://127.0.0.1:8766/health && exit 0; "
        "i=$((i+1)); sleep 2; done; exit 1; }"
    )
    result = remote.call(command, capture=True)
    output = result.stdout.strip().splitlines()
    health_line = next((line for line in reversed(output) if line.startswith("{") and '"ok"' in line), "{}")
    health = json.loads(health_line)
    if not health.get("ok") or not health.get("security_ready"):
        raise RuntimeError(f"NAS health verification failed: {health}")
    return health


def verify_workstation(public_url: str) -> dict:
    last_error: Exception | None = None
    for _ in range(5):
        try:
            with urllib.request.urlopen(f"{public_url.rstrip('/')}/health", timeout=8) as response:
                health = json.loads(response.read().decode("utf-8"))
            if health.get("ok") and health.get("security_ready"):
                return health
            raise RuntimeError(f"Unexpected workstation health response: {health}")
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Workstation cannot read back NAS Link at {public_url}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy NAS Link safely to the verified UGREEN NAS Docker host.")
    parser.add_argument("--apply", action="store_true", help="Perform the deployment. Without this flag, print a dry-run plan.")
    parser.add_argument("--verify-only", action="store_true", help="Verify the current remote deployment without writing files.")
    parser.add_argument("--target", default=os.environ.get("NAS_LINK_SSH_TARGET", DEFAULT_TARGET))
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR)
    parser.add_argument("--public-url", default=DEFAULT_PUBLIC_URL)
    parser.add_argument(
        "--bootstrap-output",
        type=Path,
        default=ROOT / "release" / "nas-link-client-config.json",
        help="Local path for the secret client bootstrap file.",
    )
    args = parser.parse_args()
    remote = Remote(args.target)

    if args.verify_only:
        health = verify(remote, args.remote_dir)
        workstation_health = verify_workstation(args.public_url)
        print(json.dumps({"verified": True, "health": health, "workstation_readback": workstation_health}, ensure_ascii=False))
        return 0

    payload = collect_payload()
    plan = {
        "target": args.target,
        "remote_dir": args.remote_dir,
        "public_url": args.public_url,
        "files": list(payload),
        "preserve": [".env", "data/"],
        "bootstrap_output": str(args.bootstrap_output),
    }
    if not args.apply:
        print(json.dumps({"dry_run": True, **plan}, ensure_ascii=False, indent=2))
        return 0

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    remote.call("python3", "-", input_text=deploy_script(payload, args.remote_dir, args.public_url, stamp))
    remote.call(f"cd {shlex.quote(args.remote_dir)} && docker compose up -d --build")
    health = verify(remote, args.remote_dir)
    workstation_health = verify_workstation(args.public_url)
    remote.copy_from(f"{args.remote_dir}/data/index/client-bootstrap.json", args.bootstrap_output)
    try:
        os.chmod(args.bootstrap_output, 0o600)
    except OSError:
        pass
    print(
        json.dumps(
            {
                "deployed": True,
                "verified": True,
                "health": health,
                "workstation_readback": workstation_health,
                "bootstrap_output": str(args.bootstrap_output),
                "warning": "The bootstrap file contains a secret. Import it on trusted devices, then protect or remove it.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
