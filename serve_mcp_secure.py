import os
import secrets

import uvicorn
from starlette.responses import JSONResponse
from tflex_harness.mcp_server import create_server


class RequireApiKey:
    def __init__(self, app, key):
        self.app = app
        self.expected = ("Bearer " + key).encode("ascii")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            values = [
                value
                for name, value in scope.get("headers", [])
                if name.lower() == b"authorization"
            ]
            authorized = (
                len(values) == 1
                and secrets.compare_digest(values[0], self.expected)
            )
            if not authorized:
                headers = scope.get("headers", [])
                print(
                    "AUTH_CHECK:",
                    {
                        "path": scope.get("path"),
                        "authorization_count": len(values),
                        "authorization_has_bearer_prefix": any(
                            v.lower().startswith(b"bearer ") for v in values
                        ),
                        "authorization_matches_raw_key": any(
                            secrets.compare_digest(v, self.expected[7:])
                            for v in values
                        ),
                        "credential_header_checks": [
                            {
                                "header": name.decode("ascii", errors="replace"),
                                "matches_raw_key": secrets.compare_digest(
                                    value, self.expected[7:]
                                ),
                                "matches_bearer_key": secrets.compare_digest(
                                    value, self.expected
                                ),
                            }
                            for name, value in headers
                            if any(
                                part in name.lower()
                                for part in (b"auth", b"key", b"token")
                            )
                        ],
                    },
                    flush=True,
                )
                response = JSONResponse(
                    {"error": "Unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


def main():
    key = os.environ.get("TFLEX_MCP_API_KEY", "")
    if len(key) < 32:
        raise SystemExit("TFLEX_MCP_API_KEY is missing or too short")

    server = create_server()
    app = RequireApiKey(server.streamable_http_app(), key)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        access_log=False,
    )


if __name__ == "__main__":
    main()
