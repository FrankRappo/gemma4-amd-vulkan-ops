import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "llm-amd-compute-profile.sh"


class AmdComputeProfileTests(unittest.TestCase):
    def test_enable_and_rollback_resolve_profile_indexes_by_name(self):
        with tempfile.TemporaryDirectory() as directory:
            drm = Path(directory)
            device = drm / "card7" / "device"
            device.mkdir(parents=True)
            (device / "vendor").write_text("0x1002\n", encoding="ascii")
            profile = device / "pp_power_profile_mode"
            profile.write_text(
                "PROFILE_INDEX(NAME)\n"
                " 0 BOOTUP_DEFAULT*:\n"
                " 5 COMPUTE :\n",
                encoding="ascii",
            )
            env = {**os.environ, "DRM_ROOT": str(drm)}

            subprocess.run(
                ["sh", str(SCRIPT), "enable"], env=env, check=True, capture_output=True
            )
            self.assertEqual(profile.read_text(encoding="ascii"), "5\n")

            profile.write_text(
                "PROFILE_INDEX(NAME)\n"
                " 0 BOOTUP_DEFAULT :\n"
                " 5 COMPUTE*:\n",
                encoding="ascii",
            )
            subprocess.run(
                ["sh", str(SCRIPT), "rollback"], env=env, check=True, capture_output=True
            )
            self.assertEqual(profile.read_text(encoding="ascii"), "0\n")

    def test_non_amd_device_is_not_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            drm = Path(directory)
            device = drm / "card0" / "device"
            device.mkdir(parents=True)
            (device / "vendor").write_text("0x1234\n", encoding="ascii")
            profile = device / "pp_power_profile_mode"
            profile.write_text("unchanged\n", encoding="ascii")
            result = subprocess.run(
                ["sh", str(SCRIPT), "enable"],
                env={**os.environ, "DRM_ROOT": str(drm)},
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(profile.read_text(encoding="ascii"), "unchanged\n")


if __name__ == "__main__":
    unittest.main()
