"""Static public-storage wiring contract; real paths are checked by SimulatorProbe."""
from pathlib import Path
import re
import unittest


class StorageContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).resolve().parents[1] / "ElichikaHost.mm").read_text()

    def test_packs_and_imports_are_explicit_documents_configuration(self):
        self.assertRegex(self.source, r'NSString \*library=\[documentsRoot stringByAppendingPathComponent:@"Elichika"\]')
        for variable, component, key in (("packs", "packs", "packs_root"), ("imports", "imports", "imports_root")):
            self.assertRegex(self.source, rf'NSString \*{variable}=\[library stringByAppendingPathComponent:@"{component}"\]')
            self.assertRegex(self.source, rf'@"{key}"\s*:\s*{variable}\b')

    def test_server_data_stays_in_application_support(self):
        self.assertIn('URLsForDirectory:NSApplicationSupportDirectory', self.source)
        self.assertIn('[[support.path stringByAppendingPathComponent:@"Elichika"] stringByAppendingPathComponent:@"data"]', self.source)
        self.assertRegex(self.source, r'@"data_root"\s*:\s*root\b')


if __name__ == "__main__":
    unittest.main()
