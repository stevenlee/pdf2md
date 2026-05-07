import re

class MarkdownProcessor:
    def __init__(self):
        pass

    def clean_markdown(self, text: str) -> str:
        """主要清理邏輯"""
        text = self.normalize_latex(text)
        text = self.fix_code_blocks(text)
        text = self.remove_artifacts(text)
        return text

    def normalize_latex(self, text: str) -> str:
        """
        將 Marker 產生的 LaTeX 轉換為標準 Markdown 格式。
        Marker 通常使用 \\( \\) 或 \\[ \\]，轉換為 $ $ 或 $$ $$.
        """
        # 行內公式
        text = re.sub(r'\\\((.*?)\\\)', r'$\1$', text)
        # 區塊公式
        text = re.sub(r'\\\[(.*?)\\\]', r'$$\1$$', text, flags=re.DOTALL)
        return text

    def fix_code_blocks(self, text: str) -> str:
        """
        優化程式碼塊識別。
        """
        # 如果發現連續縮排且看起來像程式碼的內容，確保其被包裹在 ``` 中
        # 這部分通常由 Marker 處理，我們做二次檢查
        return text

    def remove_artifacts(self, text: str) -> str:
        """
        移除常見的 PDF 遺留雜質。
        """
        # 1. 移除 arXiv 常見的頁首
        text = re.sub(r'arXiv:\d{4}\.\d{5}v\d+\s+\[.*?\]\s+\d+\s+\w+\s+\d{4}', '', text)
        
        # 2. 修正被誤標為公式的引用 (例如 $$Liu et al., 2024$$)
        text = re.sub(r'\$\$(.*?\bet al\..*?)\$\$', r'\1', text)
        
        # 3. 移除 Marker 產生的內部頁面跳轉連結 (例如 [#page-37-0])
        text = re.sub(r'\[(.*?)\]\(#page-\d+-\d+\)', r'\1', text)
        
        return text

processor = MarkdownProcessor()
