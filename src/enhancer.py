import os
import re
import asyncio
import logging
from pathlib import Path
from src.processor import processor

logger = logging.getLogger(__name__)

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

    def fix_mermaid_syntax(self, code: str) -> str:
        """強制為 Mermaid 標籤加上雙引號，並將內部的雙引號轉為單引號 (單次替換)"""
        # 匹配上下文：行首、空格、或是 Mermaid 的箭頭
        context = r'(^|[\s\-\=>])'
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

    async def process_image(
        self,
        img_name: str,
        img_path: str,
        output_dir: str,
        convert_mermaid: bool = True,
        convert_tables: bool = True,
    ) -> tuple[str, str]:
        """非同步處理單張圖片，返回 (舊標籤, 替換文字)"""
        logger.info(f"開始非同步轉換圖片: {img_name}")
        try:
            from src.llm_client import llm_client
            
            if convert_tables:
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
                    logger.warning(f"表格 OCR {img_name} 失敗，改用其他圖片處理流程: {e}")
            
            if convert_mermaid:
                mermaid_code = await llm_client.async_vision_to_mermaid(img_path)
                
                if any(x in mermaid_code for x in ["graph ", "sequenceDiagram", "classDiagram", "stateDiagram", "erDiagram"]):
                    clean_mermaid = re.sub(r'(```mermaid|```)', '', mermaid_code).strip()
                    fixed_mermaid = self.fix_mermaid_syntax(clean_mermaid)
                    
                    img_rel_path = os.path.relpath(img_path, output_dir)
                    replacement = (
                        f"\n\n```mermaid\n{fixed_mermaid}\n```\n\n"
                        f"> [!NOTE]\n"
                        f"> 原始圖片比對: ![]({img_rel_path})\n"
                    )
                    return f"![]({img_name})", replacement
            
            logger.info(f"{img_name} 不是有效表格或圖表，保留原始圖片")
            img_rel_path = os.path.relpath(img_path, output_dir)
            return f"![]({img_name})", f"![]({img_rel_path})"
        except Exception as e:
            logger.error(f"轉換 {img_name} 失敗: {e}")
            img_rel_path = os.path.relpath(img_path, output_dir)
            return f"![]({img_name})", f"![]({img_rel_path})"

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
        for img_name in img_tags:
            img_path = os.path.join(img_subdir, img_name)
            if os.path.exists(img_path) and (convert_mermaid or convert_tables):
                tasks.append(
                    self.process_image(
                        img_name,
                        img_path,
                        output_dir,
                        convert_mermaid=convert_mermaid,
                        convert_tables=convert_tables,
                    )
                )
            elif os.path.exists(img_path):
                # 只是修正路徑
                img_rel_path = os.path.relpath(img_path, output_dir)
                full_text = full_text.replace(f"![]({img_name})", f"![]({img_rel_path})")
                
        if tasks:
            logger.info(f"正在並發處理 {len(tasks)} 張圖片...")
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
