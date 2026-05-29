import os
import logging
import json
import shutil
import time
from pathlib import Path
from typing import Optional
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PDFConverter:
    def __init__(self):
        logger.info("正在載入 Marker 模型 (這可能需要一些時間)...")
        self._quarantine_incomplete_surya_models()
        self.model_dict = create_model_dict()
        self.converter = PdfConverter(artifact_dict=self.model_dict)

    def _quarantine_incomplete_surya_models(self):
        """Move partial Surya downloads aside before the downloader retries.

        Surya checks manifest completeness before loading a model, but its
        retry downloader cannot overwrite files that already exist. A partial
        cache can therefore fail forever with "Destination path already exists".
        """
        try:
            from surya.settings import settings as surya_settings
        except Exception as e:
            logger.warning(f"無法讀取 Surya cache 設定，略過 cache 檢查: {e}")
            return

        model_root = Path(surya_settings.MODEL_CACHE_DIR)
        if not model_root.exists():
            return

        for model_dir in model_root.glob("*/*"):
            if not model_dir.is_dir():
                continue

            manifest_path = model_dir / "manifest.json"
            has_files = any(model_dir.iterdir())
            if not manifest_path.exists():
                if has_files:
                    self._quarantine_model_dir(model_dir, "missing_manifest")
                continue

            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                missing = [
                    name for name in manifest.get("files", [])
                    if not (model_dir / name).exists()
                ]
            except Exception:
                self._quarantine_model_dir(model_dir, "bad_manifest")
                continue

            if missing:
                logger.warning(
                    f"偵測到未完整下載的 Surya model cache: {model_dir} "
                    f"(缺 {len(missing)} 個檔案)，將移到 quarantine 後重新下載。"
                )
                self._quarantine_model_dir(model_dir, "incomplete")

    def _quarantine_model_dir(self, model_dir: Path, reason: str):
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        quarantine = (
            model_dir.parent
            / f"{model_dir.name}_{reason}_{timestamp}"
        )
        suffix = 1
        while quarantine.exists():
            quarantine = (
                model_dir.parent
                / f"{model_dir.name}_{reason}_{timestamp}_{suffix}"
            )
            suffix += 1
        shutil.move(str(model_dir), str(quarantine))
        logger.warning(f"已移動問題 model cache: {model_dir} -> {quarantine}")

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
