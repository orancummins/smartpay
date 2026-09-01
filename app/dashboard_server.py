"""Standalone web server for the SmartPay demo dashboard."""

from __future__ import annotations

import contextlib

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from app import config
from app.dashboard import render_alex_dashboard
from app.providers.open_finance import SyntheticAlexProvider

provider = SyntheticAlexProvider()


async def demo_alex(_: Request) -> HTMLResponse:
    profile = provider.get_profile(config.DEMO_CUSTOMER_ID)
    return HTMLResponse(render_alex_dashboard(profile))


async def demo_alex_json(_: Request) -> JSONResponse:
    profile = provider.get_profile(config.DEMO_CUSTOMER_ID)
    return JSONResponse(profile.model_dump(mode="json"))


app = Starlette(
    routes=[
        Route("/", demo_alex),
        Route("/demo/alex", demo_alex),
        Route("/demo/alex.json", demo_alex_json),
    ]
)
app.mount("/static", StaticFiles(directory=config.ROOT / "app" / "static"), name="static")


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        uvicorn.run(app, host=config.HOST, port=config.DASHBOARD_PORT, log_level="info")


if __name__ == "__main__":
    main()