"""Entrypoint for running the Stiflyt MCP server (stdio transport for Cursor)."""
from .tools import create_app


def main() -> None:
    app = create_app()
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
