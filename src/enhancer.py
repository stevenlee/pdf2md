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

    # Mermaid 節點外框：開括號 -> 對應閉括號（長者優先，確保 `[[` 早於 `[`）
    _MERMAID_SHAPES = [
        ("[[", "]]"), ("((", "))"), ("{{", "}}"),
        ("([", "])"), ("[(", ")]"),
        ("[/", "/]"), ("[\\", "\\]"),
        ("[", "]"), ("(", ")"), ("{", "}"), (">", "]"),
    ]

    # 邊標籤結束的終止字元：link 運算子開頭 (- = <)、管線、或行尾
    _EDGE_TERMINATORS = "-=<|"

    def fix_mermaid_syntax(self, code: str) -> str:
        """為 Mermaid 標籤補上雙引號並修正巢狀引號。

        單次掃描狀態機，認得三種標籤：
        - 節點外框 `ID[...]`/`ID{...}`/`ID(...)` 等
        - 管線邊標籤 `-->|...|`
        - link 邊標籤 `-- "..." -->`

        關鍵設計：一旦進入引號字串就不再觸發節點偵測，避免標籤內的
        `_{...}` (如 LaTeX 下標 FS_{t+1}) 被誤判為菱形節點；邊標籤的閉引號
        以「後接 link 運算子/管線/行尾」判定，因此 `{}` 會被當文字而非結束。
        巢狀雙引號一律轉為單引號。
        """
        return "\n".join(self._fix_mermaid_line(line) for line in code.splitlines())

    def _fix_mermaid_line(self, line: str) -> str:
        out = []
        i = 0
        n = len(line)
        while i < n:
            ch = line[i]

            # (1) 節點外框
            shape = self._match_shape_open(line, i)
            if shape is not None:
                ob, cb = shape
                consumed = self._consume_node_label(line, i + len(ob), cb)
                if consumed is not None:
                    label, end = consumed
                    out.append(f'{ob}"{label}"{cb}')
                    i = end
                    continue

            # (2) 管線邊標籤 |...|
            if ch == '|':
                consumed = self._consume_pipe_label(line, i + 1)
                if consumed is not None:
                    label, end = consumed
                    out.append(f'|"{label}"|')
                    i = end
                    continue

            # (3) link 邊標籤：前接 link 運算子的引號字串
            if ch == '"' and self._prev_nonspace_is_link(line, i):
                consumed = self._consume_edge_label(line, i)
                if consumed is not None:
                    label, end = consumed
                    out.append(f'"{label}"')
                    i = end
                    continue

            out.append(ch)
            i += 1
        return "".join(out)

    def _match_shape_open(self, line: str, i: int):
        """若 line[i] 是節點外框的開頭（且前一字元為節點 ID），回傳 (開, 閉)。"""
        if line[i] not in "[({>":
            return None
        prev = line[i - 1] if i > 0 else ""
        if not (prev.isalnum() or prev == "_"):
            return None
        for ob, cb in self._MERMAID_SHAPES:
            if line.startswith(ob, i):
                return ob, cb
        return None

    def _prev_nonspace_is_link(self, line: str, i: int) -> bool:
        """往回略過空白，判斷前一個非空白字元是否為 link 運算子結尾。"""
        j = i - 1
        while j >= 0 and line[j] == ' ':
            j -= 1
        return j >= 0 and line[j] in "-=.>"

    def _consume_node_label(self, line: str, start: int, cb: str):
        """取出節點標籤，回傳 (正規化標籤, 含閉括號後的結束索引)。"""
        n = len(line)
        if line[start:].lstrip().startswith('"'):
            j = start
            while j < n and line[j] == ' ':
                j += 1
            k = j + 1  # 略過開引號
            buf = []
            while k < n:
                if line[k] == '"':
                    m = k + 1
                    while m < n and line[m] == ' ':
                        m += 1
                    if line.startswith(cb, m):  # 後接閉括號 -> 真正的閉引號
                        return "".join(buf), m + len(cb)
                    buf.append("'")  # 巢狀引號
                    k += 1
                else:
                    buf.append(line[k])
                    k += 1
            return None  # 引號未閉合
        idx = line.find(cb, start)
        if idx == -1:
            return None
        return line[start:idx].strip().replace('"', "'"), idx + len(cb)

    def _consume_pipe_label(self, line: str, start: int):
        """取出 |...| 邊標籤，回傳 (正規化標籤, 含閉管線後的結束索引)。"""
        idx = line.find('|', start)
        if idx == -1:
            return None
        content = line[start:idx].strip()
        if len(content) >= 2 and content.startswith('"') and content.endswith('"'):
            content = content[1:-1]
        return content.replace('"', "'"), idx + 1

    def _consume_edge_label(self, line: str, qpos: int):
        """取出 link 邊標籤的引號字串，回傳 (正規化標籤, 閉引號後的結束索引)。

        閉引號判定：其後（略過空白）為 link 運算子/管線/行尾，因此標籤文字內
        的 `}`/`]` 等不會被誤判為結束。
        """
        n = len(line)
        k = qpos + 1
        buf = []
        while k < n:
            if line[k] == '"':
                m = k + 1
                while m < n and line[m] == ' ':
                    m += 1
                if m >= n or line[m] in self._EDGE_TERMINATORS:
                    return "".join(buf), k + 1
                buf.append("'")  # 巢狀引號
                k += 1
            else:
                buf.append(line[k])
                k += 1
        return None

    def validate_mermaid(self, code: str) -> str:
        """驗證並修復常見的 Mermaid 語法問題（不再盲目補括號，避免破壞已配對標籤）。"""
        lines = code.strip().splitlines()
        fixed_lines = [line.rstrip().rstrip(';') if line.strip() else line for line in lines]
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

    def _parse_smart_output(self, raw: str) -> tuple[str, str]:
        """解析合併呼叫的輸出，回傳 (TYPE, 內容)。"""
        text = re.sub(r'```[a-zA-Z]*\n?|```', '', raw).strip()
        lines = text.splitlines()
        if not lines:
            return "OTHER", ""
        m = re.match(r'\s*TYPE:\s*(TABLE|DOCUMENT|DIAGRAM|OTHER)\s*$', lines[0], re.IGNORECASE)
        if m:
            return m.group(1).upper(), "\n".join(lines[1:]).strip()
        # 模型未遵守格式時，從整段內容偵測型別
        upper = text.upper()
        for category in ("DIAGRAM", "TABLE", "DOCUMENT"):
            if upper.startswith(f"TYPE: {category}") or upper.startswith(category):
                body = re.sub(r'^\s*(TYPE:\s*)?' + category + r'\s*', '', text, count=1, flags=re.IGNORECASE)
                return category, body.strip()
        return "DOCUMENT", text

    def _format_diagram(self, content: str) -> str | None:
        clean = re.sub(r'(```mermaid|```)', '', content).strip()
        if not self.is_valid_mermaid(clean):
            return None
        fixed = self.validate_mermaid(self.fix_mermaid_syntax(clean))
        return f"\n\n```mermaid\n{fixed}\n```\n\n"

    def _format_table(self, content: str) -> tuple[str, str] | None:
        clean = self.clean_markdown_table(content)
        if self.is_markdown_table(clean):
            return f"\n\n{clean}\n\n", "原始表格圖片比對"
        return None

    def _format_document(self, content: str) -> tuple[str, str] | None:
        clean = self.clean_document_output(content)
        if self.is_valid_document_output(clean):
            return f"\n\n{clean}\n\n", "原始文件圖片比對"
        return None

    async def process_image(
        self,
        img_name: str,
        img_path: str,
        output_dir: str,
        convert_mermaid: bool = True,
        convert_tables: bool = True,
        max_retries: int = 2,
        session=None,
    ) -> tuple[str, str]:
        """非同步處理單張圖片，返回 (舊標籤, 替換文字)。

        單次呼叫同時完成分類與轉換（合併原本的 classify + convert 兩段呼叫）；
        DIAGRAM 若驗證失敗會重試。session 可重用以共享連線。
        """
        logger.info(f"開始非同步轉換圖片: {img_name}")
        from src.llm_client import llm_client
        img_rel_path = os.path.relpath(img_path, output_dir)
        keep_original = (f"![]({img_name})", f"![]({img_rel_path})")
        diagram_failed = False

        for attempt in range(max(1, max_retries)):
            try:
                raw = await llm_client.async_vision_smart_convert(img_path, session=session)
            except Exception as e:
                logger.warning(f"轉換 {img_name} 第 {attempt+1} 次失敗: {e}")
                continue

            img_type, content = self._parse_smart_output(raw)
            logger.info(f"圖片 {img_name} 分類結果: {img_type}")

            if img_type == "DIAGRAM" and convert_mermaid:
                block = self._format_diagram(content)
                if block:
                    replacement = f"{block}> [!NOTE]\n> 原始圖片比對: ![]({img_rel_path})\n"
                    return f"![]({img_name})", replacement
                diagram_failed = True
                logger.warning(f"Mermaid 無效 ({img_name})，第 {attempt+1} 次，重試中...")
                continue  # 圖表才重試（模型輸出不穩定）

            if convert_tables and img_type in ("TABLE", "DOCUMENT", "OTHER"):
                formatter = self._format_table if img_type == "TABLE" else self._format_document
                result = formatter(content)
                if result:
                    body, note = result
                    replacement = f"{body}> [!NOTE]\n> {note}: ![]({img_rel_path})\n"
                    return f"![]({img_name})", replacement

            break  # 非圖表類型不重試

        # 降級：圖表轉 Mermaid 失敗（常見於節點內含複雜子圖），改用 OCR 至少抽出文字標籤
        if diagram_failed and convert_tables:
            result = await self._fallback_document_ocr(llm_client, img_name, img_path, session)
            if result:
                body, _ = result
                logger.info(f"{img_name} Mermaid 失敗，已降級為 OCR 文字 + 原圖")
                replacement = (
                    f"{body}> [!NOTE]\n> 原始圖表 (Mermaid 轉換失敗，僅供比對): "
                    f"![]({img_rel_path})\n"
                )
                return f"![]({img_name})", replacement

        logger.info(f"{img_name} 無法轉換為結構化格式，保留原始圖片")
        return keep_original

    async def _fallback_document_ocr(
        self, llm_client, img_name: str, img_path: str, session=None
    ) -> tuple[str, str] | None:
        try:
            doc_text = await llm_client.async_vision_to_document(img_path, session=session)
            return self._format_document(doc_text)
        except Exception as e:
            logger.warning(f"降級 OCR {img_name} 失敗: {e}")
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
        
        from src.llm_client import llm_client

        tasks_meta = []  # (img_name, img_path)
        semaphore = asyncio.Semaphore(max(1, settings.VISION_MAX_CONCURRENCY))

        async def process_image_limited(img_name: str, img_path: str, session):
            async with semaphore:
                return await self.process_image(
                    img_name,
                    img_path,
                    output_dir,
                    convert_mermaid=convert_mermaid,
                    convert_tables=convert_tables,
                    session=session,
                )

        for img_name in img_tags:
            img_path = os.path.join(img_subdir, img_name)
            if os.path.exists(img_path) and (convert_mermaid or convert_tables):
                tasks_meta.append((img_name, img_path))
            elif os.path.exists(img_path):
                # 只是修正路徑
                img_rel_path = os.path.relpath(img_path, output_dir)
                full_text = full_text.replace(f"![]({img_name})", f"![]({img_rel_path})")

        if tasks_meta:
            logger.info(
                f"正在並發處理 {len(tasks_meta)} 張圖片 "
                f"(上限 {settings.VISION_MAX_CONCURRENCY})..."
            )
            # 單一檔案的所有圖片共用一個 session，重用連線
            async with llm_client.make_session() as session:
                results = await asyncio.gather(
                    *(process_image_limited(n, p, session) for n, p in tasks_meta)
                )
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
        from src.llm_client import llm_client
        async with llm_client.make_session() as session:
            old_tag, replacement = await self.process_image(
                image_path.name,
                str(image_path),
                output_dir,
                convert_mermaid=convert_mermaid,
                convert_tables=convert_tables,
                session=session,
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
