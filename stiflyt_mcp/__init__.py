"""Stiflyt MCP server: exposes Stiflyt backend API as MCP tools for Cursor and other MCP clients."""

__all__ = ["create_app"]

from .tools import create_app
