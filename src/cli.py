import typer
from pathlib import Path
from typing import Optional
from src.converter import PDFConverter
from rich.console import Console
from concurrent.futures import ThreadPoolExecutor
import os
import time
import threading

console = Console()

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}

def batch_convert(
    input_dir: Path = typer.Option(..., "--input", "-i", help="包含 PDF 檔案的輸入目錄"),
    output_dir: Path = typer.Option(..., "--output", "-o", help="儲存 Markdown 檔案的輸出目錄"),
    mermaid: bool = typer.Option(True, "--mermaid/--no-mermaid", help="是否嘗試將圖表轉換為 Mermaid"),
    tables: bool = typer.Option(True, "--tables/--no-tables", help="是否嘗試將表格圖片轉換為 Markdown table"),
    workers: int = typer.Option(4, "--workers", "-w", help="並行處理的執行緒數量"),
    force: bool = typer.Option(False, "--force", "-f", help="強制重新轉換已存在的檔案"),
    keep_raw: bool = typer.Option(False, "--keep-raw/--no-keep-raw", help="是否保留第一階段產生的 *_raw.md 參考檔"),
):
    """
    批次將目錄中的 PDF 與圖片轉換為 Markdown。
    """
    if not input_dir.is_dir():
        console.print(f"[red]錯誤: {input_dir} 不是一個目錄[/red]")
        raise typer.Exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 搜尋所有 PDF 與可直接做 vision/OCR 的圖片
    pdf_files = list(input_dir.glob("**/*.pdf"))
    image_files = [
        path for path in input_dir.glob("**/*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    input_files = pdf_files + image_files
    
    if not input_files:
        console.print(f"[yellow]找不到任何 PDF 或圖片檔案於 {input_dir}[/yellow]")
        return

    console.print(
        f"[green]找到 {len(pdf_files)} 個 PDF、{len(image_files)} 個圖片檔案，準備開始轉換...[/green]"
    )

    converter: Optional[PDFConverter] = None
    converter_lock = threading.Lock()

    def process_file(input_path: Path):
        # 決定輸出子路徑以維持目錄結構
        rel_path = input_path.relative_to(input_dir)
        target_subdir = output_dir / rel_path.parent
        target_file = target_subdir / f"{input_path.stem}.md"

        if target_file.exists() and not force:
            return f"跳過: {rel_path} (已存在)"

        try:
            start_total = time.time()
            
            from src.enhancer import enhancer
            start_s1 = time.time()
            start_s2 = time.time()
            
            if input_path.suffix.lower() == ".pdf":
                # Stage 1: Physical Extraction
                nonlocal converter
                if converter is None:
                    with converter_lock:
                        if converter is None:
                            converter = PDFConverter()
                assert converter is not None
                raw_md_path_str = converter.convert(str(input_path), str(target_subdir))
                raw_md_path = Path(raw_md_path_str)
                end_s1 = time.time()
                
                # Stage 2: Semantic Enhancement
                start_s2 = time.time()
                final_md_path = enhancer.enhance(
                    raw_md_path,
                    str(target_subdir),
                    convert_mermaid=mermaid,
                    convert_tables=tables,
                )
                if not keep_raw and raw_md_path.exists():
                    raw_md_path.unlink()
            else:
                end_s1 = time.time()
                final_md_path = enhancer.enhance_image(
                    input_path,
                    str(target_subdir),
                    convert_mermaid=mermaid,
                    convert_tables=tables,
                )
            end_s2 = time.time()
            
            total_time = time.time() - start_total
            s1_time = end_s1 - start_s1
            s2_time = end_s2 - start_s2
            
            return f"成功: {rel_path} | 總計: {total_time:.1f}s (S1: {s1_time:.1f}s, S2: {s2_time:.1f}s)"
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"失敗: {rel_path} ({str(e)})"

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(process_file, input_files))

    for res in results:
        if "成功" in res:
            console.print(f"[green]{res}[/green]")
        elif "跳過" in res:
            console.print(f"[blue]{res}[/blue]")
        else:
            console.print(f"[red]{res}[/red]")

    if any(res.startswith("失敗:") for res in results):
        raise typer.Exit(1)

if __name__ == "__main__":
    typer.run(batch_convert)
