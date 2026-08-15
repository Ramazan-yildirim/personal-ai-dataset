import unittest


from scripts.personal_ai_ui import (
    NO_SOURCE,
    choice_id,
    optional_text,
    selected_visibilities,
)


class UIHelpersTestCase(unittest.TestCase):
    def test_optional_text(self):
        self.assertIsNone(optional_text("   "))
        self.assertEqual(optional_text(" value "), "value")

    def test_choice_id(self):
        self.assertEqual(choice_id("12 — Synthetic source"), 12)
        self.assertIsNone(choice_id(NO_SOURCE, allow_none=True))
        with self.assertRaises(ValueError):
            choice_id("invalid")

    def test_private_visibility_requires_opt_in(self):
        self.assertEqual(
            selected_visibilities(False, False),
            ("public",),
        )
        self.assertEqual(
            selected_visibilities(True, True),
            ("public", "private", "internal"),
        )


if __name__ == "__main__":
    unittest.main()
