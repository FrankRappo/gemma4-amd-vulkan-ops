import os
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "run-gemma4-31b-2gpu-vision.sh"


class OneShotTcpServer:
    def __enter__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()
        return self

    def _accept(self):
        connection, _ = self.sock.accept()
        connection.close()

    def __exit__(self, exc_type, exc, traceback):
        self.sock.close()
        self.thread.join(timeout=1)


class GemmaVisionLauncherTest(unittest.TestCase):
    def test_default_profile_passes_high_resolution_arguments(self):
        with tempfile.TemporaryDirectory() as tmp, OneShotTcpServer() as server:
            root = Path(tmp)
            runtime = root / "runtime"
            runtime.mkdir()
            fake_server = runtime / "llama-server"
            fake_server.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
            fake_server.chmod(0o755)
            model = root / "model.gguf"
            mmproj = root / "mmproj.gguf"
            model.touch()
            mmproj.touch()

            env = os.environ.copy()
            env.update(
                {
                    "BASE": str(root),
                    "RUNTIME_ROOT": str(runtime),
                    "MODEL": str(model),
                    "MMPROJ": str(mmproj),
                    "RPC_ADDR": f"127.0.0.1:{server.port}",
                    "RPC_WAIT_SECONDS": "2",
                }
            )
            result = subprocess.run(
                ["bash", str(SCRIPT)],
                env=env,
                text=True,
                capture_output=True,
                timeout=5,
                check=True,
            )

        args = result.stdout.splitlines()
        for flag, value in (
            ("--batch-size", "1280"),
            ("--ubatch-size", "1280"),
            ("--image-min-tokens", "280"),
            ("--image-max-tokens", "1120"),
            ("--mtmd-batch-max-tokens", "1280"),
            ("--cache-ram", "0"),
        ):
            index = args.index(flag)
            self.assertEqual(args[index + 1], value)

    def test_rejects_batch_smaller_than_image_budget(self):
        env = os.environ.copy()
        env.update(
            {
                "VISION_MAX_TOKENS": "1120",
                "VISION_BATCH_SIZE": "512",
            }
        )
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            env=env,
            text=True,
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "VISION_BATCH_SIZE must be >= VISION_MAX_TOKENS (1120)",
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
