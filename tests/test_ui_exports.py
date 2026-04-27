from __future__ import annotations

import unittest

from medical_deep_research.ui import _plain_report_text


class UiExportTests(unittest.TestCase):
    def test_plain_report_text_removes_markdown_markup(self) -> None:
        markdown = """# Final Report

See [trial title](https://example.test/paper) and `NRS pain score`.

**Conclusion:** pain improved.

```json
{"effect": "lower pain"}
```

- Reference one
"""

        text = _plain_report_text(markdown)

        self.assertIn("Final Report", text)
        self.assertIn("trial title", text)
        self.assertIn("NRS pain score", text)
        self.assertIn("Conclusion: pain improved.", text)
        self.assertIn('{"effect": "lower pain"}', text)
        self.assertIn("- Reference one", text)
        self.assertNotIn("https://example.test/paper", text)
        self.assertNotIn("```", text)
        self.assertNotIn("**", text)


if __name__ == "__main__":
    unittest.main()
