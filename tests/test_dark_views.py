import ast
from datetime import datetime
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VIEWS_PATH = REPOSITORY_ROOT.joinpath('indi_allsky', 'flask', 'views.py')


def _view_function(function_name, namespace):
    """Load one module-level helper without importing optional web dependencies."""
    module = ast.parse(VIEWS_PATH.read_text(encoding='utf-8'))
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == function_name
    )
    extracted = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(extracted)
    exec(compile(extracted, str(VIEWS_PATH), 'exec'), namespace)
    return namespace[function_name]


def _dark_flush_dispatch(namespace):
    """Load the real view method without importing optional web dependencies."""
    module = ast.parse(VIEWS_PATH.read_text(encoding='utf-8'))
    view_class = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef)
        and node.name == 'AjaxDarkLibraryFlushView'
    )
    dispatch = next(
        node
        for node in view_class.body
        if isinstance(node, ast.FunctionDef)
        and node.name == 'dispatch_request'
    )
    dispatch.decorator_list = []
    extracted = ast.Module(body=[dispatch], type_ignores=[])
    ast.fix_missing_locations(extracted)
    exec(compile(extracted, str(VIEWS_PATH), 'exec'), namespace)
    return namespace['dispatch_request']


def test_dark_task_candidates_only_query_main_queue():
    class FakeField:
        def __init__(self, name):
            self.name = name

        def __eq__(self, value):
            return ('equals', self.name, value)

        def in_(self, values):
            return ('in', self.name, tuple(values))

        def desc(self):
            return ('descending', self.name)

    class FakeQuery:
        def __init__(self):
            self.filters = []
            self.order = None

        def filter(self, expression):
            self.filters.append(expression)
            return self

        def order_by(self, expression):
            self.order = expression
            return self

        def all(self):
            return ['candidate']

    query = FakeQuery()
    task_model = SimpleNamespace(
        query=query,
        queue=FakeField('queue'),
        state=FakeField('state'),
        createDate=FakeField('createDate'),
    )
    queue_state = SimpleNamespace(
        MANUAL='manual',
        QUEUED='queued',
        RUNNING='running',
        SUCCESS='success',
        FAILED='failed',
        EXPIRED='expired',
    )
    helper = _view_function('_dark_task_candidates', {
        'IndiAllSkyDbTaskQueueTable': task_model,
        'TaskQueueQueue': SimpleNamespace(MAIN='main'),
        'TaskQueueState': queue_state,
    })

    assert helper() == ['candidate']
    assert ('equals', 'queue', 'main') in query.filters
    assert query.order == ('descending', 'createDate')


def test_confirmed_library_deletion_queues_aggregate_storage_size():
    """Exercise the confirmed request path that queues the deletion task."""
    task_store = []

    class FakeSession:
        def __init__(self):
            self.committed = False

        def add(self, task):
            task_store.append(task)

        def commit(self):
            self.committed = True

        def rollback(self):
            raise AssertionError('The valid deletion request should not roll back')

    class FakeTask:
        def __init__(self, **kwargs):
            self.id = 41
            self.__dict__.update(kwargs)

    selection = {'dark_ids': [10, 11], 'bpm_ids': [20, 21]}
    resolved = {
        'dark_frames': 2,
        'bad_pixel_maps': 2,
        'size_bytes': 123456,
    }
    batch = {
        'camera_id': 1,
        'camera': SimpleNamespace(name='Test Camera', uuid='camera-uuid'),
        'selection': selection,
        'signature': 'selection-signature',
        'resolved': resolved,
    }
    request_data = {
        'mode': 'remove',
        'camera_id': 1,
        'label': 'the bin 2 image profile',
        'selection': selection,
        'selection_signature': 'selection-signature',
        'confirmation': 'DELETE',
    }
    session = FakeSession()
    namespace = {
        '_can_save_standard_configuration': lambda: True,
        '_dark_resolve_request_batches': lambda request_data, selector: [batch],
        '_dark_public_selection_batches': lambda batches: [selection],
        '_dark_combined_selection_signature': lambda batches: 'selection-signature',
        '_dark_automation_owner': lambda: 'user:test',
        '_find_active_dark_task': lambda: None,
        '_prepare_dark_capture_service': lambda view, operation: None,
        'request': SimpleNamespace(get_json=lambda silent=True: request_data),
        'jsonify': lambda value: value,
        'datetime': datetime,
        'timezone': timezone,
        'IndiAllSkyDbTaskQueueTable': FakeTask,
        'TaskQueueQueue': SimpleNamespace(MAIN='main'),
        'TaskQueueState': SimpleNamespace(MANUAL='manual'),
        'db': SimpleNamespace(session=session),
        'SQLAlchemyError': RuntimeError,
        'app': SimpleNamespace(logger=SimpleNamespace(exception=lambda *args: None)),
        'dark_automation': SimpleNamespace(
            DarkAutomationError=ValueError,
            CAPTURE_MODE_SINGLE='single',
            task_public_status=lambda task: {'task_id': task.id},
            select_camera_library_entries=lambda *args, **kwargs: None,
        ),
    }
    dispatch_request = _dark_flush_dispatch(namespace)
    view = SimpleNamespace(cameraSetup=lambda camera_id: None)

    response = dispatch_request(view)

    assert response == {'task_id': 41, 'service_start_warning': None}
    assert session.committed is True
    assert len(task_store) == 1
    assert task_store[0].data['removal_size_bytes'] == resolved['size_bytes']
