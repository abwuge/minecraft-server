#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["tomli"]
# ///
"""Resolve a compatible Minecraft version + mod jar set across all configured mods.

Pulls version metadata from Modrinth and GitHub Releases, intersects the
supported MC versions across the *required* mods, picks the newest MC,
and prints a JSON document compatible with `mods.lock.json` to stdout.

Optional mods do not constrain the chosen MC version; if no jar exists for
the resolved MC, the script falls back to the newest jar that supports an
older patch in the same minor line.

Usage:
    python3 scripts/resolve-mods.py              # auto-pick newest MC
    python3 scripts/resolve-mods.py --mc 26.1.1  # pin a specific MC
    python3 scripts/resolve-mods.py --no-hash    # skip sha512 download for GH assets
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

import tomli

UA = "minecraft-server-resolve-mods/1.0"
DEFAULT_REGISTRY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mods.toml")

# Loaded from mods.toml at startup; see that file for the schema.
LOADER: str = "fabric"
MODS: list[dict] = []


def load_registry(path: str) -> None:
    global LOADER, MODS
    with open(path, "rb") as fh:
        data = tomli.load(fh)
    LOADER = data.get("loader", "fabric")
    MODS = list(data.get("mods", []))
    if not MODS:
        raise SystemExit(f"no mods configured in {path}")


# ---------- helpers ----------
def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def http_get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def parse_mc(v: str):
    parts = []
    for p in v.split("."):
        try:
            parts.append((0, int(p)))
        except ValueError:
            parts.append((1, p))
    return tuple(parts)


_BAD_SNIPPETS = ("snapshot", "pre", "-rc", "beta", "alpha")


def is_release_mc(v: str) -> bool:
    lv = v.lower()
    if any(s in lv for s in _BAD_SNIPPETS):
        return False
    # Snapshots like "24w03a"
    if re.match(r"^\d+w\d+[a-z]?$", lv):
        return False
    return True


def stream_sha512(url: str) -> str:
    h = hashlib.sha512()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ---------- per-source fetchers ----------
def fetch_modrinth(project: str) -> dict:
    """Return mc_version -> record dict (filename, url, sha512, version, _date)."""
    url = f'https://api.modrinth.com/v2/project/{project}/version?loaders=%5B%22{LOADER}%22%5D'
    versions = http_get_json(url)
    out: dict = {}
    for v in versions:
        if v.get("version_type") != "release":
            continue
        files = v.get("files") or []
        primary = next((f for f in files if f.get("primary")), files[0] if files else None)
        if not primary:
            continue
        rec = {
            "filename": primary["filename"],
            "url": primary["url"],
            "sha512": primary["hashes"]["sha512"],
            "version": v["version_number"],
            "_date": v["date_published"],
        }
        for gv in v.get("game_versions", []):
            cur = out.get(gv)
            if not cur or rec["_date"] > cur["_date"]:
                out[gv] = rec
    return out


def fetch_fabric_loader(mc_version: str) -> str:
    """Return the latest stable Fabric Loader version that supports MC `mc_version`."""
    data = http_get_json(f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}")
    stable = [d["loader"]["version"] for d in data if d["loader"].get("stable")]
    if not stable:
        # Fall back to whatever is newest if no loader is marked stable yet.
        stable = [d["loader"]["version"] for d in data]
    if not stable:
        raise SystemExit(f"no Fabric loader available for MC {mc_version}")
    return stable[0]  # API returns newest first


def fetch_fabric_installer() -> str:
    """Return the latest stable Fabric Installer version."""
    data = http_get_json("https://meta.fabricmc.net/v2/versions/installer")
    stable = [d["version"] for d in data if d.get("stable")]
    if not stable:
        stable = [d["version"] for d in data]
    if not stable:
        raise SystemExit("no Fabric installer versions returned")
    return stable[0]


def fetch_github(mod: dict) -> dict:
    repo = mod["repo"]
    pat = re.compile(mod["asset_re"])
    url = f"https://api.github.com/repos/{repo}/releases?per_page=30"
    releases = http_get_json(url)
    out: dict = {}
    for r in releases:
        if r.get("prerelease") or r.get("draft"):
            continue
        tag = r.get("tag_name", "")
        if any(s in tag.lower() for s in ("beta", "alpha", "rc", "snapshot")):
            continue
        for a in r.get("assets", []):
            m = pat.match(a["name"])
            if not m:
                continue
            mc = m.group("mc")
            rec = {
                "filename": a["name"],
                "url": a["browser_download_url"],
                "sha512": None,  # filled later via stream_sha512 if needed
                "version": tag,
                "_date": r["published_at"],
            }
            cur = out.get(mc)
            if not cur or rec["_date"] > cur["_date"]:
                out[mc] = rec
    return out


# ---------- core resolve ----------
def _fetch_one(mod: dict) -> tuple[str, dict]:
    name = mod["name"]
    log(f"[{name}] fetching ({mod['source']})")
    if mod["source"] == "modrinth":
        return name, fetch_modrinth(mod["project"])
    if mod["source"] == "github_release":
        return name, fetch_github(mod)
    raise ValueError(mod["source"])


def collect(workers: int = 8) -> tuple[dict, set]:
    per_mod: dict = {}
    optional: set = {m["name"] for m in MODS if m.get("optional")}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for name, vmap in ex.map(_fetch_one, MODS):
            per_mod[name] = vmap
    return per_mod, optional


def expand_fuzzy(per_mod: dict) -> None:
    """For mods marked fuzzy=True, copy their X.Y record to every X.Y.* MC seen elsewhere."""
    all_mcs = {mc for vmap in per_mod.values() for mc in vmap if is_release_mc(mc)}
    for mod in MODS:
        if not mod.get("fuzzy"):
            continue
        vmap = per_mod[mod["name"]]
        additions = {}
        for mc, rec in list(vmap.items()):
            for cand in all_mcs:
                if cand == mc or not cand.startswith(mc + "."):
                    continue
                if cand not in vmap:
                    additions[cand] = rec
        vmap.update(additions)


def pick_mc(per_mod: dict, optional: set, pin: str | None) -> str:
    required_sets = []
    for mod in MODS:
        if mod["name"] in optional:
            continue
        mcs = {mc for mc in per_mod[mod["name"]] if is_release_mc(mc)}
        required_sets.append((mod["name"], mcs))
    if not required_sets:
        raise SystemExit("no required mods configured")
    common = set.intersection(*(s for _, s in required_sets))
    if pin:
        if pin not in common:
            log("ERROR: pinned MC not supported by all required mods")
            for n, s in required_sets:
                if pin not in s:
                    log(f"  missing in: {n} (has: {sorted(s, key=parse_mc)[-5:]})")
            raise SystemExit(2)
        return pin
    if not common:
        log("ERROR: no MC version satisfies all required mods")
        for n, s in required_sets:
            log(f"  {n}: {sorted(s, key=parse_mc)[-6:] or '(none)'}")
        raise SystemExit(1)
    return max(common, key=parse_mc)


def build_lock(per_mod: dict, optional: set, target_mc: str, fill_hash: bool) -> dict:
    mods_out = []
    for mod in MODS:
        name = mod["name"]
        vmap = per_mod[name]
        if target_mc in vmap:
            r = vmap[target_mc]
        elif name in optional:
            cand = [mc for mc in vmap if is_release_mc(mc) and parse_mc(mc) <= parse_mc(target_mc)]
            if not cand:
                log(f"  [optional skip] {name}: no version <= {target_mc}")
                continue
            best = max(cand, key=parse_mc)
            r = vmap[best]
            log(f"  [optional fallback] {name}: {best} jar -> running on {target_mc}")
        else:
            raise RuntimeError(f"required mod {name} has no record for {target_mc}")

        if fill_hash and r["sha512"] is None:
            log(f"  [hash] downloading {r['filename']} to compute sha512 …")
            r = dict(r)
            r["sha512"] = stream_sha512(r["url"])

        mods_out.append({
            "name":     name,
            "filename": r["filename"],
            "url":      r["url"],
            "sha512":   r["sha512"],
            "version":  r["version"],
        })
    return {
        "mc_version": target_mc,
        "loader":     LOADER,
        "mods":       mods_out,
    }


def _download_one(entry: dict, out_dir: str) -> dict:
    """Download a single jar, verify or compute sha512, return updated entry."""
    target = os.path.join(out_dir, entry["filename"])
    h = hashlib.sha512()
    req = urllib.request.Request(entry["url"], headers={"User-Agent": UA})
    tmp = target + ".tmp"
    with urllib.request.urlopen(req, timeout=180) as resp, open(tmp, "wb") as fh:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            h.update(chunk)
            fh.write(chunk)
    digest = h.hexdigest()
    expected = entry.get("sha512")
    if expected and expected != digest:
        os.unlink(tmp)
        raise RuntimeError(f"sha512 mismatch for {entry['filename']}: expected {expected} got {digest}")
    os.replace(tmp, target)
    log(f"  [ok] {entry['filename']} ({os.path.getsize(target)} bytes)")
    out = dict(entry)
    out["sha512"] = digest
    return out


def download_all(lock: dict, out_dir: str, workers: int = 6) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    log(f"downloading {len(lock['mods'])} jars -> {out_dir}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda e: _download_one(e, out_dir), lock["mods"]))
    lock = dict(lock)
    lock["mods"] = results
    return lock


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mc", help="pin a specific MC version instead of auto-picking")
    ap.add_argument("--no-hash", action="store_true",
                    help="skip streaming GitHub-sourced jars to compute sha512 "
                         "(ignored when --download is set)")
    ap.add_argument("--download", metavar="DIR",
                    help="download all resolved jars into DIR (parallel); also fills sha512")
    ap.add_argument("--workers", type=int, default=8, help="parallel HTTP workers (default 8)")
    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
                    help="path to mods.toml registry (default: ../mods.toml)")
    args = ap.parse_args()

    load_registry(args.registry)
    per_mod, optional = collect(workers=args.workers)
    expand_fuzzy(per_mod)
    target_mc = pick_mc(per_mod, optional, args.mc)
    log(f"=> resolved MC: {target_mc}")
    log(f"=> resolving Fabric loader / installer for MC {target_mc}")
    loader_v    = fetch_fabric_loader(target_mc)
    installer_v = fetch_fabric_installer()
    log(f"=> Fabric loader: {loader_v}, installer: {installer_v}")
    fill_hash = (not args.no_hash) and (args.download is None)
    lock = build_lock(per_mod, optional, target_mc, fill_hash=fill_hash)
    lock["fabric_loader_version"]    = loader_v
    lock["fabric_installer_version"] = installer_v
    if args.download:
        lock = download_all(lock, args.download, workers=args.workers)
    json.dump(lock, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        log(f"HTTP error: {e.code} {e.reason} on {e.url}")
        sys.exit(3)
