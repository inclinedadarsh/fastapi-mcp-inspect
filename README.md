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
Lists every registered route with its HTTP methods and total count.

### `show_endpoint_details(method, endpoint)`
Shows detailed information for a specific endpoint, including request/response
schemas and any referenced Pydantic models.

### `search_routes(query, method=None)`
Searches routes by path (case-insensitive) and optionally filters by HTTP method.

## Development

```bash
git clone https://github.com/inclinedadarsh/fastapi-mcp-inspect.git
cd fastapi-mcp-inspect
uv sync
```

## License

MIT
