import atexit
import logging
import os
import socket

try:
    from opentelemetry import metrics, trace
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.flask import FlaskInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.propagate import extract, inject
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

from .version import __version__


_INITIALIZED_PID = None
_FORK_HANDLER_REGISTERED = False
_PROVIDERS = {
    'tracer': None,
    'meter': None,
    'logger': None,
    'log_handler': None,
}
_INSTRUMENTS = {}


class _NoOpSpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def set_attribute(self, key, value):
        pass

    def record_exception(self, exception):
        pass

    def set_status(self, status):
        pass


class _NoOpTracer:
    def start_as_current_span(self, name, **kwargs):
        return _NoOpSpan()


class _NoOpInstrument:
    def add(self, amount, attributes=None):
        pass

    def record(self, amount, attributes=None):
        pass

    def set(self, amount, attributes=None):
        pass


class _NoOpMeter:
    def create_counter(self, name, **kwargs):
        return _NoOpInstrument()

    def create_histogram(self, name, **kwargs):
        return _NoOpInstrument()

    def create_gauge(self, name, **kwargs):
        return _NoOpInstrument()

    def create_up_down_counter(self, name, **kwargs):
        return _NoOpInstrument()


def is_otel_enabled():
    """Return True when OTEL packages are present and an OTLP endpoint is configured."""
    if not OTEL_AVAILABLE:
        return False

    if os.environ.get('OTEL_SDK_DISABLED', '').strip().lower() in ('1', 'true', 'yes'):
        return False

    return bool(
        os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT', '').strip()
        or os.environ.get('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT', '').strip()
        or os.environ.get('OTEL_EXPORTER_OTLP_METRICS_ENDPOINT', '').strip()
        or os.environ.get('OTEL_EXPORTER_OTLP_LOGS_ENDPOINT', '').strip()
    )


def _reset_after_fork():
    """Clear parent-process OTEL provider references in forked children."""
    global _INITIALIZED_PID
    _INITIALIZED_PID = None
    _PROVIDERS['tracer'] = None
    _PROVIDERS['meter'] = None
    _PROVIDERS['logger'] = None
    _INSTRUMENTS.clear()


def attach_otel_log_handler(target_logger):
    """Attach the active OTEL LoggingHandler to a Python logger without duplicating it."""
    handler = _PROVIDERS.get('log_handler')
    if handler is None or target_logger is None:
        return

    for existing in list(target_logger.handlers):
        if isinstance(existing, LoggingHandler) and existing is not handler:
            target_logger.removeHandler(existing)

    if handler not in target_logger.handlers:
        target_logger.addHandler(handler)


def init_otel(service_name='indi-allsky', component=None, loggers=None):
    """Initialize OpenTelemetry trace, metric, and log providers for the current process."""
    global _INITIALIZED_PID, _FORK_HANDLER_REGISTERED

    if not is_otel_enabled():
        return False

    pid = os.getpid()
    if _INITIALIZED_PID == pid:
        if loggers:
            for lg in loggers:
                attach_otel_log_handler(lg)
        return True

    if not _FORK_HANDLER_REGISTERED and hasattr(os, 'register_at_fork'):
        os.register_at_fork(after_in_child=_reset_after_fork)
        _FORK_HANDLER_REGISTERED = True

    resolved_service = os.environ.get('OTEL_SERVICE_NAME', '').strip() or service_name
    resource_attrs = {
        'service.name': resolved_service,
        'service.version': __version__,
        'host.name': socket.gethostname(),
    }
    if component:
        resource_attrs['process.component'] = component

    resource = Resource.create(resource_attrs)

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)

    LoggingInstrumentor().instrument(set_logging_format=False)
    log_handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)

    _PROVIDERS['tracer'] = tracer_provider
    _PROVIDERS['meter'] = meter_provider
    _PROVIDERS['logger'] = logger_provider
    _PROVIDERS['log_handler'] = log_handler
    _INSTRUMENTS.clear()
    _INITIALIZED_PID = pid

    if loggers:
        for lg in loggers:
            attach_otel_log_handler(lg)

    atexit.register(shutdown_otel)
    return True


def shutdown_otel():
    """Flush and shut down active OTEL providers for the current process."""
    global _INITIALIZED_PID

    for key in ('tracer', 'meter', 'logger'):
        provider = _PROVIDERS.get(key)
        if provider is None:
            continue
        try:
            if hasattr(provider, 'force_flush'):
                provider.force_flush(timeout_millis=2000)
        except Exception:
            pass
        try:
            provider.shutdown()
        except Exception:
            pass
        _PROVIDERS[key] = None

    _PROVIDERS['log_handler'] = None
    _INSTRUMENTS.clear()
    _INITIALIZED_PID = None


def get_tracer(name='indi_allsky'):
    """Return an active OTEL Tracer or a zero-overhead no-op tracer."""
    provider = _PROVIDERS.get('tracer')
    if not is_otel_enabled() or provider is None:
        return _NoOpTracer()
    return provider.get_tracer(name)


def get_meter(name='indi_allsky'):
    """Return an active OTEL Meter or a zero-overhead no-op meter."""
    provider = _PROVIDERS.get('meter')
    if not is_otel_enabled() or provider is None:
        return _NoOpMeter()
    return provider.get_meter(name)


def get_pipeline_instruments():
    """Return cached pipeline metric instruments for the active process."""
    if not is_otel_enabled() or _PROVIDERS['meter'] is None:
        return {
            'frames_captured': _NoOpInstrument(),
            'exposure_duration': _NoOpInstrument(),
            'image_processing_duration': _NoOpInstrument(),
            'video_generation_duration': _NoOpInstrument(),
            'queue_depth': _NoOpInstrument(),
            'sensor_value': _NoOpInstrument(),
        }

    if not _INSTRUMENTS:
        meter = get_meter('indi_allsky.pipeline')
        _INSTRUMENTS['frames_captured'] = meter.create_counter(
            'indi_allsky.frames.captured',
            description='Total frames captured by CaptureWorker',
            unit='1',
        )
        _INSTRUMENTS['exposure_duration'] = meter.create_histogram(
            'indi_allsky.exposure.duration',
            description='Camera exposure duration in seconds',
            unit='s',
        )
        _INSTRUMENTS['image_processing_duration'] = meter.create_histogram(
            'indi_allsky.image.processing.duration',
            description='Image processing duration per frame in seconds',
            unit='s',
        )
        _INSTRUMENTS['video_generation_duration'] = meter.create_histogram(
            'indi_allsky.video.generation.duration',
            description='Video, keogram, and startrail task duration in seconds',
            unit='s',
        )
        _INSTRUMENTS['queue_depth'] = meter.create_gauge(
            'indi_allsky.queue.depth',
            description='Approximate multiprocessing queue depth',
            unit='1',
        )
        _INSTRUMENTS['sensor_value'] = meter.create_gauge(
            'indi_allsky.sensor.value',
            description='Observatory and hardware sensor reading',
            unit='1',
        )

    return _INSTRUMENTS


def inject_trace_context(carrier=None):
    """Inject active W3C trace context into a dict for cross-process queue propagation."""
    target = {} if carrier is None else carrier
    if is_otel_enabled() and _PROVIDERS['tracer'] is not None:
        inject(target)
    return target


def extract_trace_context(carrier):
    """Extract W3C trace context from a dict received across a multiprocessing queue."""
    if not carrier or not is_otel_enabled() or _PROVIDERS['tracer'] is None:
        return None
    return extract(carrier)


_REQUESTS_INSTRUMENTED = False


def instrument_flask_app(app, db_engine=None):
    """Instrument a Flask app, SQLAlchemy engine, and outbound requests when OTEL is enabled."""
    global _REQUESTS_INSTRUMENTED

    if not is_otel_enabled():
        return False

    init_otel(service_name='indi-allsky-web', component='flask', loggers=[app.logger])

    if not getattr(app, '_otel_instrumented', False):
        FlaskInstrumentor().instrument_app(app)
        app._otel_instrumented = True

    if db_engine is not None and not getattr(db_engine, '_otel_instrumented', False):
        SQLAlchemyInstrumentor().instrument(engine=db_engine)
        db_engine._otel_instrumented = True

    if not _REQUESTS_INSTRUMENTED:
        RequestsInstrumentor().instrument()
        _REQUESTS_INSTRUMENTED = True

    return True
