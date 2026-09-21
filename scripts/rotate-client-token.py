from __future__ import annotations

import argparse
import json
import os
import secrets
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = "19991108513@192.168.31.35"
DEFAULT_REMOTE_DIR = "/volume1/docker/nas-link"
DEFAULT_PUBLIC_URL = "http://192.168.31.35:8766"


def ssh(target: str, command: str, *, input_text: str | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=10", target, command,
        ],
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        capture_output=capture,
    )


def authorized_get(url: str, token: str) -> int:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotate the NAS Link client token without printing it.")
    parser.add_argument("--target", default=os.environ.get("NAS_LINK_SSH_TARGET", DEFAULT_TARGET))
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR)
    parser.add_argument("--public-url", default=DEFAULT_PUBLIC_URL)
    parser.add_argument("--bootstrap-output", type=Path, default=ROOT / "release" / "nas-link-client-config.json")
    args = parser.parse_args()

    runtime_path = Path(os.environ["APPDATA"]) / "nas-link-desktop" / "config.json" if os.environ.get("APPDATA") else None
    runtime = json.loads(runtime_path.read_text(encoding="utf-8")) if runtime_path and runtime_path.exists() else {}
    bootstrap = json.loads(args.bootstrap_output.read_text(encoding="utf-8")) if args.bootstrap_output.exists() else {}
    old_token = str(runtime.get("token") or bootstrap.get("token") or "")
    new_token = secrets.token_urlsafe(48)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    remote_code = f"""
import json
import os
import pathlib
import shutil
import sys

token = sys.stdin.read().strip()
if len(token) < 48:
    raise RuntimeError("generated token is unexpectedly short")
root = pathlib.Path({args.remote_dir!r})
env_path = root / ".env"
bootstrap_path = root / "data" / "index" / "client-bootstrap.json"
backup = root / ".codex-backups" / {stamp!r} / "token-rotation"
backup.mkdir(parents=True, exist_ok=True)
shutil.copy2(env_path, backup / ".env")
if bootstrap_path.exists():
    shutil.copy2(bootstrap_path, backup / "client-bootstrap.json")

lines = env_path.read_text(encoding="utf-8").splitlines()
updated = []
replaced = False
for line in lines:
    if line.startswith("NAS_LINK_TOKEN="):
        updated.append("NAS_LINK_TOKEN=" + token)
        replaced = True
    else:
        updated.append(line)
if not replaced:
    updated.append("NAS_LINK_TOKEN=" + token)
temporary = env_path.with_name(".env.token-new")
temporary.write_text("\\n".join(updated) + "\\n", encoding="utf-8")
temporary.chmod(0o600)
os.replace(temporary, env_path)

bootstrap_path.parent.mkdir(parents=True, exist_ok=True)
bootstrap_temp = bootstrap_path.with_name(bootstrap_path.name + ".token-new")
bootstrap_temp.write_text(json.dumps({{
    "serverUrl": {args.public_url!r},
    "token": token,
    "deviceName": "",
    "version": "0.1.2",
}}, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
bootstrap_temp.chmod(0o600)
os.replace(bootstrap_temp, bootstrap_path)
print(json.dumps({{"updated": True, "backup": str(backup)}}))
"""
    result = ssh(args.target, f"python3 -c {shlex.quote(remote_code)}", input_text=new_token, capture=True)
    receipt = json.loads(result.stdout.strip())
    backup_path = receipt["backup"]

    try:
        ssh(args.target, f"cd {shlex.quote(args.remote_dir)} && docker compose up -d --force-recreate")
        health = None
        for _ in range(12):
            try:
                with urllib.request.urlopen(f"{args.public_url}/health", timeout=5) as response:
                    health = json.loads(response.read().decode("utf-8"))
                if health.get("ok"):
                    break
            except Exception:
                pass
            time.sleep(2)
        if not health or not health.get("ok"):
            raise RuntimeError("service health check did not recover after token rotation")
        new_status = authorized_get(f"{args.public_url}/api/dashboard", new_token)
        old_status = authorized_get(f"{args.public_url}/api/dashboard", old_token) if old_token else None
        if new_status != 200 or (old_token and old_status != 401):
            raise RuntimeError(f"token readback failed: new={new_status}, old={old_status}")
    except Exception:
        rollback = f"""
import pathlib
import shutil
root = pathlib.Path({args.remote_dir!r})
backup = pathlib.Path({backup_path!r})
shutil.copy2(backup / ".env", root / ".env")
saved = backup / "client-bootstrap.json"
if saved.exists():
    shutil.copy2(saved, root / "data" / "index" / "client-bootstrap.json")
"""
        ssh(args.target, f"python3 -c {shlex.quote(rollback)}")
        ssh(args.target, f"cd {shlex.quote(args.remote_dir)} && docker compose up -d --force-recreate")
        raise

    connection_payload = {"serverUrl": args.public_url, "token": new_token, "deviceName": "", "version": "0.1.2"}
    write_json_atomic(args.bootstrap_output, connection_payload)
    runtime_updated = False
    if runtime_path and runtime:
        backup_runtime = runtime_path.with_name(f"config.json.backup-{stamp}")
        backup_runtime.write_text(json.dumps(runtime, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        runtime["serverUrl"] = args.public_url
        runtime["token"] = new_token
        write_json_atomic(runtime_path, runtime)
        runtime_updated = True

    print(json.dumps({
        "rotated": True,
        "remote_backup_created": True,
        "new_token_status": new_status,
        "old_token_status": old_status,
        "health_version": health.get("version"),
        "bootstrap_updated": args.bootstrap_output.exists(),
        "runtime_config_updated": runtime_updated,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
