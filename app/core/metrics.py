from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator


def setup_metrics(app: FastAPI) -> Instrumentator:
    """Attach Prometheus metrics endpoint and default HTTP instrumentation."""
    instrumentator = Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        should_respect_env_var=False,
        should_instrument_requests_inprogress=True,
        excluded_handlers={"/health/live", "/health/ready", "/metrics"},
        inprogress_name="http_requests_inprogress",
        inprogress_labels=True,
    )
    instrumentator.instrument(app).expose(
        app,
        include_in_schema=False,
        endpoint="/metrics",
    )
    return instrumentator
