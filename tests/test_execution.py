import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_code import load, ROOT


class Execution(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        tmp = tempfile.TemporaryDirectory(prefix="codespace-run-test-")
        self.addCleanup(tmp.cleanup)
        self.client = load(os.path.join(ROOT, "codespace"), tmp.name)
        self.path = Path(tmp.name)

    def test_browser_and_keychain_dependencies_stay_on_mac(self):
        for dependency in ["browser", "desktop", "keychain", "macos", "local-network"]:
            plan = self.client.execution_plan("compute", True, [dependency], "auto", 8192)
            self.assertEqual(plan["target"], "local")
            with self.assertRaises(ValueError):
                self.client.execution_plan("compute", True, [dependency], "space", 8192)

    def test_portability_must_be_declared_before_automatic_offload(self):
        self.assertEqual(self.client.execution_plan("build", False, [], "auto", 8192)["target"], "local")
        self.assertEqual(self.client.execution_plan("build", True, [], "auto", 8192)["target"], "space")
        self.assertEqual(self.client.execution_plan("general", True, [], "auto", 128)["target"], "local")

    def test_plan_does_not_execute_or_upload(self):
        with patch.object(self.client.subprocess, "call") as call, contextlib.redirect_stdout(io.StringIO()) as output:
            self.client.run_workload(["--portable", "--workload", "compute", "--plan", "--", "python3", "script.py"])
            call.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["target"], "space")

    def test_cloud_command_preserves_arguments_as_one_quoted_shell_command(self):
        with patch.object(self.client, "require", return_value="space"), patch.object(self.client.subprocess, "call", return_value=0) as call:
            self.client.run_workload(["--portable", "--target", "space", "--", "printf", "%s", "$(do-not-execute); with spaces"])
        args = call.call_args.args[0]
        self.assertIn("--async", args)
        import shlex
        self.assertEqual(shlex.split(args[-1]), ["printf", "%s", "$(do-not-execute); with spaces"])

    def test_local_input_staging_and_output_are_real(self):
        script = self.path / "compute.py"
        script.write_text("from pathlib import Path\nPath('out/result.txt').write_text('finished')\n")
        rc = self.client.run_workload(["--target", "local", "--file", str(script), "--", sys.executable, "input/compute.py"])
        self.assertEqual(rc, 0)
        outputs = list((self.client.RELEASE_ROOT / "jobs").glob("*/out/result.txt"))
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0].read_text(), "finished")


if __name__ == "__main__":
    unittest.main()
