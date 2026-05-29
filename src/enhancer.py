import os
import re
import asyncio
import logging
from pathlib import Path
from src.processor import processor
from src.config import settings

logger = logging.getLogger(__name__)

DOCUMENT_PROMPT_LEAK_PATTERNS = [
    "目標與投資細節",
    "OBJECTIVE AND INVESTMENT DETAILS",
    "風險承受度 Risk Exposure",
    "帳戶投資目標 Account Investment Objectives",
    "其他投資 Other Investments",
    "[visible section title]",
    "[visible field label]",
    "[visible column A]",
    "[visible cell A1]",
]


class MarkdownEnhancer:
    def __init__(self):
        self.processor = processor

    def is_markdown_table(self, text: str) -> bool:
        """判斷 LLM 輸出是否像有效的 Markdown table。"""
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        if len(lines) < 2:
            return False
        if lines[0].upper() == "NOT_A_TABLE":
            return False
        if not lines[0].startswith("|") or not lines[0].endswith("|"):
            return False
        separator = lines[1]
        return bool(re.match(r'^\|\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$', separator))

    def clean_markdown_table(self, text: str) -> str:
        """移除模型偶爾加上的 fence 或前後說明，只保留 table 行。"""
        text = re.sub(r'```(?:markdown|md)?|```', '', text).strip()
        table_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
        return "\n".join(table_lines).strip()

    def is_valid_document_output(self, text: str) -> bool:
        """判斷 LLM 輸出是否像有效的文件/表單 Markdown 內容。"""
        text = text.strip()
        if not text or len(text) < 20:
            return False
        if self.has_document_prompt_leak(text):
            return False
        # 應至少包含一些結構性標記（標題、表格、粗體等）
        has_heading = bool(re.search(r'^#{1,4}\s', text, re.MULTILINE))
        has_table = "|" in text and "---" in text
        has_bold = "**" in text
        has_checkbox = "☐" in text or "☑" in text or "✓" in text or "✔" in text
        # 至少有其中兩項
        score = sum([has_heading, has_table, has_bold, has_checkbox])
        return score >= 1

    def has_document_prompt_leak(self, text: str) -> bool:
        """偵測 vision_to_document 舊範例被模型複製到輸出的情況。"""
        normalized = re.sub(r"\s+", " ", text)
        matches = sum(
            1 for pattern in DOCUMENT_PROMPT_LEAK_PATTERNS
            if pattern in normalized
        )
        return matches >= 2

    def clean_document_output(self, text: str) -> str:
        """清理文件 OCR 輸出，移除多餘的 fence。"""
        text = re.sub(r'```(?:markdown|md)?|```', '', text).strip()
        return text

    def fix_mermaid_syntax(self, code: str) -> str:
        """強制為 Mermaid 標籤加上雙引號，並將內部的雙引號轉為單引號 (單次替換)"""
        # 匹配上下文：行首、空格、或是 Mermaid 的箭頭
        context = r'(^|[\s\-\=\>])'
        # 節點 ID 必須以字母數字或底線開頭，避免匹配到箭頭 (如 -- )
        id_pattern = r'([a-zA-Z0-9_][a-zA-Z0-9._-]*)'
        
        # 定義各類括號的配對 branch，確保非貪婪匹配 (.*?) 能準確停在對應的閉合括號上
        # 共 7 種括號，對應群組為：
        # 1: context, 2: ID
        # 每種括號佔 3 個群組 (ob, content, cb)
        branches = [
            r'(\[\[)(.*?)(\]\])',
            r'(\(\()(.*?)(\)\))',
            r'(\{\{)(.*?)(\}\})',
            r'(\[)(.*?)(\])',
            r'(\()(.*?)(\))',
            r'(\{)(.*?)(\})',
            r'(>)(.*?)(\])'
        ]
        
        pattern = context + id_pattern + r'\s*(?:' + '|'.join(branches) + r')'
        
        def repl(m):
            prefix = m.group(1)
            node_id = m.group(2)
            
            # 尋找匹配的 branch (從 group 3 開始，每 3 個為一組)
            ob, content, cb = None, None, None
            for i in range(3, 24, 3):
                if m.group(i) is not None:
                    ob = m.group(i)
                    content = m.group(i+1)
                    cb = m.group(i+2)
                    break
                    
            if content is None:
                return m.group(0)
                
            # 如果內容已經是最外層有引號包覆，我們只處理裡面的引號
            if content.startswith('"') and content.endswith('"') and len(content) >= 2:
                inner = content[1:-1]
                inner = inner.replace('"', "'")
                return f'{prefix}{node_id}{ob}"{inner}"{cb}'
                
            # 如果沒有包覆，則包覆起來，並將內部的雙引號轉為單引號
            clean_content = content.replace('"', "'")
            return f'{prefix}{node_id}{ob}"{clean_content}"{cb}'

        return re.sub(pattern, repl, code, flags=re.MULTILINE)

    def validate_mermaid(self, code: str) -> str:
        """驗證並修復常見的 Mermaid 語法問題"""
        lines = code.strip().splitlines()
        fixed_lines = []
        
        for line in lines:
            stripped = line.strip()
            
            # 移除空行
            if not stripped:
                fixed_lines.append(line)
                continue
            
            # 修復常見問題：行尾多餘的分號
            stripped = stripped.rstrip(';')
            
            # 修復常見問題：節點定義中的未閉合括號
            # 計算括號平衡
            open_sq = stripped.count('[') - stripped.count(']')
            open_rnd = stripped.count('(') - stripped.count(')')
            open_curl = stripped.count('{') - stripped.count('}')
            
            # 嘗試修復未閉合括號
            if open_sq > 0:
                stripped += ']' * open_sq
            if open_rnd > 0:
                stripped += ')' * open_rnd
            if open_curl > 0:
                stripped += '}' * open_curl
            
            fixed_lines.append(stripped)
        
        result = '\n'.join(fixed_lines)
        
        # 確保第一行是 diagram type declaration
        first_meaningful = next(
            (l.strip() for l in result.splitlines() if l.strip()), ''
        )
        valid_starts = [
            'graph ', 'graph\t', 'flowchart ',
            'sequenceDiagram', 'classDiagram',
            'stateDiagram', 'erDiagram', 'gantt',
            'pie', 'gitgraph', 'mindmap',
        ]
        if not any(first_meaningful.startswith(s) for s in valid_starts):
            # 嘗試找到有效的起始行
            new_lines = []
            found_start = False
            for line in result.splitlines():
                if not found_start and any(line.strip().startswith(s) for s in valid_starts):
                    found_start = True
                if found_start:
                    new_lines.append(line)
            if new_lines:
                result = '\n'.join(new_lines)
        
        return result

    def is_valid_mermaid(self, code: str) -> bool:
        """檢查 Mermaid 程式碼是否有效"""
        valid_keywords = [
            "graph ", "flowchart ", "sequenceDiagram", "classDiagram",
            "stateDiagram", "erDiagram", "gantt", "pie", "gitgraph", "mindmap"
        ]
        has_keyword = any(kw in code for kw in valid_keywords)
        # 至少有一個箭頭連接或節點定義
        has_structure = '-->' in code or '---' in code or '==' in code or '[' in code
        # 不能太短
        has_content = len(code.strip()) > 30
        
        return has_keyword and has_structure and has_content

    async def process_image(
        self,
        img_name: str,
        img_path: str,
        output_dir: str,
        convert_mermaid: bool = True,
        convert_tables: bool = True,
    ) -> tuple[str, str]:
        """非同步處理單張圖片，返回 (舊標籤, 替換文字)

        處理流程:
        1. 先用 vision 模型分類圖片類型 (TABLE / DOCUMENT / DIAGRAM / OTHER)
        2. 根據分類結果路由到對應的轉換管道
        """
        logger.info(f"開始非同步轉換圖片: {img_name}")
        try:
            from src.llm_client import llm_client
            
            # ===== Stage 1: 圖片分類 =====
            img_type = await llm_client.async_vision_classify(img_path)
            logger.info(f"圖片 {img_name} 分類結果: {img_type}")
            
            # ===== Stage 2: 根據分類路由 =====

            # --- TABLE: 純表格提取 ---
            if img_type == "TABLE" and convert_tables:
                result = await self._handle_table(llm_client, img_name, img_path, output_dir)
                if result:
                    return result

            # --- DOCUMENT: 文件/表單提取 (文字 + 表格混合) ---
            if img_type == "DOCUMENT" and convert_tables:
                result = await self._handle_document(llm_client, img_name, img_path, output_dir)
                if result:
                    return result
            
            # --- DIAGRAM: Mermaid 圖表轉換 ---
            if img_type == "DIAGRAM" and convert_mermaid:
                result = await self._handle_mermaid(llm_client, img_name, img_path, output_dir)
                if result:
                    return result
            
            # --- Fallback: 分類不明確時的智慧路由 ---
            if img_type == "OTHER" or img_type not in ("TABLE", "DOCUMENT", "DIAGRAM"):
                # 先嘗試 document 提取
                if convert_tables:
                    result = await self._handle_document(llm_client, img_name, img_path, output_dir)
                    if result:
                        return result
            
            # 保留原始圖片
            logger.info(f"{img_name} 無法轉換為結構化格式，保留原始圖片")
            img_rel_path = os.path.relpath(img_path, output_dir)
            return f"![]({img_name})", f"![]({img_rel_path})"
        except Exception as e:
            logger.error(f"轉換 {img_name} 失敗: {e}")
            img_rel_path = os.path.relpath(img_path, output_dir)
            return f"![]({img_name})", f"![]({img_rel_path})"

    async def _handle_table(
        self, llm_client, img_name: str, img_path: str, output_dir: str
    ) -> tuple[str, str] | None:
        """處理純表格類型圖片"""
        try:
            table_text = await llm_client.async_vision_to_markdown_table(img_path)
            clean_table = self.clean_markdown_table(table_text)
            
            if self.is_markdown_table(clean_table):
                img_rel_path = os.path.relpath(img_path, output_dir)
                replacement = (
                    f"\n\n{clean_table}\n\n"
                    f"> [!NOTE]\n"
                    f"> 原始表格圖片比對: ![]({img_rel_path})\n"
                )
                return f"![]({img_name})", replacement
        except Exception as e:
            logger.warning(f"表格 OCR {img_name} 失敗: {e}")
        return None

    async def _handle_document(
        self, llm_client, img_name: str, img_path: str, output_dir: str
    ) -> tuple[str, str] | None:
        """處理文件/表單類型圖片（文字 + 表格混合內容）"""
        try:
            doc_text = await llm_client.async_vision_to_document(img_path)
            clean_doc = self.clean_document_output(doc_text)
            
            if self.is_valid_document_output(clean_doc):
                img_rel_path = os.path.relpath(img_path, output_dir)
                replacement = (
                    f"\n\n{clean_doc}\n\n"
                    f"> [!NOTE]\n"
                    f"> 原始文件圖片比對: ![]({img_rel_path})\n"
                )
                return f"![]({img_name})", replacement
        except Exception as e:
            logger.warning(f"文件 OCR {img_name} 失敗: {e}")
        return None

    async def _handle_mermaid(
        self, llm_client, img_name: str, img_path: str, output_dir: str,
        max_retries: int = 2,
    ) -> tuple[str, str] | None:
        """處理圖表類型圖片，轉換為 Mermaid。支援重試以提升穩定性。"""
        for attempt in range(max_retries):
            try:
                mermaid_code = await llm_client.async_vision_to_mermaid(img_path)
                
                # 移除 fence
                clean_mermaid = re.sub(r'(```mermaid|```)', '', mermaid_code).strip()
                
                # 驗證是否為有效 Mermaid
                if not self.is_valid_mermaid(clean_mermaid):
                    logger.warning(
                        f"Mermaid 第 {attempt+1} 次嘗試無效 ({img_name})，"
                        + ("重試中..." if attempt < max_retries - 1 else "放棄")
                    )
                    continue
                
                # 修復語法
                fixed_mermaid = self.fix_mermaid_syntax(clean_mermaid)
                # 額外驗證修復
                fixed_mermaid = self.validate_mermaid(fixed_mermaid)
                
                img_rel_path = os.path.relpath(img_path, output_dir)
                replacement = (
                    f"\n\n```mermaid\n{fixed_mermaid}\n```\n\n"
                    f"> [!NOTE]\n"
                    f"> 原始圖片比對: ![]({img_rel_path})\n"
                )
                return f"![]({img_name})", replacement
            except Exception as e:
                logger.warning(f"Mermaid 轉換 {img_name} 第 {attempt+1} 次失敗: {e}")
        return None

    async def enhance_async(
        self,
        raw_md_path: Path,
        output_dir: str,
        convert_mermaid: bool = True,
        convert_tables: bool = True,
    ) -> str:
        with open(raw_md_path, 'r', encoding='utf-8') as f:
            full_text = f.read()

        # 找出所有 marker 產生的圖片標籤: ![](filename.jpeg)
        img_tags = re.findall(r'!\[\]\(([^)]+)\)', full_text)
        
        img_subdir = os.path.join(output_dir, "images", raw_md_path.name.replace("_raw.md", ""))
        
        tasks = []
        semaphore = asyncio.Semaphore(max(1, settings.VISION_MAX_CONCURRENCY))

        async def process_image_limited(img_name: str, img_path: str):
            async with semaphore:
                return await self.process_image(
                    img_name,
                    img_path,
                    output_dir,
                    convert_mermaid=convert_mermaid,
                    convert_tables=convert_tables,
                )

        for img_name in img_tags:
            img_path = os.path.join(img_subdir, img_name)
            if os.path.exists(img_path) and (convert_mermaid or convert_tables):
                tasks.append(process_image_limited(img_name, img_path))
            elif os.path.exists(img_path):
                # 只是修正路徑
                img_rel_path = os.path.relpath(img_path, output_dir)
                full_text = full_text.replace(f"![]({img_name})", f"![]({img_rel_path})")
                
        if tasks:
            logger.info(
                f"正在並發處理 {len(tasks)} 張圖片 "
                f"(上限 {settings.VISION_MAX_CONCURRENCY})..."
            )
            results = await asyncio.gather(*tasks)
            for old_tag, new_tag in results:
                full_text = full_text.replace(old_tag, new_tag)

        # 執行後處理 (清理雜質、正規化 LaTeX)
        processed_text = self.processor.normalize_latex(full_text)
        processed_text = self.processor.remove_artifacts(processed_text)
        
        final_filename = raw_md_path.name.replace("_raw.md", ".md")
        final_path = os.path.join(output_dir, final_filename)
        
        with open(final_path, "w", encoding="utf-8") as f:
            f.write(processed_text)
            
        logger.info(f"完成非同步增強轉換: {final_path}")
        return final_path

    async def enhance_image_async(
        self,
        image_path: Path,
        output_dir: str,
        convert_mermaid: bool = True,
        convert_tables: bool = True,
    ) -> str:
        os.makedirs(output_dir, exist_ok=True)
        old_tag, replacement = await self.process_image(
            image_path.name,
            str(image_path),
            output_dir,
            convert_mermaid=convert_mermaid,
            convert_tables=convert_tables,
        )
        final_path = os.path.join(output_dir, f"{image_path.stem}.md")
        
        if replacement == old_tag:
            img_rel_path = os.path.relpath(image_path, output_dir)
            replacement = f"![]({img_rel_path})"
        
        processed_text = self.processor.normalize_latex(replacement.strip())
        processed_text = self.processor.remove_artifacts(processed_text)
        
        with open(final_path, "w", encoding="utf-8") as f:
            f.write(processed_text + "\n")
        
        logger.info(f"完成圖片增強轉換: {final_path}")
        return final_path

    def enhance(
        self,
        raw_md_path: Path,
        output_dir: str,
        convert_mermaid: bool = True,
        convert_tables: bool = True,
    ) -> str:
        return asyncio.run(
            self.enhance_async(
                raw_md_path,
                output_dir,
                convert_mermaid=convert_mermaid,
                convert_tables=convert_tables,
            )
        )

    def enhance_image(
        self,
        image_path: Path,
        output_dir: str,
        convert_mermaid: bool = True,
        convert_tables: bool = True,
    ) -> str:
        return asyncio.run(
            self.enhance_image_async(
                image_path,
                output_dir,
                convert_mermaid=convert_mermaid,
                convert_tables=convert_tables,
            )
        )

enhancer = MarkdownEnhancer()
