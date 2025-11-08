"""
LibreChat code execution tool implementation.

Provides multi-language code execution capability through LibreChat API (premium).
"""

import httpx
from pydantic_ai.tools import Tool
from .base import BaseTool
from core.settings.secrets_store import get_secret_value


class LibreChatClient:
    """Client for LibreChat Code Interpreter API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.librechat.ai"
        self.headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json"
        }

        # Map common language names to LibreChat's expected values
        self.language_map = {
            "python": "py",
            "javascript": "js",
            "typescript": "ts",
            "c++": "cpp",
            "c": "c",
            "go": "go",
            "java": "java",
            "php": "php",
            "rust": "rs",
            "fortran": "f90",
            "d": "d",
            "r": "r"
        }

    async def execute_code(self, code: str, language: str = "python") -> dict:
        """Execute code via LibreChat API."""
        # Map language to LibreChat's expected format
        lang_code = self.language_map.get(language.lower(), language.lower())

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/exec",
                headers=self.headers,
                json={
                    "code": code,
                    "lang": lang_code
                },
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()


class CodeExecutionLibreChat(BaseTool):
    """Code execution tool using LibreChat API."""

    @classmethod
    def get_tool(cls, vault_path: str = None):
        """Get the Pydantic AI tool for LibreChat code execution."""
        librechat_api_key = get_secret_value('LIBRECHAT_API_KEY')
        if not librechat_api_key:
            raise ValueError("Secret 'LIBRECHAT_API_KEY' is required for LibreChat code execution.")

        client = LibreChatClient(librechat_api_key)

        async def execute_code(code: str, language: str = "python") -> str:
            """Execute code in specified language with LibreChat's multi-language support.

            Args:
                code: The code to execute
                language: Programming language (python, javascript, typescript, go, c, cpp, java, php, rust, fortran)
            """
            try:
                result = await client.execute_code(code, language)

                # Parse LibreChat API response format - handles both flat and nested formats
                if 'run' in result:
                    run_info = result['run']
                    output = run_info.get('output', '')
                    stdout = run_info.get('stdout', '')
                    stderr = run_info.get('stderr', '')
                    exit_code = run_info.get('code')
                elif 'stdout' in result:
                    # Flat format (actual API response)
                    output = result.get('output', '')
                    stdout = result.get('stdout', '')
                    stderr = result.get('stderr', '')
                    exit_code = result.get('code')
                else:
                    return f"Code executed. Result: {str(result)}"

                # Build response based on execution results
                response_parts = []

                if stdout:
                    response_parts.append(f"Output:\n{stdout}")

                if output and output != stdout:
                    response_parts.append(f"Result:\n{output}")

                if stderr:
                    response_parts.append(f"Errors:\n{stderr}")

                if exit_code is not None and exit_code != 0:
                    response_parts.append(f"Exit code: {exit_code}")

                if response_parts:
                    return "Code execution completed:\n\n" + "\n\n".join(response_parts)
                else:
                    return "Code executed successfully (no output)"

            except httpx.HTTPError as e:
                return f"LibreChat API error: {str(e)}"
            except Exception as e:
                return f"Code execution error: {str(e)}"

        return Tool(execute_code, name="execute_code")

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for LibreChat code execution."""
        return "Code execution using LibreChat API: Multi-language support (Python, JavaScript, TypeScript, Go, C, C++, Java, PHP, Rust, Fortran) with file operations (premium service)"
