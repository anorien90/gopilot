"""
gopilot LSP Server - Full-featured server with stdio/TCP/agent modes

Usage:
    python -m gopilot.server [options]

Options:
    --mode        Server mode: stdio, tcp, or agent (default: stdio)
    --host        TCP host (default: 127.0.0.1)
    --port        TCP port (default: 2087)
    --ollama-host Ollama server host (default: localhost)
    --ollama-port Ollama server port (default: 11434)
    --model       Ollama model to use (default: codellama)
    --log-file    Log file path (default: /tmp/gopilot.log)
    --log-level   Log level: DEBUG, INFO, WARNING, ERROR (default: INFO)
    --repo-path   Path to git repository (default: current directory)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import socket
import threading
from typing import Any, Optional

from .ollama_client import OllamaClient
from .handlers import LSPHandlers
from .git_context import GitContext
from .agent import CopilotAgent

# Configure logger
logger = logging.getLogger(__name__)


class LSPServer:
    """Language Server Protocol server implementation."""

    def __init__(
        self,
        ollama_host: str = "localhost",
        ollama_port: int = 11434,
        model: str = "codellama",
        repo_path: Optional[str] = None,
        context_lines: int = 50,
    ):
        """
        Initialize LSP server.

        Args:
            ollama_host: Ollama server hostname
            ollama_port: Ollama server port
            model: Default Ollama model
            repo_path: Path to the git repository (enables agent features)
            context_lines: Number of lines around cursor for local scope
        """
        self.ollama_client = OllamaClient(
            host=ollama_host,
            port=ollama_port,
            model=model,
        )

        # Git-aware copilot agent
        self.git_context = GitContext(repo_path)
        self.agent: Optional[CopilotAgent] = None
        git_enabled = self.git_context.is_git_repo()

        # Initialize handlers with git context for project scope
        self.handlers = LSPHandlers(
            self.ollama_client,
            git_context=self.git_context if git_enabled else None,
            context_lines=context_lines,
        )

        if git_enabled:
            self.agent = CopilotAgent(self.ollama_client, self.git_context)
            logger.info("Copilot agent enabled (git repository detected)")
        else:
            logger.info("Copilot agent disabled (not a git repository)")

        self._initialized = False
        self._shutdown_requested = False

        self._capabilities = {
            "textDocumentSync": {
                "openClose": True,
                "change": 1,  # Full sync
                "save": {"includeText": True},
            },
            "completionProvider": {
                "triggerCharacters": [".", "(", "[", "{", ",", " ", ":"],
                "resolveProvider": False,
            },
            "hoverProvider": True,
        }
        logger.info(f"LSP server initialized with model: {model}")

    def handle_request(self, request: dict) -> Optional[dict]:
        """
        Handle an incoming JSON-RPC request.

        Args:
            request: JSON-RPC request object

        Returns:
            JSON-RPC response or None for notifications
        """
        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id")

        logger.debug(f"Handling request: {method}")

        # Method dispatch
        if method == "initialize":
            result = self._handle_initialize(params)
        elif method == "initialized":
            self._handle_initialized()
            return None  # Notification, no response
        elif method == "shutdown":
            result = self._handle_shutdown()
        elif method == "exit":
            self._handle_exit()
            return None
        elif method == "textDocument/didOpen":
            self._handle_did_open(params)
            return None
        elif method == "textDocument/didChange":
            self._handle_did_change(params)
            return None
        elif method == "textDocument/didSave":
            self._handle_did_save(params)
            return None
        elif method == "textDocument/didClose":
            self._handle_did_close(params)
            return None
        elif method == "textDocument/completion":
            result = self._handle_completion(params)
        elif method == "textDocument/hover":
            result = self._handle_hover(params)
        elif method == "gopilot/agent":
            result = self._handle_agent_request(params)
        elif method == "$/cancelRequest":
            return None  # Ignore cancel requests
        else:
            logger.warning(f"Unknown method: {method}")
            if request_id is not None:
                return self._create_error_response(
                    request_id, -32601, f"Method not found: {method}"
                )
            return None

        if request_id is not None:
            return self._create_response(request_id, result)
        return None

    def _handle_initialize(self, params: dict) -> dict:
        """Handle initialize request."""
        logger.info("Received initialize request")
        root_uri = params.get("rootUri", params.get("rootPath", ""))
        logger.info(f"Root URI: {root_uri}")

        # Update git context repo path from the client root if available
        if root_uri:
            repo_path = root_uri.removeprefix("file://")
            self.git_context = GitContext(repo_path)
            git_enabled = self.git_context.is_git_repo()

            # Reinitialize handlers with updated git context
            self.handlers = LSPHandlers(
                self.ollama_client,
                git_context=self.git_context if git_enabled else None,
                context_lines=self.handlers.context_lines,
            )

            if git_enabled:
                self.agent = CopilotAgent(self.ollama_client, self.git_context)
                logger.info(f"Copilot agent enabled for: {repo_path}")

        result = {
            "capabilities": self._capabilities,
            "serverInfo": {
                "name": "gopilot",
                "version": "0.1.0",
            },
        }

        # Advertise agent capabilities
        if self.agent:
            result["serverInfo"]["agentCapabilities"] = {
                "actions": [
                    "query",
                    "review",
                    "commit_message",
                    "explain_diff",
                    "summarize_branch",
                    "status",
                ],
            }

        return result

    def _handle_initialized(self) -> None:
        """Handle initialized notification."""
        self._initialized = True
        logger.info("Server initialized successfully")

        # Check Ollama connection
        if self.ollama_client.health_check():
            logger.info("Ollama server is available")
            models = self.ollama_client.list_models()
            if models:
                logger.info(f"Available models: {', '.join(models)}")
        else:
            logger.warning("Ollama server is not available")

    def _handle_shutdown(self) -> None:
        """Handle shutdown request."""
        logger.info("Shutdown requested")
        self._shutdown_requested = True
        return None

    def _handle_exit(self) -> None:
        """Handle exit notification."""
        logger.info("Exit notification received")
        exit_code = 0 if self._shutdown_requested else 1
        sys.exit(exit_code)

    def _handle_did_open(self, params: dict) -> None:
        """Handle textDocument/didOpen notification."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")
        text = text_document.get("text", "")
        self.handlers.store_document(uri, text)
        logger.info(f"Document opened: {uri}")

    def _handle_did_change(self, params: dict) -> None:
        """Handle textDocument/didChange notification."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")
        content_changes = params.get("contentChanges", [])

        # Full sync - take the last content change
        if content_changes:
            text = content_changes[-1].get("text", "")
            self.handlers.store_document(uri, text)
            logger.debug(f"Document changed: {uri}")

    def _handle_did_save(self, params: dict) -> None:
        """Handle textDocument/didSave notification."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")
        text = params.get("text")

        if text is not None:
            self.handlers.store_document(uri, text)

        logger.debug(f"Document saved: {uri}")

    def _handle_did_close(self, params: dict) -> None:
        """Handle textDocument/didClose notification."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")
        # Remove from document store when tab closes
        self.handlers.remove_document(uri)
        logger.debug(f"Document closed: {uri}")

    def _handle_agent_request(self, params: dict) -> dict:
        """Handle gopilot/agent custom request."""
        if not self.agent:
            return {"error": "Agent not available (not a git repository)"}

        action = params.get("action", "")
        action_params = params.get("params", {})
        logger.info(f"Agent request: action={action}")
        return self.agent.handle_agent_request(action, action_params)

    def _handle_completion(self, params: dict) -> dict:
        """Handle textDocument/completion request."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")
        position = params.get("position", {})
        context = params.get("context")

        items = self.handlers.handle_completion(uri, position, context)

        return {
            "isIncomplete": False,
            "items": items,
        }

    def _handle_hover(self, params: dict) -> Optional[dict]:
        """Handle textDocument/hover request."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")
        position = params.get("position", {})

        return self.handlers.handle_hover(uri, position)

    def _create_response(self, request_id: Any, result: Any) -> dict:
        """Create a JSON-RPC response."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }

    def _create_error_response(
        self, request_id: Any, code: int, message: str
    ) -> dict:
        """Create a JSON-RPC error response."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }


class StdioTransport:
    """Stdio transport for LSP communication."""

    def __init__(self, server: LSPServer):
        """
        Initialize stdio transport.

        Args:
            server: LSP server instance
        """
        self.server = server
        self._running = False

    def start(self) -> None:
        """Start the stdio transport loop."""
        logger.info("Starting stdio transport")
        self._running = True

        while self._running:
            try:
                message = self._read_message()
                if message is None:
                    break

                response = self.server.handle_request(message)
                if response:
                    self._write_message(response)

            except Exception as e:
                logger.exception(f"Error handling message: {e}")

    def _read_message(self) -> Optional[dict]:
        """Read a message from stdin."""
        try:
            # Read headers
            headers = {}
            while True:
                line = sys.stdin.readline()
                if not line:
                    return None
                line = line.strip()
                if not line:
                    break
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()

            # Get content length
            content_length = int(headers.get("content-length", 0))
            if content_length == 0:
                return None

            # Read content
            content = sys.stdin.read(content_length)
            if not content:
                return None

            return json.loads(content)

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return None
        except Exception as e:
            logger.error(f"Error reading message: {e}")
            return None

    def _write_message(self, message: dict) -> None:
        """Write a message to stdout."""
        try:
            content = json.dumps(message)
            content_bytes = content.encode("utf-8")
            header = f"Content-Length: {len(content_bytes)}\r\n\r\n"

            sys.stdout.write(header)
            sys.stdout.write(content)
            sys.stdout.flush()

        except Exception as e:
            logger.error(f"Error writing message: {e}")


class TCPTransport:
    """TCP transport for LSP communication."""

    def __init__(self, server: LSPServer, host: str = "127.0.0.1", port: int = 2087):
        """
        Initialize TCP transport.

        Args:
            server: LSP server instance
            host: TCP host to bind to
            port: TCP port to bind to
        """
        self.server = server
        self.host = host
        self.port = port
        self._socket: Optional[socket.socket] = None
        self._running = False

    def start(self) -> None:
        """Start the TCP transport."""
        logger.info(f"Starting TCP transport on {self.host}:{self.port}")
        self._running = True

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.host, self.port))
        self._socket.listen(5)

        logger.info(f"Listening on {self.host}:{self.port}")

        while self._running:
            try:
                client_socket, address = self._socket.accept()
                logger.info(f"Client connected: {address}")
                thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket,),
                    daemon=True,
                )
                thread.start()
            except Exception as e:
                if self._running:
                    logger.error(f"Error accepting connection: {e}")

    def _handle_client(self, client_socket: socket.socket) -> None:
        """Handle a client connection."""
        try:
            buffer = b""
            while self._running:
                data = client_socket.recv(4096)
                if not data:
                    break
                buffer += data

                while True:
                    message, buffer = self._parse_message(buffer)
                    if message is None:
                        break

                    response = self.server.handle_request(message)
                    if response:
                        self._send_message(client_socket, response)

        except Exception as e:
            logger.error(f"Error handling client: {e}")
        finally:
            client_socket.close()

    def _parse_message(self, buffer: bytes) -> tuple[Optional[dict], bytes]:
        """Parse a message from the buffer."""
        try:
            # Find header end
            header_end = buffer.find(b"\r\n\r\n")
            if header_end == -1:
                return None, buffer

            # Parse headers
            headers_raw = buffer[:header_end].decode("utf-8")
            headers = {}
            for line in headers_raw.split("\r\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()

            # Get content length
            content_length = int(headers.get("content-length", 0))
            if content_length == 0:
                return None, buffer

            # Check if we have enough data
            content_start = header_end + 4
            content_end = content_start + content_length

            if len(buffer) < content_end:
                return None, buffer

            # Parse content
            content = buffer[content_start:content_end].decode("utf-8")
            message = json.loads(content)

            return message, buffer[content_end:]

        except Exception as e:
            logger.error(f"Error parsing message: {e}")
            return None, buffer

    def _send_message(self, client_socket: socket.socket, message: dict) -> None:
        """Send a message to the client."""
        try:
            content = json.dumps(message)
            content_bytes = content.encode("utf-8")
            header = f"Content-Length: {len(content_bytes)}\r\n\r\n"

            client_socket.sendall(header.encode("utf-8"))
            client_socket.sendall(content_bytes)

        except Exception as e:
            logger.error(f"Error sending message: {e}")


def setup_logging(log_file: str, log_level: str) -> None:
    """
    Configure logging.

    Args:
        log_file: Path to log file
        log_level: Logging level string
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)


def _run_agent_cli(server: LSPServer) -> None:
    """
    Run an interactive CLI agent session.

    This mode lets developers interact with the copilot agent directly
    from the terminal, asking questions about branches, requesting
    code reviews, or generating commit messages.
    """
    if not server.agent:
        print("Error: not inside a git repository. Agent mode requires git.")
        sys.exit(1)

    branch = server.agent.git.get_current_branch() or "unknown"
    print(f"gopilot agent · branch: {branch}")
    print("Commands: /review, /commit, /diff <base> [target], /summary [branch], /status, /quit")
    print("Or type a question.\n")

    while True:
        try:
            query = input("gopilot> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not query:
            continue
        if query in ("/quit", "/exit", "/q"):
            print("Bye!")
            break

        if query == "/status":
            status = server.agent.git.get_status_summary()
            for key, val in status.items():
                if isinstance(val, list):
                    val = ", ".join(val) if val else "(none)"
                print(f"  {key}: {val}")
            continue

        if query == "/review":
            print("Reviewing changes …")
            print(server.agent.review_changes() or "(no response)")
            continue

        if query == "/commit":
            print("Generating commit message …")
            print(server.agent.suggest_commit_message() or "(no response)")
            continue

        if query.startswith("/diff"):
            parts = query.split()
            base = parts[1] if len(parts) > 1 else "main"
            target = parts[2] if len(parts) > 2 else None
            print(f"Explaining diff {base}..{target or 'HEAD'} …")
            print(server.agent.explain_diff(base, target) or "(no response)")
            continue

        if query.startswith("/summary"):
            parts = query.split()
            branch_arg = parts[1] if len(parts) > 1 else None
            print("Summarizing branch …")
            print(server.agent.summarize_branch(branch_arg) or "(no response)")
            continue

        # Free-form query
        print("Thinking …")
        print(server.agent.process_query(query) or "(no response)")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="gopilot LSP Server - AI-powered code assistance"
    )
    parser.add_argument(
        "--mode",
        choices=["stdio", "tcp", "agent"],
        default="stdio",
        help="Server mode (default: stdio). 'agent' starts an interactive CLI agent.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="TCP host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=2087,
        help="TCP port (default: 2087)",
    )
    parser.add_argument(
        "--ollama-host",
        default="localhost",
        help="Ollama server host (default: localhost)",
    )
    parser.add_argument(
        "--ollama-port",
        type=int,
        default=11434,
        help="Ollama server port (default: 11434)",
    )
    parser.add_argument(
        "--model",
        default="codellama",
        help="Ollama model to use (default: codellama)",
    )
    parser.add_argument(
        "--log-file",
        default="/tmp/gopilot.log",
        help="Log file path (default: /tmp/gopilot.log)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Log level (default: INFO)",
    )
    parser.add_argument(
        "--repo-path",
        default=None,
        help="Path to git repository (default: current directory)",
    )
    parser.add_argument(
        "--context-lines",
        type=int,
        default=50,
        help="Number of lines around cursor for local scope (default: 50)",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_file, args.log_level)

    logger.info("Starting gopilot LSP server")
    logger.info(f"Mode: {args.mode}")
    logger.info(f"Ollama: {args.ollama_host}:{args.ollama_port}")
    logger.info(f"Model: {args.model}")

    # Create server
    server = LSPServer(
        ollama_host=args.ollama_host,
        ollama_port=args.ollama_port,
        model=args.model,
        repo_path=args.repo_path,
        context_lines=args.context_lines,
    )

    # Start transport
    if args.mode == "agent":
        _run_agent_cli(server)
    elif args.mode == "stdio":
        transport = StdioTransport(server)
    else:
        transport = TCPTransport(server, args.host, args.port)

    if args.mode != "agent":
        try:
            transport.start()
        except KeyboardInterrupt:
            logger.info("Server interrupted")
        except Exception as e:
            logger.exception(f"Server error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
