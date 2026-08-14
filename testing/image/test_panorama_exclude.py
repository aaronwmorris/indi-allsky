from pathlib import Path
from types import SimpleNamespace
import ast
import unittest


class TestPanoramaExclude(unittest.TestCase):

    def test_clause_correlates_camera_timestamp_and_exclusion(self):
        project_root = Path(__file__).resolve().parents[2]
        helper_path = project_root / 'indi_allsky' / 'query_helpers.py'
        helper_source = helper_path.read_text(encoding='utf-8')
        helper_tree = ast.parse(helper_source, filename=str(helper_path))
        helper_node = next(
            node
            for node in helper_tree.body
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == 'panorama_source_image_not_excluded_clause'
            )
        )

        class FakeColumn(object):
            def __init__(self, name):
                self.name = name

            def __eq__(self, other):
                return ('equals', self.name, other.name)

            def is_(self, value):
                return ('is', self.name, value)

        class FakeExists(object):
            def where(self, predicate):
                self.predicate = predicate
                return self

            def __invert__(self):
                return ('not_exists', self.predicate)

        namespace = {
            'and_': lambda *conditions: ('and', conditions),
            'exists': FakeExists,
        }
        isolated_module = ast.Module(body=[helper_node], type_ignores=[])
        exec(
            compile(
                ast.fix_missing_locations(isolated_module),
                filename=str(helper_path),
                mode='exec',
            ),
            namespace,
        )

        panorama_model = SimpleNamespace(
            camera_id=FakeColumn('panorama.camera_id'),
            createDate=FakeColumn('panorama.createDate'),
        )
        image_model = SimpleNamespace(
            camera_id=FakeColumn('image.camera_id'),
            createDate=FakeColumn('image.createDate'),
            exclude=FakeColumn('image.exclude'),
        )
        clause = namespace['panorama_source_image_not_excluded_clause'](
            panorama_model,
            image_model,
        )

        self.assertEqual(
            clause,
            (
                'not_exists',
                (
                    'and',
                    (
                        (
                            'equals',
                            'image.camera_id',
                            'panorama.camera_id',
                        ),
                        (
                            'equals',
                            'image.createDate',
                            'panorama.createDate',
                        ),
                        ('is', 'image.exclude', True),
                    ),
                ),
            ),
        )

    def test_panorama_video_and_loop_apply_shared_clause(self):
        project_root = Path(__file__).resolve().parents[2]
        video_path = project_root / 'indi_allsky' / 'video.py'
        views_path = project_root / 'indi_allsky' / 'flask' / 'views.py'
        video_source = video_path.read_text(encoding='utf-8')
        views_source = views_path.read_text(encoding='utf-8')

        video_tree = ast.parse(video_source, filename=str(video_path))
        worker_class = next(
            node
            for node in video_tree.body
            if isinstance(node, ast.ClassDef) and node.name == 'VideoWorker'
        )
        panorama_video_method = next(
            node
            for node in worker_class.body
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == 'generatePanoramaVideo'
            )
        )
        panorama_video_source = ast.get_source_segment(
            video_source,
            panorama_video_method,
        )

        views_tree = ast.parse(views_source, filename=str(views_path))
        image_loop_class = next(
            node
            for node in views_tree.body
            if (
                isinstance(node, ast.ClassDef)
                and node.name == 'JsonImageLoopView'
            )
        )
        image_loop_filter = next(
            node
            for node in image_loop_class.body
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == '_apply_exclusion_filters'
            )
        )
        image_loop_source = ast.get_source_segment(
            views_source,
            image_loop_filter,
        )
        panorama_loop_class = next(
            node
            for node in views_tree.body
            if (
                isinstance(node, ast.ClassDef)
                and node.name == 'JsonPanoramaLoopView'
            )
        )
        panorama_loop_filter = next(
            node
            for node in panorama_loop_class.body
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == '_apply_exclusion_filters'
            )
        )
        panorama_loop_source = ast.get_source_segment(
            views_source,
            panorama_loop_filter,
        )

        for source in (panorama_video_source, panorama_loop_source):
            self.assertIn(
                'panorama_source_image_not_excluded_clause(',
                source,
            )
            self.assertIn('IndiAllSkyDbPanoramaImageTable', source)
            self.assertIn('IndiAllSkyDbImageTable', source)

        self.assertIn(
            'IndiAllSkyDbPanoramaImageTable.exclude == sa_false()',
            panorama_video_source,
        )
        self.assertIn('self.model.exclude == sa_false()', image_loop_source)


if __name__ == '__main__':
    unittest.main()
