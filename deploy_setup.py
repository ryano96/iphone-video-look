"""Create GitHub repo + Render web service for iphone-video-look."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request

REPO_NAME = "iphone-video-look"
GITHUB_USER = "ryano96"
RENDER_OWNER_ID = "tea-d8fm7qv7f7vs73eg27eg"
RENDER_SERVICE_NAME = "iphone-video-look"


def github_token() -> str:
    proc = subprocess.run(
        ["git", "credential", "fill"],
        input="url=https://github.com\n\n",
        capture_output=True,
        text=True,
        check=True,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("No GitHub token")


def gh_request(method: str, path: str, body: dict | None = None) -> object:
    url = f"https://api.github.com{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {github_token()}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "iphone-video-look-deploy",
            **({"Content-Type": "application/json"} if data else {}),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub {method} {path} → {exc.code}: {detail}") from exc


def render_request(method: str, path: str, body: dict | None = None) -> object:
    sys.path.insert(0, str(__file__).replace("deploy_setup.py", "../render_ops"))
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "render_ops"))
    from render_client import request  # noqa: PLC0415

    return request(method, path, body=body)


def ensure_github_repo() -> str:
    repo_url = f"https://github.com/{GITHUB_USER}/{REPO_NAME}.git"
    try:
        gh_request("GET", f"/repos/{GITHUB_USER}/{REPO_NAME}")
        print(f"GitHub repo exists: {repo_url}")
        return repo_url
    except RuntimeError as exc:
        if "404" not in str(exc):
            raise
    gh_request(
        "POST",
        "/user/repos",
        {
            "name": REPO_NAME,
            "description": "Make AI videos look like casual iPhone footage",
            "private": False,
        },
    )
    print(f"Created GitHub repo: {repo_url}")
    return repo_url


def ensure_render_service(repo_url: str) -> dict:
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "render_ops"))
    from render_client import find_service  # noqa: PLC0415

    try:
        svc = find_service(RENDER_SERVICE_NAME)
        print(f"Render service exists: {(svc.get('serviceDetails') or {}).get('url', svc.get('id'))}")
        return svc
    except RuntimeError:
        pass

    payload = {
        "type": "web_service",
        "name": RENDER_SERVICE_NAME,
        "ownerId": RENDER_OWNER_ID,
        "repo": repo_url,
        "branch": "main",
        "autoDeploy": "yes",
        "serviceDetails": {
            "env": "docker",
            "plan": "starter",
            "region": "oregon",
            "numInstances": 1,
            "healthCheckPath": "/health",
            "envSpecificDetails": {
                "dockerfilePath": "./Dockerfile",
                "dockerContext": ".",
            },
        },
    }
    result = render_request("POST", "/services", body=payload)
    svc = result.get("service") or result
    url = (svc.get("serviceDetails") or {}).get("url", "")
    print(f"Created Render service: {url or svc.get('dashboardUrl')}")
    return svc


if __name__ == "__main__":
    url = ensure_github_repo()
    ensure_render_service(url)
    print("OK")