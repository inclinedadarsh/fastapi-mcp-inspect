from __future__ import annotations

import types as py_types
from typing import TYPE_CHECKING, Annotated, Any, Union, get_args, get_origin

from fastapi.routing import APIRoute, _DefaultLifespan, _IncludedRouter
from fastmcp import FastMCP
from fastmcp.utilities.lifespan import combine_lifespans
from pydantic import BaseModel

if TYPE_CHECKING:
    from fastapi import FastAPI


def _get_api_routes(app):
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route.path, route.methods, route
        elif isinstance(route, _IncludedRouter):
            for ctx in route.effective_route_contexts():
                if isinstance(ctx.original_route, APIRoute):
                    yield ctx.path, ctx.methods, ctx.original_route


def _format_type(tp) -> str:
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
    lines = [model.__name__, "{"]
    for name, field in model.model_fields.items():
        tp = field.annotation
        type_str = _format_type(tp)
        lines.append(f"  {name}: {type_str}")
    lines.append("}")
    return "\n".join(lines)


def _collect_referenced_schemas(*models) -> dict[str, type[BaseModel]]:
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
    def __init__(self, app: FastAPI, mount_path: str = "/mcp"):
        self.app = app
        self.mcp = FastMCP("fastapi-mcp-inspect")
        self.mount_path = mount_path

        @self.mcp.tool()
        async def show_all_routes() -> str:
            routes: dict[str, set[str]] = {}
            for path, methods, _ in _get_api_routes(self.app):
                routes.setdefault(path, set()).update(methods)
            lines = []
            for path, methods in sorted(routes.items()):
                methods_str = ", ".join(sorted(methods))
                lines.append(f"---\nROUTE: {path}\nMETHODS: {methods_str}")
            total = len(routes)
            return f"Total available routes: {total}\n\n" + "\n".join(lines)

        @self.mcp.tool()
        async def show_endpoint_details(method: str, endpoint: str) -> str:
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

        mcp_asgi_app = self.mcp.http_app(path="/")

        if isinstance(app.router.lifespan_context, _DefaultLifespan):
            app.router.lifespan_context = mcp_asgi_app.lifespan
        else:
            app.router.lifespan_context = combine_lifespans(
                app.router.lifespan_context,
                mcp_asgi_app.lifespan,
            )

        app.mount(self.mount_path, mcp_asgi_app)
