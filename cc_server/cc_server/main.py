"""Command Center server. Binds 127.0.0.1:8585. Serves /api and the built web app."""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from cc_sdk.control import control_dir
from cc_sdk.ledger import var_dir
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import api, riskd
from .alerts import Alerter, write_default_config

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "cc_web" / "dist"


def setup_logging() -> None:
    logdir = var_dir() / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='{"t":"%(asctime)s","lvl":"%(levelname)s","src":"%(name)s","msg":%(message)r}',
                        handlers=[logging.FileHandler(logdir / "server.log"), logging.StreamHandler(sys.stdout)])


async def riskd_loop(stop: asyncio.Event) -> None:
    L = api.L()
    alerter = Alerter(L)
    while not stop.is_set():
        try:
            await asyncio.to_thread(riskd.tick, L, alerter)
        except Exception:  # noqa: BLE001
            logging.getLogger("riskd").exception("tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
        except TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    control_dir().mkdir(parents=True, exist_ok=True)
    write_default_config()
    stop = asyncio.Event()
    task = asyncio.create_task(riskd_loop(stop))
    yield
    stop.set()
    await task


app = FastAPI(title="Trading Bot Command Center", version="0.1.0", lifespan=lifespan)
app.include_router(api.router)

if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(DIST / "index.html")


if __name__ == "__main__":
    import uvicorn
    reload = "--reload" in sys.argv
    uvicorn.run("cc_server.main:app", host="127.0.0.1", port=8585, reload=reload)
