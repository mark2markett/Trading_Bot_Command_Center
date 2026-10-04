"""Load actual bot code from an isolated source copy; never copy runtime/credentials."""
from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import sys
from pathlib import Path
from uuid import uuid4

from scripts.closed_loop_guard import SandboxError, validate_sandbox

FOLDERS = {"gap_go": "gap_go_bot", "nr7": "nr7_bot", "sip_orb": "sip_orb",
           "spy_mr": "spy_mr_bot", "gap_go_spread": "gap_go_spread_bot"}


def load_sources(repo: Path, runtime: Path) -> dict:
    expected = runtime.resolve()
    runtime = validate_sandbox(repo, os.getenv("CC_VAR"))
    if runtime != expected or os.getenv("MODE", "paper") != "paper":
        raise SandboxError("Source loading requires the validated paper worker environment")
    mirror = runtime.parent / "imports" / "bots"
    (runtime / "control").mkdir(parents=True, exist_ok=True)
    for folder in FOLDERS.values():
        target = mirror / folder
        target.mkdir(parents=True, exist_ok=True)
        for source in (repo / "bots" / folder).glob("*.py"):
            shutil.copyfile(source, target / source.name)
    names = ("cc", "broker", "strategy", "gap_go_rules", "nr7_rules", "sip_orb_rules", "sip_scanner")
    previous = {name: sys.modules.pop(name, None) for name in names}
    paths = sys.path[:]
    modules = {}
    try:
        sys.path[:0] = [str(mirror / folder) for folder in FOLDERS.values()]
        for bot_id, folder in FOLDERS.items():
            name = f"_closed_loop_{bot_id}_{uuid4().hex}"
            spec = importlib.util.spec_from_file_location(name, mirror / folder / "bot.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            manifest = module.cc.MANIFEST if bot_id == "spy_mr" else module.MANIFEST
            if manifest.mode != "paper":
                raise SandboxError("An imported manifest is not paper-only")
            modules[bot_id] = module
    finally:
        sys.path[:] = paths
        for name in names:
            sys.modules.pop(name, None)
            if previous[name] is not None:
                sys.modules[name] = previous[name]
    logging.getLogger("bot").setLevel(logging.ERROR)
    return modules


def load_fleet(repo: Path, runtime: Path) -> tuple[dict, dict]:
    from cc_sdk import Bot

    modules = load_sources(repo, runtime)
    bots = {}
    for bot_id, module in modules.items():
        bots[bot_id] = (module.cc.bot if bot_id == "spy_mr" else
                        Bot(module.MANIFEST, db_path=runtime / "cc.db", control_dir=runtime / "control"))
        if bots[bot_id] is None:
            raise RuntimeError("Daily bot SDK initialization failed")
        bots[bot_id].L.heartbeat(bot_id, "session" if bot_id != "spy_mr" else "decide", True, "SYNTHETIC harness")
    return bots, modules
