#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


plugins = sorted(Path(sys.argv[1]).iterdir())
requirements = []
for plugin in plugins:
    with zipfile.ZipFile(plugin) as archive:
        if "requirements.txt" in archive.namelist():
            requirements.extend(archive.read("requirements.txt").decode().splitlines())

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "requirements.txt"
    path.write_text("\n".join(requirements) + "\n")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(path)], check=True)

for plugin in plugins:
    with zipfile.ZipFile(plugin) as archive:
        metadata = json.loads(archive.read("mcdreforged.plugin.json"))
    entrypoint = metadata.get("entrypoint", metadata["id"])
    subprocess.run(
        [sys.executable, "-c", "import importlib,sys; sys.path.insert(0,sys.argv[1]); importlib.import_module(sys.argv[2])", str(plugin), entrypoint],
        check=True,
    )
    print(f"Validated {metadata['id']}@{metadata['version']}", flush=True)
