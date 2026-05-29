import unittest

from src.enhancer import MarkdownEnhancer


class MarkdownEnhancerTest(unittest.TestCase):
    def setUp(self):
        self.enhancer = MarkdownEnhancer()

    def test_rejects_old_document_prompt_example_leak(self):
        leaked_output = """
## 10 目標與投資細節 OBJECTIVE AND INVESTMENT DETAILS

**風險承受度 Risk Exposure** ☐低 Low ☐中度 Moderate ☐投機 Speculation ☐高風險 High Risk

### 其他投資 Other Investments

| 投資 Investment | 投資價值 Investment Value |
| --- | --- |
| 股票 Equities | 價值 Value($) |
"""

        self.assertFalse(self.enhancer.is_valid_document_output(leaked_output))

    def test_rejects_new_document_prompt_placeholder_leak(self):
        leaked_output = """
## [visible section title]

**[visible field label]** ☐[visible option] ☑[visible selected option]

| [visible column A] | [visible column B] |
| --- | --- |
| [visible cell A1] | [visible cell B1] |
"""

        self.assertFalse(self.enhancer.is_valid_document_output(leaked_output))

    def test_accepts_unrelated_structured_document_output(self):
        patent_cover_output = """
### (12) United States Patent

**Patent No.:** US 12,613,857 B2

**Date of Patent:** Apr. 28, 2026
"""

        self.assertTrue(self.enhancer.is_valid_document_output(patent_cover_output))


if __name__ == "__main__":
    unittest.main()
