"""
Ollama Client - HTTP client for localhost:11434
"""

import json
import logging
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)


class OllamaClient:
    """HTTP client for interacting with Ollama API."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 11434,
        model: str = "codellama",
        timeout: int = 30,
    ):
        """
        Initialize Ollama client.

        Args:
            host: Ollama server hostname
            port: Ollama server port
            model: Default model to use
            timeout: Request timeout in seconds
        """
        self.base_url = f"http://{host}:{port}"
        self.model = model
        self.timeout = timeout
        logger.info(f"Ollama client initialized: {self.base_url}, model={model}")

    def _make_request(self, endpoint: str, data: dict) -> Optional[dict]:
        """
        Make a synchronous HTTP request to Ollama API.

        Args:
            endpoint: API endpoint (e.g., '/api/generate')
            data: Request payload

        Returns:
            Response data or None on error
        """
        url = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}

        try:
            request = Request(
                url,
                data=json.dumps(data).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urlopen(request, timeout=self.timeout) as response:
                # Handle streaming response - collect all chunks
                full_response = ""
                for line in response:
                    if line:
                        try:
                            chunk = json.loads(line.decode("utf-8"))
                            if "response" in chunk:
                                full_response += chunk["response"]
                            if chunk.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
                return {"response": full_response}
        except HTTPError as e:
            logger.error(f"HTTP error: {e.code} - {e.reason}")
            return None
        except URLError as e:
            logger.error(f"URL error: {e.reason}")
            return None
        except TimeoutError:
            logger.error(f"Request timed out after {self.timeout}s")
            return None
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return None

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        context: Optional[str] = None,
        system: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate a completion from Ollama.

        Args:
            prompt: The prompt to complete
            model: Model to use (defaults to client's default)
            context: Additional context for the prompt
            system: System prompt for the model

        Returns:
            Generated text or None on error
        """
        data = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": True,
        }

        if system:
            data["system"] = system

        if context:
            data["prompt"] = f"{context}\n\n{prompt}"

        logger.debug(f"Generating completion for prompt: {prompt[:100]}...")
        result = self._make_request("/api/generate", data)

        if result and "response" in result:
            return result["response"]
        return None

    def complete_code(
        self,
        code_before: str,
        code_after: str = "",
        language: str = "python",
        model: Optional[str] = None,
        cursor_prefix: str = "",
        secondary_context: str = "",
        project_context: str = "",
    ) -> Optional[str]:
        """
        Generate code completion with layered context.

        Args:
            code_before: Code before cursor (local scope)
            code_after: Code after cursor (local scope)
            language: Programming language
            model: Model to use
            cursor_prefix: Exact text at cursor position for precise completion
            secondary_context: Context from other open tabs
            project_context: Project file listing

        Returns:
            Code completion or None on error
        """
        system_prompt = f"""You are a precise code completion assistant for {language}.

CRITICAL RULES:
1. Complete ONLY from the exact cursor position - do NOT repeat any code that already exists
2. The cursor is at the end of: "{cursor_prefix}"
3. Your completion should continue naturally from that exact point
4. Do NOT include explanations, comments, or markdown - only the completion code
5. Match the existing code style and indentation
6. Keep completions focused and concise

Context priority:
- PRIMARY: Local code around cursor (most important)
- SECONDARY: Other open files (for imports/references)
- TERTIARY: Project structure (for awareness)

Only output the exact completion text that should be inserted at the cursor."""

        # Build the prompt with layered context
        prompt_parts = []

        # Add secondary context if available
        if secondary_context:
            prompt_parts.append(secondary_context)

        # Add project context if available (less priority)
        if project_context:
            prompt_parts.append(f"\n{project_context}")

        # Add the main completion request (highest priority)
        prompt_parts.append(f"\n=== Current File (Primary Context) ===")
        prompt_parts.append(f"Language: {language}")
        prompt_parts.append(f"\nCode before cursor:\n```{language}\n{code_before}")

        if code_after:
            prompt_parts.append(f"\n[CURSOR HERE]\n{code_after}")
        else:
            prompt_parts.append("\n[CURSOR HERE]")

        prompt_parts.append("```")

        # Truncate cursor_prefix for display to avoid prompt issues with very long lines
        display_prefix = cursor_prefix[:100] if len(cursor_prefix) > 100 else cursor_prefix
        prompt_parts.append(f"\nCursor position text: '{display_prefix}'")
        prompt_parts.append("\nProvide ONLY the completion code (no explanations):")

        prompt = "\n".join(prompt_parts)

        return self.generate(prompt, model=model, system=system_prompt)

    def explain_code(
        self,
        code: str,
        language: str = "python",
        model: Optional[str] = None,
    ) -> Optional[str]:
        """
        Explain a piece of code for hover documentation.

        Args:
            code: Code to explain
            language: Programming language
            model: Model to use

        Returns:
            Explanation or None on error
        """
        system_prompt = """You are a code documentation assistant.
Provide brief, helpful explanations of code.
Keep explanations concise (2-3 sentences max)."""

        prompt = f"Explain this {language} code briefly:\n```{language}\n{code}\n```"

        return self.generate(prompt, model=model, system=system_prompt)

    def health_check(self) -> bool:
        """
        Check if Ollama server is available.

        Returns:
            True if server is reachable, False otherwise
        """
        try:
            url = f"{self.base_url}/api/tags"
            request = Request(url, method="GET")
            with urlopen(request, timeout=5) as response:
                return response.status == 200
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False

    def list_models(self) -> list:
        """
        List available models.

        Returns:
            List of model names
        """
        try:
            url = f"{self.base_url}/api/tags"
            request = Request(url, method="GET")
            with urlopen(request, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []
