"""Unified Swagger UI: one page with a drop-down to switch between the OpenAPI specs of all services.

Every service keeps its own spec (`/openapi.json`); the gateway proxies them as `/openapi/<service>.json`.
Because the gateway exposes the same paths as the services, "Try it out" works through the gateway.
"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from common.errors import NotFoundError, UpstreamError

router = APIRouter(include_in_schema=False)

SPECS = [
    ("API Gateway (aggregation)", "/openapi.json"),
    ("Auth Service", "/openapi/auth.json"),
    ("User Service", "/openapi/user.json"),
    ("Catalog Service", "/openapi/catalog.json"),
    ("Booking Service", "/openapi/booking.json"),
    ("Payment Service", "/openapi/payment.json"),
    ("Notification Service", "/openapi/notification.json"),
]

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Ticketing API docs</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"></head>
<body><div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
<script>
window.ui = SwaggerUIBundle({
  urls: __URLS__,
  "urls.primaryName": "Booking Service",
  dom_id: "#swagger-ui",
  presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
  layout: "StandaloneLayout",
  persistAuthorization: true,
  displayRequestDuration: true
});
</script></body></html>"""


@router.get("/docs")
async def docs() -> HTMLResponse:
    urls = json.dumps([{"name": name, "url": url} for name, url in SPECS])
    return HTMLResponse(PAGE.replace("__URLS__", urls))


@router.get("/openapi/{service}.json")
async def service_spec(service: str, request: Request) -> JSONResponse:
    upstream = request.app.state.upstreams.get(service)
    if upstream is None:
        raise NotFoundError("Unknown service")
    response = await upstream.request("GET", "/openapi.json")
    if response.status_code != 200:
        raise UpstreamError(f"{service} service did not return its OpenAPI spec")
    return JSONResponse(response.json())
