"""Tool to run the ingestion pipeline synchronously on a single URL."""

from pydantic_ai.tools import Tool

from core.ingestion.models import SourceKind
from core.ingestion.service import IngestionService
from core.logger import UnifiedLogger
from core.runtime.state import get_runtime_context
from .base import BaseTool


logger = UnifiedLogger(tag="import-url-tool")


class ImportUrlTool(BaseTool):
    @classmethod
    def get_tool(cls, vault_path: str = None):
        if not vault_path:
            raise ValueError("Vault context is required for import_url tool.")

        # Derive vault name from path
        vault_name = vault_path.rstrip("/").split("/")[-1]
        if not vault_name:
            raise ValueError("Unable to derive vault name from vault_path")

        def import_url(url: str, clean_html: bool = True):
            runtime = get_runtime_context()
            svc: IngestionService = runtime.ingestion
            job = svc.enqueue_job(
                source_uri=url,
                vault=vault_name,
                source_type=SourceKind.URL.value,
                mime_hint="text/html",
                options={"extractor_options": {"clean_html": clean_html}},
            )
            try:
                svc.process_job(job.id)
            except Exception as exc:
                logger.warning("import_url tool encountered error", metadata={"error": str(exc)})
            job_ref = svc.get_job(job.id)
            return {
                "id": job_ref.id if job_ref else job.id,
                "status": job_ref.status if job_ref else "unknown",
                "error": job_ref.error if job_ref else None,
                "outputs": job_ref.outputs if job_ref else None,
                "source_uri": url,
                "vault": vault_name,
            }

        return Tool(
            import_url,
            name="import_url",
            description="Import a single URL into a vault using the ingestion pipeline. Returns vault-relative output paths.",
        )

    @classmethod
    def get_instructions(cls) -> str:
        return (
            "Use import_url to fetch a URL, convert it to markdown, and write it under the vault's Imported/ folder. "
            "Provide the target vault name and the URL. clean_html defaults to true to strip obvious page chrome."
        )
