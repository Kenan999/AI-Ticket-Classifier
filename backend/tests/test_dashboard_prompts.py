"""Prompt cards must show the category guidance actually sent to providers."""
import unittest
from html import escape
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from backend.keyword_classifier import CATEGORY_GUIDANCE, DATASET_CATEGORIES
from backend.evaluation.dashboard import prompt_texts
from backend.llms.prompts import CATEGORY_GUIDANCE_V2, render_prompt


class DashboardPromptTests(unittest.TestCase):
    @patch("backend.evaluation.evaluate.load_env", return_value={})
    def test_cards_match_rendered_provider_prompts(self, _load_env):
        for version in ("V1", "V2", "V3"):
            found = prompt_texts(version)
            for provider in ("gemini", "openai"):
                with self.subTest(version=version, provider=provider):
                    expected = render_prompt(
                        version, provider, DATASET_CATEGORIES,
                        category_guidance=CATEGORY_GUIDANCE,
                    )
                    self.assertIn(provider, found[expected])
                    self.assertNotIn("{categories}", expected)
        self.assertNotEqual(prompt_texts("V1"), prompt_texts("V2"))
        self.assertNotEqual(prompt_texts("V2"), prompt_texts("V3"))

    @patch("backend.evaluation.evaluate.load_env", return_value={})
    def test_v2_card_displays_guidance_and_highlights_changes(self, _load_env):
        app = AppTest.from_string(
            "from backend.evaluation.dashboard import render_prompts\nrender_prompts()",
            default_timeout=20,
        ).run()
        self.assertFalse(app.exception)
        self.assertEqual([card.label for card in app.expander],
                         ["Prompt V1", "Prompt V2", "Prompt V3"])
        html = [element.proto.body for element in app.get("html")]
        self.assertIn(escape(CATEGORY_GUIDANCE), html[0])
        self.assertIn(escape(CATEGORY_GUIDANCE_V2), html[1])
        self.assertNotEqual(html[0], html[1])
        self.assertIn("<span", html[2])
        self.assertIn("delivery address", html[2])
        self.assertIn(escape(CATEGORY_GUIDANCE_V2), html[3])
