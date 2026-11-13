"""Concatenate the pinned, standalone bridge and QA observer for Frida 16."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parent
package = root / "node_modules/frida-il2cpp-bridge"
metadata = json.loads((package / "package.json").read_text())
assert metadata["version"] == "0.9.1", "Use the pinned Frida 16-compatible bridge"
bridge = package / "dist/index.js"
agent = root / "unity_ui.js"
output = root / "unity_ui.bundle.js"
output.write_bytes(bridge.read_bytes() + b"\n;\n" + agent.read_bytes() + b"\n")
report = {"bridge": metadata["version"], "frida_server_and_client": "16.6.6",
          "bundle": output.name, "bytes": output.stat().st_size,
          "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
          "observer_sha256": hashlib.sha256(agent.read_bytes()).hexdigest(),
          "bridge_sha256": hashlib.sha256(bridge.read_bytes()).hexdigest(),
          "runtime_validation": "Pending actual Unity process; syntax checks alone are not runtime proof"}
(root / "unity_ui.manifest.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
