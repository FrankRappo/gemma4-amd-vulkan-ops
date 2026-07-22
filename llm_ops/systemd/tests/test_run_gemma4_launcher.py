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
            ("--tensor-split", "1,1"),
            ("--ctx-size", "327680"),
            ("--parallel", "2"),
            ("--batch-size", "1280"),
            ("--ubatch-size", "1280"),
            ("--image-min-tokens", "280"),
            ("--image-max-tokens", "1120"),
            ("--mtmd-batch-max-tokens", "1280"),
            ("--cache-ram", "0"),
        ):
            index = args.index(flag)
            self.assertEqual(args[index + 1], value)

    def test_custom_tensor_split_is_forwarded(self):
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
            env = {
                **os.environ,
                "BASE": str(root),
                "RUNTIME_ROOT": str(runtime),
                "MODEL": str(model),
                "MMPROJ": str(mmproj),
                "RPC_ADDR": f"127.0.0.1:{server.port}",
                "RPC_WAIT_SECONDS": "2",
                "TENSOR_SPLIT": "0.9,1.1",
            }
            result = subprocess.run(
                ["bash", str(SCRIPT)],
                env=env,
                text=True,
                capture_output=True,
                timeout=5,
                check=True,
            )

        args = result.stdout.splitlines()
        index = args.index("--tensor-split")
        self.assertEqual(args[index + 1], "0.9,1.1")

    def test_rejects_invalid_tensor_split(self):
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            env={**os.environ, "TENSOR_SPLIT": "1,0"},
            text=True,
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("TENSOR_SPLIT must contain two positive numbers", result.stderr)

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

    def test_speculative_profiles_are_forwarded(self):
        profiles = {
            "mtp": (
                {
                    "MTP_N_MAX": "4",
                    "MTP_N_MIN": "1",
                    "MTP_P_SPLIT": "0.2",
                    "MTP_P_MIN": "0.05",
                    "MTP_BACKEND_SAMPLING": "0",
                },
                (
                    ("--spec-type", "draft-mtp"),
                    ("--spec-draft-n-max", "4"),
                    ("--spec-draft-n-min", "1"),
                    ("--spec-draft-p-split", "0.2"),
                    ("--spec-draft-p-min", "0.05"),
                ),
            ),
            "ngram-mod": (
                {
                    "NGRAM_MOD_N_MIN": "8",
                    "NGRAM_MOD_N_MAX": "16",
                    "NGRAM_MOD_N_MATCH": "6",
                },
                (
                    ("--spec-type", "ngram-mod"),
                    ("--spec-ngram-mod-n-min", "8"),
                    ("--spec-ngram-mod-n-max", "16"),
                    ("--spec-ngram-mod-n-match", "6"),
                ),
            ),
            "ngram-simple": (
                {
                    "NGRAM_SIMPLE_SIZE_N": "8",
                    "NGRAM_SIMPLE_SIZE_M": "24",
                    "NGRAM_SIMPLE_MIN_HITS": "2",
                },
                (
                    ("--spec-type", "ngram-simple"),
                    ("--spec-ngram-simple-size-n", "8"),
                    ("--spec-ngram-simple-size-m", "24"),
                    ("--spec-ngram-simple-min-hits", "2"),
                ),
            ),
        }
        for mode, (extra_env, expected) in profiles.items():
            with (
                self.subTest(mode=mode),
                tempfile.TemporaryDirectory() as tmp,
                OneShotTcpServer() as server,
            ):
                root = Path(tmp)
                runtime = root / "runtime"
                runtime.mkdir()
                fake_server = runtime / "llama-server"
                fake_server.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
                fake_server.chmod(0o755)
                model = root / "model.gguf"
                mmproj = root / "mmproj.gguf"
                draft = root / "draft.gguf"
                model.touch()
                mmproj.touch()
                draft.touch()
                env = {
                    **os.environ,
                    "BASE": str(root),
                    "RUNTIME_ROOT": str(runtime),
                    "MODEL": str(model),
                    "MMPROJ": str(mmproj),
                    "DRAFT_MODEL": str(draft),
                    "RPC_ADDR": f"127.0.0.1:{server.port}",
                    "RPC_WAIT_SECONDS": "2",
                    "SPECULATIVE_MODE": mode,
                    **extra_env,
                }
                result = subprocess.run(
                    ["bash", str(SCRIPT)],
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=5,
                    check=True,
                )
                args = result.stdout.splitlines()
                for flag, value in expected:
                    index = args.index(flag)
                    self.assertEqual(args[index + 1], value)
                if mode == "mtp":
                    self.assertIn("--no-spec-draft-backend-sampling", args)

    def test_rejects_unknown_speculative_mode(self):
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            env={**os.environ, "SPECULATIVE_MODE": "unknown"},
            text=True,
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unsupported SPECULATIVE_MODE=unknown", result.stderr)


if __name__ == "__main__":
    unittest.main()
