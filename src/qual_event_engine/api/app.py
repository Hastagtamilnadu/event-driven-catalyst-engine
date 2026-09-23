from __future__ import annotations

"""Local FastAPI application. Routes are the §33.1 contract in `routes.py`."""

from fastapi import FastAPI

from qual_event_engine.api.routes import router

app = FastAPI(title="Qualitative Event Engine", version="0.1.0")
app.include_router(router)
