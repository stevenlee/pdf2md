import os
import logging
from typing import Optional
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PDFConverter:
    def __init__(self):
        logger.info("正在載入 Marker 模型 (這可能需要一些時間)...")
        self.model_dict = create_model_dict()
        self.converter = PdfConverter(artifact_dict=self.model_dict)

    def convert(self, pdf_path: str, output_dir: str) -> str:
        # 1. 執行基礎轉換
        logger.info(f"開始物理萃取 (Stage 1): {pdf_path}")
        rendered = self.converter(pdf_path)
        full_text, _, images = text_from_rendered(rendered)
        
        # 建立圖片目錄
        img_subdir = os.path.join(output_dir, "images", os.path.basename(pdf_path).replace(".pdf", ""))
        os.makedirs(img_subdir, exist_ok=True)

        # 2. 單純儲存圖片
        for img_name, img_data in images.items():
            img_save_path = os.path.join(img_subdir, img_name)
            img_data.save(img_save_path)

        # 3. 寫入 _raw.md (不在此階段呼叫 LLM)
        output_filename = os.path.basename(pdf_path).replace(".pdf", "_raw.md")
        output_path = os.path.join(output_dir, output_filename)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_text)
            
        logger.info(f"完成物理萃取: {output_path}")
        return output_path
