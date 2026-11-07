"""Run the real pure JS spawn-provenance contract; never touches a device."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import unittest


class SpawnBindingContractTests(unittest.TestCase):
    def test_actual_javascript_policy_contract(self):
        root = Path(__file__).resolve().parent
        helper = root / "spawn_bindings.js"
        before = hashlib.sha256(helper.read_bytes()).hexdigest()
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for the real JS policy contract")
        completed = subprocess.run([node, "--test", "--test-reporter=tap",
            str(root / "test_spawn_binding_contract.js")],
            cwd=root, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(hashlib.sha256(helper.read_bytes()).hexdigest(), before,
                         "Pure contract tests must not alter the actual helper")
        self.assertEqual(completed.returncode, 0,
                         (completed.stdout + "\n" + completed.stderr)[-16000:])
        self.assertIn("# fail 0", completed.stdout)


if __name__ == "__main__":
    unittest.main()
