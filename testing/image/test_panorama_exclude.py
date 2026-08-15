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

    def test_capture_exclusion_is_persisted_on_panorama(self):
        image_path = self.project_root / 'indi_allsky' / 'image.py'
        panorama_source = self._method_source(
            image_path,
            'ImageWorker',
            'write_panorama_img',
        )
        misc_db_path = self.project_root / 'indi_allsky' / 'flask' / 'miscDb.py'
        add_panorama_source = self._method_source(
            misc_db_path,
            'miscDb',
            'addPanoramaImage',
        )

        self.assertIn(
            "'exclude'    : asi676mc.excluded_from_downstream_measurements(",
            panorama_source,
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

        for expected in (
            'IndiAllSkyDbPanoramaImageTable.query',
            'IndiAllSkyDbPanoramaImageTable.camera_id == image.camera_id',
            'IndiAllSkyDbPanoramaImageTable.createDate == image.createDate',
            "{'exclude': exclude}",
        ):
            self.assertIn(expected, exclude_source)


if __name__ == '__main__':
    unittest.main()
