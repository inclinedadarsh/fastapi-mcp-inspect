from __future__ import annotations

import types as py_types
from typing import TYPE_CHECKING, Annotated, Any, Union, get_args, get_origin

if TYPE_CHECKING:
    from collections.abc import Generator

    from fastapi import FastAPI

from fastapi.routing import APIRoute, _DefaultLifespan, _IncludedRouter
from fastmcp import FastMCP
from fastmcp.utilities.lifespan import combine_lifespans
from pydantic import BaseModel


def _get_api_routes(
    app: FastAPI,
) -> Generator[tuple[str, set[str], APIRoute]]:
    """Yield (path, methods, route) tuples for every API route in the app.

    Handles both direct APIRoute instances and routes nested inside
    _IncludedRouter (from FastAPI sub-mounting).
    """
    for route in app.routes:
        if isinstance(route, APIRoute):
            assert route.methods is not None
            yield route.path, route.methods, route
        elif isinstance(route, _IncludedRouter):
            for ctx in route.effective_route_contexts():
                if isinstance(ctx.original_route, APIRoute):
                    yield ctx.path, ctx.methods, ctx.original_route


def _format_type(tp) -> str:
    """Convert a Python type annotation into a human-readable string.

    Handles Annotated, Union, list, dict, None, Any, and common primitives.
    Falls back to __name__ for unrecognized types.
    """
    origin = get_origin(tp)
    args = get_args(tp)

    if origin is Annotated:
        return _format_type(args[0])

    if origin is Union or origin is py_types.UnionType:
        arg_list = list(args)
        has_none = type(None) in arg_list
        non_none = [a for a in arg_list if a is not type(None)]
        formatted = " | ".join(_format_type(a) for a in non_none)
        return f"{formatted} | null" if has_none else formatted

    if origin is list:
        return f"list[{', '.join(_format_type(a) for a in args)}]"

    if origin is dict:
        return f"dict[{', '.join(_format_type(a) for a in args)}]"

    if tp is type(None):
        return "null"

    if tp is Any:
        return "any"

    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        bytes: "bytes",
    }
    if tp in type_map:
        return type_map[tp]

    if hasattr(tp, "__name__"):
        name = tp.__name__
        if name == "datetime":
            return "datetime"
        if name == "UUID":
            return "UUID"
        return name

    return str(tp)


def _get_schema_text(model: type[BaseModel]) -> str:
    """Render a Pydantic model as a human-readable schema block.

    Example:
        Item {
          name: string
          price: number
        }
    """
    lines = [model.__name__, "{"]
    for name, field in model.model_fields.items():
        tp = field.annotation
        type_str = _format_type(tp)
        lines.append(f"  {name}: {type_str}")
    lines.append("}")
    return "\n".join(lines)


def _collect_referenced_schemas(*models) -> dict[str, type[BaseModel]]:
    """Walk Pydantic model fields to collect all referenced schemas.

    Recursively follows Annotated, Union, list, and dict types to find
    nested BaseModel classes. Returns a deduplicated name-to-model map.
    """
    collected: dict[str, type[BaseModel]] = {}

    def _walk(tp):
        origin = get_origin(tp)
        args = get_args(tp)

        if isinstance(tp, type) and issubclass(tp, BaseModel):
            name = tp.__name__
            if name not in collected:
                collected[name] = tp
                for field in tp.model_fields.values():
                    _walk(field.annotation)
            return

        if origin is Annotated:
            _walk(args[0])
            return

        if origin is Union or origin is py_types.UnionType:
            for a in args:
                _walk(a)
            return

        if origin is list:
            for a in args:
                _walk(a)
            return

        if origin is dict:
            for a in args:
                _walk(a)
            return

    for model in models:
        if model is not None:
            _walk(model)

    return collected


class FastAPIInspect:
    """Mount an MCP server onto a FastAPI app for LLM-powered route inspection.

    Registers tools that let AI agents list routes, view endpoint details,
    and search endpoints at runtime.

    Usage:
        app = FastAPI()
        FastAPIInspect(app, mount_path="/mcp")
    """

    def __init__(self, app: FastAPI, mount_path: str = "/mcp"):
        """Attach an MCP inspect server to a FastAPI application.

        Args:
            app: The FastAPI application to inspect.
            mount_path: URL path where the MCP server will be mounted
                (default: "/mcp").
        """
        self.app = app
        self.mcp = FastMCP("fastapi-mcp-inspect")
        self.mount_path = mount_path

        @self.mcp.tool()
        async def show_all_routes() -> str:
            """List every registered API route with its HTTP methods."""
            route_map: dict[str, tuple[set[str], APIRoute]] = {}
            for path, methods, route in _get_api_routes(self.app):
                if path in route_map:
                    route_map[path][0].update(methods)
                else:
                    route_map[path] = (methods, route)
            lines = []
            for path, (methods, route) in sorted(route_map.items()):
                methods_str = ", ".join(sorted(methods))
                lines.append("---")
                lines.append(f"ROUTE: {path}")
                lines.append(f"METHODS: {methods_str}")
                if route.summary:
                    lines.append(f"SUMMARY: {route.summary}")
                if route.description:
                    desc = route.description.strip()
                    if desc:
                        desc_lines = desc.split("\n")
                        lines.append(f"DESCRIPTION: {desc_lines[0].strip()}")
                        for line in desc_lines[1:]:
                            stripped = line.strip()
                            if stripped:
                                lines.append(f"  {stripped}")
            total = len(route_map)
            return f"Total available routes: {total}\n\n" + "\n".join(lines)

        @self.mcp.tool()
        async def show_endpoint_details(method: str, endpoint: str) -> str:
            """Show request/response schemas and metadata for a specific endpoint.

            Args:
                method: HTTP method (e.g. GET, POST).
                endpoint: URL path of the endpoint.
            """
            method_upper = method.upper()
            matched = None
            for path, methods, route in _get_api_routes(self.app):
                if path == endpoint and method_upper in methods:
                    matched = (path, methods, route)
                    break

            if matched is None:
                return f"Route not found: {method_upper} {endpoint}"

            path, _methods, route = matched

            req_model = None
            if route.body_field is not None:
                req_model = getattr(route.body_field.field_info, "annotation", None)

            resp_model = route.response_model

            schemas = _collect_referenced_schemas(req_model, resp_model)

            lines = []
            lines.append("=" * 25)
            lines.append("ENDPOINTS")
            lines.append("-" * 25)
            lines.append("")
            lines.append(f"{method_upper} {path}")

            summary = getattr(route, "summary", None) or ""
            if summary:
                lines.append(summary)

            description = getattr(route, "description", None) or ""
            if description:
                desc_text = description.strip()
                if desc_text:
                    for line in desc_text.split("\n"):
                        lines.append(line.strip())

            if req_model is not None:
                lines.append("")
                lines.append("Request Body:")
                req_name = (
                    req_model.__name__
                    if hasattr(req_model, "__name__")
                    else str(req_model)
                )
                lines.append(f"  {req_name}")

            if resp_model is not None:
                status_code = getattr(route, "status_code", 200)
                lines.append("")
                lines.append(f"Response ({status_code}):")
                resp_name = (
                    resp_model.__name__
                    if hasattr(resp_model, "__name__")
                    else str(resp_model)
                )
                lines.append(f"  {resp_name}")

            if schemas:
                lines.append("")
                lines.append("=" * 25)
                lines.append("SCHEMAS")
                lines.append("-" * 25)
                lines.append("")
                for name in sorted(schemas.keys()):
                    model = schemas[name]
                    lines.append(_get_schema_text(model))
                    lines.append("")

            return "\n".join(lines)

        @self.mcp.tool()
        async def search_routes(query: str, method: str | None = None) -> str:
            """Search for routes by path and optionally filter by HTTP method.

            Args:
                query: Substring to match against route paths (case-insensitive).
                method: Optional HTTP method filter (e.g. GET, POST).
            """
            route_map: dict[str, tuple[set[str], APIRoute]] = {}
            for path, methods, route in _get_api_routes(self.app):
                if query.lower() in path.lower() and (
                    method is None or method.upper() in methods
                ):
                    if path in route_map:
                        route_map[path][0].update(methods)
                    else:
                        route_map[path] = (methods, route)
            if not route_map:
                msg = f"No routes found matching query: {query}"
                if method is not None:
                    msg += f" with method: {method.upper()}"
                return msg
            lines = []
            for path, (methods, route) in sorted(route_map.items()):
                methods_str = ", ".join(sorted(methods))
                lines.append("---")
                lines.append(f"ROUTE: {path}")
                lines.append(f"METHODS: {methods_str}")
                if route.summary:
                    lines.append(f"SUMMARY: {route.summary}")
                if route.description:
                    desc = route.description.strip()
                    if desc:
                        desc_lines = desc.split("\n")
                        lines.append(f"DESCRIPTION: {desc_lines[0].strip()}")
                        for line in desc_lines[1:]:
                            stripped = line.strip()
                            if stripped:
                                lines.append(f"  {stripped}")
            total = len(route_map)
            header = f"Found {total} route(s) matching query: {query}"
            return header + "\n\n" + "\n".join(lines)

        mcp_asgi_app = self.mcp.http_app(path="/")

        if isinstance(app.router.lifespan_context, _DefaultLifespan):
            app.router.lifespan_context = mcp_asgi_app.lifespan
        else:
            app.router.lifespan_context = combine_lifespans(
                app.router.lifespan_context,
                mcp_asgi_app.lifespan,
            )

        app.mount(self.mount_path, mcp_asgi_app)
