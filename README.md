# fastapi-mcp-inspect

Mount an MCP server onto your FastAPI application to let AI agents inspect
your routes, endpoints, and schemas at runtime.

## Installation

```bash
uv add fastapi-mcp-inspect
# or using pip: pip install fastapi-mcp-inspect
```

## Quick Start

```python
from fastapi import FastAPI
from fastapi_mcp_inspect import FastAPIInspect

app = FastAPI()
FastAPIInspect(app, mount_path="/mcp")
```

Any LLM with MCP support can now connect to your app's `/mcp` endpoint and
inspect all registered routes.

## MCP Tools

### `show_all_routes()`
Lists every registered route with its HTTP methods, summary, description, and
total count.

### `show_endpoint_details(method, endpoint)`
Shows detailed information for a specific endpoint, including request/response
schemas and any referenced Pydantic models.

### `search_routes(query, method=None, search_in_summary=False, tags=None)`
Searches routes by path (case-insensitive) with optional filters:
- `method` — filter by HTTP method (e.g. GET, POST).
- `search_in_summary` — when True, also matches against summaries and descriptions.
- `tags` — filter by tag names (OR logic — any match).

### `list_all_tags()`
Lists every unique tag used across API routes with route counts.

### `get_schema_definition(schema_name)`
Returns the full field-level definition of a Pydantic schema used by any
endpoint. Lookup is case-insensitive.

## Development

```bash
git clone https://github.com/inclinedadarsh/fastapi-mcp-inspect.git
cd fastapi-mcp-inspect
uv sync
```

## License

MIT
