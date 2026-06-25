from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.routing import _DefaultLifespan
from fastmcp import FastMCP
from fastmcp.utilities.lifespan import combine_lifespans

if TYPE_CHECKING:
    from fastapi import FastAPI


class FastAPIInspect:
    def __init__(self, app: FastAPI, mount_path: str = "/mcp"):
        self.app = app
        self.mcp = FastMCP("fastapi-mcp-inspect")
        self.mount_path = mount_path

        @self.mcp.tool()
        async def hello() -> str:
            return "world"

        mcp_asgi_app = self.mcp.http_app(path="/")

        if isinstance(app.router.lifespan_context, _DefaultLifespan):
            app.router.lifespan_context = mcp_asgi_app.lifespan
        else:
            app.router.lifespan_context = combine_lifespans(
                app.router.lifespan_context,
                mcp_asgi_app.lifespan,
            )

        app.mount(self.mount_path, mcp_asgi_app)
