import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT

# Never downloaded: the agent reads code, not media or model weights.
MEDIA = [f"*.{ext}" for e in ("jpg", "jpeg", "png", "gif", "webp", "mp4", "zip", "pth", "pt", "bin",
                              "onnx", "h5", "ckpt", "safetensors") for ext in (e, e.upper())]


@dataclass
class Repo:
    full_name: str
    path: Path


def git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def registry():
    return {r["name"]: r for r in tomllib.loads((ROOT / "repos.toml").read_text())["repo"]}


def download(dest, url, ref, skip=()):
    dest.mkdir(parents=True, exist_ok=True)
    try:
        git("init", "-q", cwd=dest)
        git("remote", "add", "origin", url, cwd=dest)
        git("sparse-checkout", "set", "--no-cone", "/*", *[f"!{p}" for p in [*MEDIA, *skip]], cwd=dest)
        git("fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", ref, cwd=dest)
        git("checkout", "-q", "FETCH_HEAD", cwd=dest)
    except subprocess.CalledProcessError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


def clone_pinned(r):
    if "local_path" in r:
        return ROOT / r["local_path"]
    dest = ROOT / "workspace" / r["name"]
    return dest if (dest / ".git").exists() else download(dest, r["url"], r["commit"], r.get("skip", []))


def resolve(name):
    reg = registry()
    if name in reg:
        return Repo(reg[name]["full_name"], clone_pinned(reg[name]))
    m = re.fullmatch(r"(?:https?://(?:www\.)?github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/(?:tree|blob)/.*)?/?",
                     name.strip())
    if not m:
        raise ValueError(f"Not a GitHub repository: {name}")
    full_name = "/".join(m.groups())
    for r in reg.values():
        if r["full_name"].lower() == full_name.lower():
            return Repo(r["full_name"], clone_pinned(r))
    dest = ROOT / "workspace" / full_name.replace("/", "__")
    if not (dest / ".git").exists():
        download(dest, f"https://github.com/{full_name}.git", "HEAD")
    return Repo(full_name, dest)
