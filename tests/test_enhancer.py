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

    def test_fix_mermaid_quotes_unquoted_label(self):
        fixed = self.enhancer.fix_mermaid_syntax("graph TD\n    A[Start] --> B[End]")
        self.assertIn('A["Start"]', fixed)
        self.assertIn('B["End"]', fixed)

    def test_fix_mermaid_collapses_nested_quotes(self):
        # 模型偶爾輸出巢狀雙引號，應轉成單引號且不產生破損括號
        fixed = self.enhancer.fix_mermaid_syntax('graph TD\n    A["a "b" c"] --> B["d"]')
        self.assertIn('''A["a 'b' c"]''', fixed)
        self.assertIn('B["d"]', fixed)
        self.assertNotIn('""', fixed)

    def test_fix_mermaid_does_not_cross_nodes(self):
        # 同行多節點時，巢狀引號修復不可吞掉後續節點
        fixed = self.enhancer.fix_mermaid_syntax('graph TD\n    A["ok"] --> B["It\'s a "test""]')
        self.assertIn('A["ok"]', fixed)
        self.assertIn('-->', fixed)
        self.assertIn('''B["It's a 'test'"]''', fixed)

    def test_fix_mermaid_label_with_brackets(self):
        # 標籤內含 ] 不應截斷
        fixed = self.enhancer.fix_mermaid_syntax('graph TD\n    A["data [1]"] --> B{x}')
        self.assertIn('A["data [1]"]', fixed)
        self.assertIn('B{"x"}', fixed)

    def test_fix_mermaid_preserves_shapes(self):
        fixed = self.enhancer.fix_mermaid_syntax('graph TD\n    A([s]) --> B((c)) --> C{{h}}')
        self.assertIn('A(["s"])', fixed)
        self.assertIn('B(("c"))', fixed)
        self.assertIn('C{{"h"}}', fixed)

    def test_validate_mermaid_does_not_add_brackets(self):
        # 已配對的標籤不應被重複補上括號
        code = 'graph TD\n    A["a (b)"] --> B["c [d]"]'
        result = self.enhancer.validate_mermaid(self.enhancer.fix_mermaid_syntax(code))
        self.assertNotIn(']]]', result)
        self.assertNotIn(')))', result)
        self.assertIn('A["a (b)"]', result)

    def test_fix_mermaid_edge_label_nested_quotes(self):
        # 使用者回報的實例：邊標籤含巢狀引號 + LaTeX 下標 {}
        code = 'graph TD\n    D -- "Commanded filament speed FS_{"t+1"}" --> A'
        fixed = self.enhancer.fix_mermaid_syntax(code)
        self.assertIn('''D -- "Commanded filament speed FS_{'t+1'}" --> A''', fixed)
        # 不可殘留巢狀雙引號，也不可把 _{ 誤判成節點
        self.assertNotIn('"t+1"', fixed)
        self.assertNotIn('FS_{"', fixed)

    def test_fix_mermaid_does_not_misfire_on_latex_subscript_in_edge(self):
        code = 'graph TD\n    A -- "x_{i}" --> B'
        fixed = self.enhancer.fix_mermaid_syntax(code)
        self.assertIn('A -- "x_{i}" --> B', fixed)

    def test_fix_mermaid_pipe_label(self):
        code = 'graph TD\n    A -->|Yes "really"| B'
        fixed = self.enhancer.fix_mermaid_syntax(code)
        self.assertIn('''A -->|"Yes 'really'"| B''', fixed)

    def test_fix_mermaid_node_and_edge_same_line(self):
        code = 'graph TD\n    A["start"] -- "go" --> B["end"]'
        fixed = self.enhancer.fix_mermaid_syntax(code)
        self.assertIn('A["start"]', fixed)
        self.assertIn('-- "go" -->', fixed)
        self.assertIn('B["end"]', fixed)

    def test_parse_smart_output_diagram(self):
        img_type, content = self.enhancer._parse_smart_output(
            "TYPE: DIAGRAM\ngraph TD\n    A[\"x\"] --> B[\"y\"]"
        )
        self.assertEqual(img_type, "DIAGRAM")
        self.assertTrue(content.startswith("graph TD"))

    def test_parse_smart_output_strips_fences(self):
        img_type, content = self.enhancer._parse_smart_output(
            "```\nTYPE: TABLE\n| a | b |\n| --- | --- |\n```"
        )
        self.assertEqual(img_type, "TABLE")
        self.assertIn("| a | b |", content)

    def test_parse_smart_output_other(self):
        img_type, content = self.enhancer._parse_smart_output("TYPE: OTHER")
        self.assertEqual(img_type, "OTHER")
        self.assertEqual(content, "")


if __name__ == "__main__":
    unittest.main()
