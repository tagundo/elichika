"""Small host checks for compiled product-class boundaries and build inputs."""
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('mv_dex_build', HERE/'build_menu_dex.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class BridgeClassBoundaryTest(unittest.TestCase):
    def test_exact_product_roots_and_nested_classes(self):
        prefix='com/klab/lovelive/allstars/fovmod/'
        for root in BUILD.BRIDGE_NAMES:
            self.assertTrue(BUILD.bridge_class_allowed(prefix+root+'.class'))
            self.assertTrue(BUILD.bridge_class_allowed(prefix+root+'$1.class'))
            self.assertTrue(BUILD.bridge_class_allowed(prefix+root+'$Config.class'))

    def test_tests_and_lookalike_classes_are_rejected(self):
        for name in ['AndroidMVEncoderDeviceTest', 'MVExportContractTest',
                     'FovModTest', 'AndroidMVExportOther']:
            self.assertFalse(BUILD.bridge_class_allowed(
                'com/klab/lovelive/allstars/fovmod/'+name+'.class'))
        self.assertFalse(BUILD.bridge_class_allowed('other/package/AndroidMVExport.class'))
        self.assertFalse(BUILD.bridge_class_allowed('com/klab/lovelive/allstars/fovmod/AndroidMVEncoder$1.java'))

    def test_sources_are_explicit_product_units(self):
        self.assertEqual({p.name for p in BUILD.BRIDGE_SOURCES},
            {'FovMod.java','AndroidMVExport.java','AndroidMVEncoder.java','MVExportContract.java',
             'MP4Gapless.java','MVExportService.java'})


if __name__ == '__main__':
    unittest.main()
