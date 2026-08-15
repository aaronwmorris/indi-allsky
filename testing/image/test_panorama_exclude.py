from pathlib import Path
import ast
import unittest


class TestPanoramaExclude(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parents[2]

    def _method_source(self, path, class_name, method_name):
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=str(path))
        class_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        )
        method_node = next(
            node
            for node in class_node.body
            if isinstance(node, ast.FunctionDef) and node.name == method_name
        )
        return ast.get_source_segment(source, method_node)

    def test_capture_exclusion_is_written_to_both_rows(self):
        image_path = self.project_root / 'indi_allsky' / 'image.py'
        process_source = self._method_source(
            image_path,
            'ImageWorker',
            'processImage',
        )
        panorama_source = self._method_source(
            image_path,
            'ImageWorker',
            'write_panorama_img',
        )

        self.assertIn(
            'image_exclude = asi676mc.excluded_from_downstream_measurements(',
            process_source,
        )
        self.assertIn('image_exclude=image_exclude', process_source)
        self.assertIn("image_metadata['exclude'] = True", process_source)
        self.assertIn("'exclude'    : image_exclude", panorama_source)

    def test_panorama_database_insert_persists_exclude(self):
        misc_db_path = self.project_root / 'indi_allsky' / 'flask' / 'miscDb.py'
        add_panorama_source = self._method_source(
            misc_db_path,
            'miscDb',
            'addPanoramaImage',
        )

        self.assertIn(
            "exclude=metadata.get('exclude', False)",
            add_panorama_source,
        )

    def test_manual_image_exclusion_updates_matching_panorama(self):
        views_path = self.project_root / 'indi_allsky' / 'flask' / 'views.py'
        exclude_source = self._method_source(
            views_path,
            'AjaxImageExcludeView',
            'dispatch_request',
        )

        self.assertIn('image.exclude = exclude', exclude_source)
        self.assertIn('IndiAllSkyDbPanoramaImageTable.query', exclude_source)
        self.assertIn(
            'IndiAllSkyDbPanoramaImageTable.camera_id == image.camera_id',
            exclude_source,
        )
        self.assertIn(
            'IndiAllSkyDbPanoramaImageTable.createDate == image.createDate',
            exclude_source,
        )
        self.assertIn("{'exclude': exclude}", exclude_source)

    def test_panorama_consumers_use_panorama_exclude(self):
        video_path = self.project_root / 'indi_allsky' / 'video.py'
        views_path = self.project_root / 'indi_allsky' / 'flask' / 'views.py'
        panorama_video_source = self._method_source(
            video_path,
            'VideoWorker',
            'generatePanoramaVideo',
        )
        image_loop_source = self._method_source(
            views_path,
            'JsonImageLoopView',
            'getLoopImages',
        )

        self.assertIn(
            'IndiAllSkyDbPanoramaImageTable.exclude == sa_false()',
            panorama_video_source,
        )
        self.assertIn('self.model.exclude == sa_false()', image_loop_source)

        query_helper_path = self.project_root / 'indi_allsky' / 'query_helpers.py'
        self.assertFalse(query_helper_path.exists())
        self.assertNotIn(
            'panorama_source_image_not_excluded_clause',
            panorama_video_source,
        )


if __name__ == '__main__':
    unittest.main()
