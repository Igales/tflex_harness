import os
import re
import secrets
from pathlib import Path
from typing import Literal

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

from tflex_harness.docs_search import DocsSearch


# Библиотека располагается рядом с этим серверным скриптом.
#
# verified_macros/
#   example_v1/
#     macro.cs
#     README.md
#
# README.md необязателен.
MACROS_DIR = Path(__file__).resolve().parent / "verified_macros"

# Максимальные размеры возвращаемых файлов.
MAX_CODE_BYTES = 512 * 1024
MAX_README_BYTES = 64 * 1024

# Допустимы только простые имена папок.
MACRO_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")


class RequireApiKey:
    """Проверка ключа перед передачей HTTP-запроса MCP-серверу."""

    def __init__(self, app, key: str):
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
                # Значения заголовков и сам ключ не журналируются.
                print(
                    "AUTH_CHECK: request rejected; "
                    f"authorization_count={len(values)}",
                    flush=True,
                )

                response = JSONResponse(
                    {"error": "Unauthorized"},
                    status_code=401,
                    headers={
                        "WWW-Authenticate": "Bearer",
                        "Cache-Control": "no-store",
                    },
                )
                await response(scope, receive, send)
                return

        # Служебные события ASGI, включая lifespan,
        # передаются приложению без изменений.
        await self.app(scope, receive, send)


def get_macro_dir(macro_id: str) -> Path:
    """Проверить идентификатор и получить безопасный путь к примеру."""

    if not MACRO_ID_PATTERN.fullmatch(macro_id):
        raise ValueError(
            "Invalid macro_id. Use 1-80 Latin letters, digits, "
            "underscores or hyphens; start with a letter or digit."
        )

    root = MACROS_DIR.resolve()
    candidate = (root / macro_id).resolve()

    # После разрешения символических ссылок и junction папка
    # должна оставаться непосредственным потомком библиотеки.
    if candidate.parent != root:
        raise ValueError("Macro directory is outside the library.")

    if not candidate.is_dir():
        raise ValueError("Macro directory was not found.")

    return candidate


def read_allowed_file(
    macro_dir: Path,
    filename: str,
    max_bytes: int,
    optional: bool = False,
) -> str:
    """Прочитать только разрешённый файл внутри папки примера."""

    if filename not in {"macro.cs", "README.md"}:
        raise ValueError("File is not allowed.")

    path = (macro_dir / filename).resolve()

    # Не разрешаем перенаправлять файл за пределы папки примера.
    if path.parent != macro_dir:
        raise ValueError("File points outside the macro directory.")

    if not path.exists():
        if optional:
            return ""
        raise ValueError("Required file was not found: " + filename)

    if not path.is_file():
        raise ValueError("Not a regular file: " + filename)

    # Читаем с ограничением объёма.
    with path.open("rb") as stream:
        content = stream.read(max_bytes + 1)

    if len(content) > max_bytes:
        raise ValueError("File is too large: " + filename)

    # Поддерживаются UTF-8 с BOM и без BOM.
    return content.decode("utf-8-sig")


def main():
    key = os.environ.get("TFLEX_MCP_API_KEY", "")

    if len(key) < 32:
        raise SystemExit("TFLEX_MCP_API_KEY is missing or too short")

    # Ключ, созданный нашим скриптом, состоит из ASCII-символов.
    # Проверяем значение до запуска HTTP-сервера.
    try:
        key.encode("ascii")
    except UnicodeEncodeError:
        raise SystemExit("TFLEX_MCP_API_KEY must contain ASCII characters")

    if any(character.isspace() for character in key):
        raise SystemExit("TFLEX_MCP_API_KEY must not contain whitespace")

    server = FastMCP("tflex-docs-readonly")
    docs = DocsSearch()

    @server.tool()
    def search_tflex_docs(
        query: str,
        scope: Literal["symbols", "types", "chm", "all"] = "all",
        limit: int = 5,
    ) -> dict:
        """Search T-FLEX API documentation. Does not execute CAD code.

        Installed CAD API version: 17.0.85.0.
        Reference documentation includes version 17.1.30.0;
        verify compatibility before using API members.
        """
        return docs.search(
            query=query,
            scope=scope,
            limit=max(1, min(limit, 20)),
        )

    @server.tool()
    def list_verified_macros() -> dict:
        """List locally saved T-FLEX C# macro examples.

        Reads only the verified_macros library.
        Does not execute code or independently verify the examples.
        Use read_verified_macro to retrieve complete source code.
        """
        if not MACROS_DIR.exists():
            return {
                "ok": True,
                "macros": [],
                "count": 0,
                "message": "The verified_macros directory does not exist.",
            }

        items = []

        for entry in sorted(
            MACROS_DIR.iterdir(),
            key=lambda item: item.name.lower(),
        ):
            if not MACRO_ID_PATTERN.fullmatch(entry.name):
                continue

            try:
                macro_dir = get_macro_dir(entry.name)

                code = read_allowed_file(
                    macro_dir,
                    "macro.cs",
                    MAX_CODE_BYTES,
                )

                readme = read_allowed_file(
                    macro_dir,
                    "README.md",
                    MAX_README_BYTES,
                    optional=True,
                )

                items.append({
                    "macro_id": entry.name,
                    "description": readme[:2000],
                    "has_readme": bool(readme),
                    "code_lines": len(code.splitlines()),
                })

            except (OSError, ValueError) as exc:
                items.append({
                    "macro_id": entry.name,
                    "error": str(exc),
                })

        return {
            "ok": True,
            "macros": items,
            "count": len(items),
        }

    @server.tool()
    def read_verified_macro(macro_id: str) -> dict:
        """Read a complete saved T-FLEX C# macro and its README.

        Supply a macro_id returned by list_verified_macros.
        Returns source as text only; never compiles or executes it.
        README verification claims are user-maintained metadata,
        not an independent verification by this server.
        """
        try:
            macro_dir = get_macro_dir(macro_id)

            code = read_allowed_file(
                macro_dir,
                "macro.cs",
                MAX_CODE_BYTES,
            )

            readme = read_allowed_file(
                macro_dir,
                "README.md",
                MAX_README_BYTES,
                optional=True,
            )

            return {
                "ok": True,
                "macro_id": macro_id,
                "language": "csharp",
                "code": code,
                "readme": readme,
            }

        except (OSError, ValueError) as exc:
            return {
                "ok": False,
                "macro_id": macro_id,
                "error": str(exc),
            }

    app = RequireApiKey(
        server.streamable_http_app(),
        key,
    )

    print(
        "T-FLEX Docs: API key authentication enabled; "
        "expected header: Authorization: Bearer <key>",
        flush=True,
    )

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        access_log=False,
    )


if __name__ == "__main__":
    main()