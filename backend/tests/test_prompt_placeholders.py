import unittest
from backend.llms.prompts import render_prompt
from backend.tickets.categories import DATASET_CATEGORIES, CATEGORY_GUIDANCE

class PromptPlaceholderTests(unittest.TestCase):
    def test_configured_versions_render(self):
        for version in ("V1", "V2", "V3"):
            for provider in ("gemini", "openai"):
                with self.subTest(version=version, provider=provider):
                    text = render_prompt(
                        version, provider, DATASET_CATEGORIES,
                        category_guidance=CATEGORY_GUIDANCE)
                    self.assertNotIn("{categories}", text)

    def test_unknown_version_cannot_render(self):
        for provider in ("gemini", "openai"):
            with self.subTest(provider=provider):
                with self.assertRaisesRegex(ValueError, "No V9 prompt"):
                    render_prompt(
                        "V9", provider, DATASET_CATEGORIES,
                        category_guidance=CATEGORY_GUIDANCE)

    def test_v1_matches_across_providers(self):
        self.assertEqual(
            render_prompt("V1", "gemini", DATASET_CATEGORIES, category_guidance=CATEGORY_GUIDANCE),
            render_prompt("V1", "openai", DATASET_CATEGORIES, category_guidance=CATEGORY_GUIDANCE))
