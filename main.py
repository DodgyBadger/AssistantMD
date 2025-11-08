from contextlib import asynccontextmanager
from datetime import datetime
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

from core.logger import UnifiedLogger
from core.constants import CONTAINER_DATA_ROOT, SYSTEM_DATA_ROOT
from core.runtime.config import RuntimeConfig
from core.runtime.bootstrap import bootstrap_runtime
from api.endpoints import router as api_router, register_exception_handlers
from api.services import set_system_startup_time

# Create main logger
logger = UnifiedLogger(tag="main")


# Run in development
# uvicorn main:app --host 0.0.0.0 --port 8000 --reload


#######################################################################
## FastAPI lifespan with runtime bootstrap
#######################################################################

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    startup_time = datetime.now()
    set_system_startup_time(startup_time)

    # Create runtime configuration for production
    config = RuntimeConfig.for_production(
        data_root=CONTAINER_DATA_ROOT,
        system_data_root=SYSTEM_DATA_ROOT
    )

    # Bootstrap runtime services
    runtime = await bootstrap_runtime(config)

    # Store runtime context in app state for API access
    app.state.runtime = runtime

    logger.info("Application startup complete")

    yield  # App runs here

    # Shutdown
    if hasattr(app.state, 'runtime') and app.state.runtime:
        await app.state.runtime.shutdown()
        app.state.runtime = None  # Clear app state to match global context
        logger.info("Application shutdown complete")




#######################################################################
## FastAPI application setup
#######################################################################

app = FastAPI(lifespan=lifespan)

# Register API routes
app.include_router(api_router)

# Register API exception handlers
register_exception_handlers(app)

# Mount static files with absolute path
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir, html=True), name="static")

# Serve main UI at root
@app.get("/")
async def root():
    return FileResponse(os.path.join(static_dir, "index.html"))

# Set up unified logging with instrumentation
logger.setup_instrumentation(app)
