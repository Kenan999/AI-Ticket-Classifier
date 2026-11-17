import unittest
from evaluation.prompts import render_prompt
from backend.classifier import DATASET_CATEGORIES, CATEGORY_GUIDANCE

class PromptPlaceholderTests(unittest.TestCase):
    def test_reserved_versions_cannot_render(self):
        for version in ("V2", "V3"):
            for provider in ("gemini", "openai"):
                with self.subTest(version=version, provider=provider):
                    with self.assertRaisesRegex(ValueError, "not configured"):
                        render_prompt(version, provider, DATASET_CATEGORIES, category_guidance=CATEGORY_GUIDANCE)

    def test_v1_matches_across_providers(self):
        self.assertEqual(
            render_prompt("V1", "gemini", DATASET_CATEGORIES, category_guidance=CATEGORY_GUIDANCE),
            render_prompt("V1", "openai", DATASET_CATEGORIES, category_guidance=CATEGORY_GUIDANCE))
