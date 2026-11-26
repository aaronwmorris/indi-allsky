import json
import logging
import os
import tempfile
import unittest

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from indi_allsky import otel


class TestOpenTelemetry(unittest.TestCase):
    def setUp(self):
        otel.shutdown_otel()
        self._orig_env = dict(os.environ)

    def tearDown(self):
        otel.shutdown_otel()
        os.environ.clear()
        os.environ.update(self._orig_env)

    def test_noop_when_unconfigured(self):
        os.environ.pop('OTEL_EXPORTER_OTLP_ENDPOINT', None)
        os.environ.pop('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT', None)
        os.environ.pop('OTEL_EXPORTER_OTLP_METRICS_ENDPOINT', None)
        os.environ.pop('OTEL_EXPORTER_OTLP_LOGS_ENDPOINT', None)

        self.assertFalse(otel.is_otel_enabled())
        self.assertFalse(otel.init_otel('indi-allsky-test'))

        tracer = otel.get_tracer('test')
        with tracer.start_as_current_span('noop.span') as span:
            span.set_attribute('k', 'v')

        inst = otel.get_pipeline_instruments()
        inst['frames_captured'].add(1, {'day_night': 'night'})
        inst['exposure_duration'].record(1.5)
        inst['sensor_value'].set(22.5, {'sensor.name': 'MockSensor'})

        carrier = otel.inject_trace_context()
        self.assertEqual(carrier, {})
        self.assertIsNone(otel.extract_trace_context(carrier))

    def test_traces_metrics_logs_and_queue_propagation(self):
        os.environ['OTEL_EXPORTER_OTLP_ENDPOINT'] = 'http://127.0.0.1:4318'

        span_exporter = InMemorySpanExporter()
        metric_reader = InMemoryMetricReader()
        log_exporter = InMemoryLogRecordExporter()
        resource = Resource.create({'service.name': 'indi-allsky-unit'})

        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        trace.set_tracer_provider(tracer_provider)

        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)

        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(SimpleLogRecordProcessor(log_exporter))
        set_logger_provider(logger_provider)

        log_handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)

        # Bind directly into module state to exercise helpers with in-memory exporters
        otel._PROVIDERS['tracer'] = tracer_provider
        otel._PROVIDERS['meter'] = meter_provider
        otel._PROVIDERS['logger'] = logger_provider
        otel._PROVIDERS['log_handler'] = log_handler
        otel._INITIALIZED_PID = os.getpid()
        otel._INSTRUMENTS.clear()

        test_logger = logging.getLogger('indi_allsky_otel_test')
        test_logger.setLevel(logging.INFO)
        test_logger.propagate = False
        otel.attach_otel_log_handler(test_logger)

        tracer = otel.get_tracer('indi_allsky.capture')
        with tracer.start_as_current_span('capture.exposure') as parent_span:
            carrier = otel.inject_trace_context()
            self.assertIn('traceparent', carrier)
            test_logger.info('Captured frame')

            inst = otel.get_pipeline_instruments()
            inst['frames_captured'].add(1, {'day_night': 'night'})
            inst['exposure_duration'].record(2.5, {'day_night': 'night'})
            inst['queue_depth'].set(3, {'queue': 'image_q'})

        # Simulate child worker extracting context from multiprocessing.Queue payload
        ctx = otel.extract_trace_context(carrier)
        child_tracer = otel.get_tracer('indi_allsky.image')
        with child_tracer.start_as_current_span('image.process', context=ctx):
            test_logger.info('Processed frame')

        spans = span_exporter.get_finished_spans()
        self.assertEqual(len(spans), 2)
        parent_s, child_s = spans[0], spans[1]
        self.assertEqual(parent_s.context.trace_id, child_s.context.trace_id)
        self.assertEqual(child_s.parent.span_id, parent_s.context.span_id)

        metrics_data = metric_reader.get_metrics_data()
        metric_names = {
            m.name
            for rm in metrics_data.resource_metrics
            for sm in rm.scope_metrics
            for m in sm.metrics
        }
        self.assertIn('indi_allsky.frames.captured', metric_names)
        self.assertIn('indi_allsky.exposure.duration', metric_names)
        self.assertIn('indi_allsky.queue.depth', metric_names)

        logs = log_exporter.get_finished_logs()
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].log_record.trace_id, parent_span.get_span_context().trace_id)

        # Verify fork reset clears inherited providers
        otel._reset_after_fork()
        self.assertIsNone(otel._INITIALIZED_PID)
        self.assertIsNone(otel._PROVIDERS['tracer'])

        test_logger.removeHandler(log_handler)

    def test_flask_instrumentation_no_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, 'test.sqlite')
            img_dir = os.path.join(tmpdir, 'images')
            os.makedirs(img_dir, exist_ok=True)
            with open('flask.json_template') as f:
                flask_cfg = json.load(f)
            flask_cfg.update({
                'SECRET_KEY': 'test-secret',
                'PASSWORD_KEY': 'test-password-key-32bytes-padding',
                'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
                'MIGRATION_FOLDER': os.path.abspath('migrations'),
                'INDI_ALLSKY_IMAGE_FOLDER': img_dir,
                'INDI_ALLSKY_DOCROOT': os.path.abspath('indi_allsky/flask/static'),
                'SESSION_COOKIE_SECURE': False,
                'REMEMBER_COOKIE_SECURE': False,
            })
            cfg_path = os.path.join(tmpdir, 'flask.json')
            with open(cfg_path, 'w') as f:
                json.dump(flask_cfg, f)

            os.environ['INDI_ALLSKY_FLASK_CONFIG'] = cfg_path
            os.environ['OTEL_EXPORTER_OTLP_ENDPOINT'] = 'http://127.0.0.1:4318'

            from indi_allsky.flask import create_app

            app = create_app()
            self.assertTrue(getattr(app, '_otel_instrumented', False))
            with app.test_client() as client:
                res = client.get('/indi-allsky/static/css/app.css')
                self.assertEqual(res.status_code, 200)


if __name__ == '__main__':
    unittest.main()
