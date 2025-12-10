#!/usr/bin/env python3
"""Simple HTTP server with filtered logging to ignore HTTPS/TLS probe errors."""
import http.server
import socketserver
import sys
import re

class FilteredHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler that filters out HTTPS/TLS probe errors."""

    def log_message(self, format, *args):
        """Override log_message to filter out HTTPS/TLS probe errors."""
        # Filter out HTTPS/TLS handshake attempts (common bot/scanner behavior)
        # These show up as "Bad request version" or "Invalid HTTP request" errors
        if len(args) >= 2:
            message = str(args[1]) if len(args) > 1 else ""
            # Skip logging for HTTPS/TLS handshake attempts
            if ("Bad request version" in message or
                "Invalid HTTP request" in message or
                ("code 400" in format and "\x16\x03" in message)):
                return  # Don't log these

        # Also check the format string
        if "Bad request version" in format or "Invalid HTTP request" in format:
            return

        # Log normal requests
        super().log_message(format, *args)

def run_server(port=8080):
    """Run the HTTP server on the specified port."""
    Handler = FilteredHTTPRequestHandler

    with socketserver.TCPServer(("", port), Handler) as httpd:
        print(f"Serving at http://localhost:{port}/")
        print("Press Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
            sys.exit(0)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port)

