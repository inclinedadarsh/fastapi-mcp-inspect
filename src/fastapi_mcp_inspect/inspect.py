from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastapi.routing import APIRoute, _DefaultLifespan, _IncludedRouter
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
        async def show_all_routes() -> str:
            routes: dict[str, set[str]] = {}
            for route in self.app.routes:
                if isinstance(route, APIRoute):
                    routes.setdefault(route.path, set()).update(route.methods)
                elif isinstance(route, _IncludedRouter):
                    for ctx in route.effective_route_contexts():
                        if isinstance(ctx.original_route, APIRoute):
                            routes.setdefault(ctx.path, set()).update(ctx.methods)
            result = [
                {"path": path, "methods": sorted(methods)}
                for path, methods in sorted(routes.items())
            ]
            return json.dumps(result, indent=2)

        mcp_asgi_app = self.mcp.http_app(path="/")

        if isinstance(app.router.lifespan_context, _DefaultLifespan):
            app.router.lifespan_context = mcp_asgi_app.lifespan
        else:
            app.router.lifespan_context = combine_lifespans(
                app.router.lifespan_context,
                mcp_asgi_app.lifespan,
            )

        app.mount(self.mount_path, mcp_asgi_app)
