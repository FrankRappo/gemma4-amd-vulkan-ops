import unittest

import numpy as np

from llm_ops.vulkan.normalize_gemma4_mtp import (
    NEXTN_LAYERS_KEY,
    build_rope_freqs,
    comparable_value,
    mapped_metadata_key,
    mapped_tensor_name,
)


class NormalizeGemma4MtpTests(unittest.TestCase):
    def test_maps_legacy_architecture_metadata(self):
        self.assertEqual(
            mapped_metadata_key("gemma4_mtp.context_length"),
            "gemma4-assistant.context_length",
        )
        self.assertEqual(
            mapped_metadata_key("gemma4_mtp.backbone_embedding_length"),
            "gemma4-assistant.embedding_length_out",
        )
        self.assertEqual(NEXTN_LAYERS_KEY, "gemma4-assistant.nextn_predict_layers")
        self.assertEqual(mapped_metadata_key("general.name"), "general.name")

    def test_maps_only_legacy_projection_tensor_names(self):
        self.assertEqual(
            mapped_tensor_name("mtp_pre_proj.weight"),
            "nextn.pre_projection.weight",
        )
        self.assertEqual(
            mapped_tensor_name("mtp_post_proj.weight"),
            "nextn.post_projection.weight",
        )
        self.assertEqual(
            mapped_tensor_name("blk.0.attn_q.weight"),
            "blk.0.attn_q.weight",
        )

    def test_builds_official_gemma4_proportional_rope_tensor(self):
        values = build_rope_freqs(512)
        self.assertEqual(values.dtype, np.float32)
        self.assertEqual(values.shape, (256,))
        np.testing.assert_array_equal(values[:64], np.ones(64, dtype=np.float32))
        np.testing.assert_array_equal(
            values[64:], np.full(192, 1e30, dtype=np.float32)
        )

    def test_rejects_invalid_rope_dimensions(self):
        for value in (0, -2, 511):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_rope_freqs(value)

    def test_normalizes_numpy_metadata_for_exact_comparison(self):
        self.assertEqual(
            comparable_value(np.array([np.uint32(1), np.uint32(2)])),
            [1, 2],
        )


if __name__ == "__main__":
    unittest.main()
