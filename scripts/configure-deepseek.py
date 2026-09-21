from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys


TARGET = os.environ.get("NAS_LINK_SSH_TARGET", "19991108513@192.168.31.35")
REMOTE_DIR = "/volume1/docker/nas-link"


def ssh(command: str, *, input_text: str | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=10",
            TARGET,
            command,
        ],
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        capture_output=capture,
    )


def main() -> int:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if len(key) < 20:
        raise RuntimeError("DEEPSEEK_API_KEY is missing or unexpectedly short")

    remote_code = f"""
import datetime
import json
import pathlib
import shutil
import sys

key = sys.stdin.read().strip()
if len(key) < 20:
    raise RuntimeError("DeepSeek key is missing or unexpectedly short")
root = pathlib.Path({REMOTE_DIR!r})
env_path = root / ".env"
if not env_path.exists():
    raise FileNotFoundError(env_path)
stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
backup = root / ".codex-backups" / stamp / ".env.before-deepseek"
backup.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(env_path, backup)
lines = env_path.read_text(encoding="utf-8").splitlines()
updated = []
replaced = False
for line in lines:
    if line.startswith("DEEPSEEK_API_KEY="):
        updated.append("DEEPSEEK_API_KEY=" + key)
        replaced = True
    else:
        updated.append(line)
if not replaced:
    updated.append("DEEPSEEK_API_KEY=" + key)
temporary = env_path.with_suffix(".env-new")
temporary.write_text("\\n".join(updated) + "\\n", encoding="utf-8")
temporary.chmod(0o600)
temporary.replace(env_path)
print(json.dumps({{"configured": True, "backup": str(backup)}}))
"""
    result = ssh(f"python3 -c {shlex.quote(remote_code)}", input_text=key, capture=True)
    remote_receipt = json.loads(result.stdout.strip())

    ssh(f"cd {shlex.quote(REMOTE_DIR)} && docker compose up -d --force-recreate")
    test_code = """
import json, os, httpx
response = httpx.post(
    os.environ.get('DEEPSEEK_BASE_URL','https://api.deepseek.com').rstrip('/') + '/chat/completions',
    headers={'Authorization':'Bearer ' + os.environ['DEEPSEEK_API_KEY']},
    json={
        'model': os.environ.get('DEEPSEEK_CLASSIFY_MODEL','deepseek-flash'),
        'messages': [
            {'role':'system','content':'Return json only.'},
            {'role':'user','content':'Return this JSON object exactly: {"ok":true}'},
        ],
        'response_format': {'type':'json_object'},
        'thinking': {'type':'disabled'},
        'max_tokens': 30,
        'stream': False,
    },
    timeout=90,
)
response.raise_for_status()
data=response.json()
content=data['choices'][0]['message'].get('content','')
print(json.dumps({'api_status':response.status_code,'model':data.get('model'),'content_present':bool(content)}))
"""
    checked = ssh(
        f"docker exec nas-link-server python -c {shlex.quote(test_code)}",
        capture=True,
    )
    api_receipt = json.loads(checked.stdout.strip())
    health = ssh(
        "i=0; while [ $i -lt 10 ]; do "
        "curl -fsS --max-time 5 http://127.0.0.1:8766/health && exit 0; "
        "i=$((i+1)); sleep 2; done; exit 1",
        capture=True,
    )
    health_receipt = json.loads(health.stdout.strip())
    if not health_receipt.get("deepseek_configured") or not api_receipt.get("content_present"):
        raise RuntimeError("DeepSeek configuration did not pass independent readback")
    print(
        json.dumps(
            {
                "configured": True,
                "backup_created": bool(remote_receipt.get("backup")),
                "api_status": api_receipt["api_status"],
                "model": api_receipt.get("model"),
                "health_readback": health_receipt,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"configured": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        raise
