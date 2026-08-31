from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI

from core.runtime.paths import (
    resolve_bootstrap_data_root,
    resolve_bootstrap_system_root,
    set_bootstrap_roots,
)

# Prime bootstrap roots before importing modules that touch settings/paths
_BOOTSTRAP_DATA_ROOT = resolve_bootstrap_data_root()
_BOOTSTRAP_SYSTEM_ROOT = resolve_bootstrap_system_root()
set_bootstrap_roots(_BOOTSTRAP_DATA_ROOT, _BOOTSTRAP_SYSTEM_ROOT)

from api.application import create_application  # noqa: E402
from api.services import set_system_startup_time  # noqa: E402
from core.advanced_shell import load_advanced_shell_config  # noqa: E402
from core.authentication import load_authentication_policy  # noqa: E402
from core.logger import UnifiedLogger  # noqa: E402
from core.runtime.bootstrap import bootstrap_runtime  # noqa: E402
from core.runtime.config import RuntimeConfig  # noqa: E402
from core.settings import get_app_settings  # noqa: E402

# Create main logger
logger = UnifiedLogger(tag="main")
app_settings = get_app_settings()


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
        data_root=_BOOTSTRAP_DATA_ROOT,
        system_root=_BOOTSTRAP_SYSTEM_ROOT,
        public_url=app_settings.public_url,
    )

    # Bootstrap runtime services
    runtime = await bootstrap_runtime(config)

    # Store runtime context in app state for API access
    app.state.runtime = runtime

    logger.info("Application startup complete")

    yield  # App runs here

    # Shutdown
    if hasattr(app.state, "runtime") and app.state.runtime:
        await app.state.runtime.shutdown()
        app.state.runtime = None  # Clear app state to match global context
        logger.info("Application shutdown complete")


#######################################################################
## FastAPI application setup
#######################################################################

app = create_application(
    authentication_policy=load_authentication_policy(app_settings),
    advanced_shell_config=load_advanced_shell_config(app_settings),
    lifespan=lifespan,
)


# Set up unified logging with instrumentation
logger.setup_instrumentation(app)
