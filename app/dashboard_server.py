"""Standalone web server for the SmartPay demo dashboard."""

from __future__ import annotations

import contextlib

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from app import config, history, runtime
from app.admin_dashboard import render_admin_dashboard
from app.dashboard import render_alex_dashboard
from app.providers.open_finance import SyntheticAlexProvider

provider = SyntheticAlexProvider()


async def demo_alex(_: Request) -> HTMLResponse:
    profile = provider.get_profile(config.DEMO_CUSTOMER_ID)
    return HTMLResponse(render_alex_dashboard(profile))


async def demo_alex_json(_: Request) -> JSONResponse:
    profile = provider.get_profile(config.DEMO_CUSTOMER_ID)
    return JSONResponse(profile.model_dump(mode="json"))


async def admin_dashboard(_: Request) -> HTMLResponse:
    return HTMLResponse(render_admin_dashboard())


async def query_history(_: Request) -> JSONResponse:
    """What has been asked, so the open page can notice a new question and reload."""
    entries = history.load()
    latest = entries[0] if entries else None
    return JSONResponse(
        {
            "count": len(entries),
            "latest": (
                {"key": latest.get("key"), "asked_at": latest.get("asked_at")}
                if latest else None
            ),
            "entries": [
                {k: v for k, v in e.items() if k != "plan"} for e in entries
            ],
        }
    )


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "smartpay-dashboard", **runtime.status()})


app = Starlette(
    routes=[
        Route("/health", health),
        Route("/admin", admin_dashboard),
        Route("/", demo_alex),
        Route("/history.json", query_history),
        Route("/demo/alex", demo_alex),
        Route("/demo/alex.json", demo_alex_json),
    ]
)
app.mount("/static", StaticFiles(directory=config.ROOT / "app" / "static"), name="static")


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        if config.RELOAD:
            uvicorn.run(
                "app.dashboard_server:app", host=config.HOST, port=config.DASHBOARD_PORT,
                log_level="info", reload=True, reload_dirs=["app"],
            )
        else:
            uvicorn.run(app, host=config.HOST, port=config.DASHBOARD_PORT, log_level="info")


if __name__ == "__main__":
    main()