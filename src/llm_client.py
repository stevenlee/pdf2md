import os
import re
import typer
import base64
import aiohttp
import asyncio
from pathlib import Path
from openai import OpenAI
import google.generativeai as genai
from src.config import settings

class LLMClient:
    def __init__(self):
        # 初始化 vLLM 連線
        self.vllm_client = OpenAI(
            base_url=settings.VLLM_API_BASE,
            api_key=settings.VLLM_API_KEY,
        )
        
        # 初始化 Ollama 連線
        self.ollama_client = OpenAI(
            base_url=settings.OLLAMA_API_BASE,
            api_key="ollama",
        )
        
        # 初始化 Gemini (如果有的話)
        if settings.GEMINI_API_KEY:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self.gemini_client = genai.GenerativeModel(settings.GEMINI_MODEL)
        else:
            self.gemini_client = None

    def _load_prompt(self, prompt_name: str) -> str:
        prompt_path = Path(__file__).parent.parent / "prompts" / f"{prompt_name}.md"
        if not prompt_path.exists():
            return "You are a helpful assistant."
        return prompt_path.read_text(encoding="utf-8")

    def chat(self, prompt: str, system_prompt: str = None):
        if system_prompt is None:
            system_prompt = "You are a helpful assistant."
            
        provider = settings.TEXT_PROVIDER
        
        if provider == "vllm":
            response = self.vllm_client.chat.completions.create(
                model=settings.VLLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ]
            )
            return response.choices[0].message.content
        elif provider == "ollama":
            response = self.ollama_client.chat.completions.create(
                model=settings.OLLAMA_MODEL_TEXT,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ]
            )
            return response.choices[0].message.content
        elif provider == "gemini" and self.gemini_client:
            response = self.gemini_client.generate_content(f"{system_prompt}\n\n{prompt}")
            return response.text
        return "Error: No text provider configured."

    def vision_to_mermaid(self, image_path: str):
        system_prompt = self._load_prompt("vision_to_mermaid")
        provider = settings.VISION_PROVIDER
        
        if provider == "ollama":
            import base64
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            
            response = self.ollama_client.chat.completions.create(
                model=settings.OLLAMA_MODEL_VISION,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": system_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                },
                            },
                        ],
                    }
                ],
            )
            return response.choices[0].message.content
        elif provider == "gemini" and self.gemini_client:
            from PIL import Image
            img = Image.open(image_path)
            response = self.gemini_client.generate_content([system_prompt, img])
            return response.text
        return "Error: No vision provider configured."

    @staticmethod
    def _read_image_b64(image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    async def _async_vision_call(
        self, image_path: str, prompt: str, model: str = None, session=None
    ) -> str:
        """通用非同步 vision API 呼叫。

        session 可由呼叫端傳入以重用連線；未提供時自建臨時 session。
        檔案讀取與 base64 編碼移到執行緒，避免阻塞 event loop。
        """
        provider = settings.VISION_PROVIDER

        if provider == "ollama":
            if model is None:
                model = settings.OLLAMA_MODEL_VISION

            base64_image = await asyncio.to_thread(self._read_image_b64, image_path)

            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                }
                            }
                        ]
                    }
                ]
            }

            endpoint = f"{settings.OLLAMA_API_BASE.rstrip('/')}/chat/completions"

            attempts = max(1, settings.VISION_REQUEST_RETRIES + 1)
            last_error = None

            owns_session = session is None
            if owns_session:
                timeout = aiohttp.ClientTimeout(total=settings.VISION_REQUEST_TIMEOUT)
                session = aiohttp.ClientSession(timeout=timeout)
            try:
                for attempt in range(attempts):
                    try:
                        async with session.post(endpoint, json=payload) as response:
                            if response.status == 200:
                                data = await response.json()
                                return data["choices"][0]["message"]["content"]

                            text = await response.text()
                            error = Exception(f"Ollama API 錯誤: HTTP {response.status} - {text}")
                            if response.status not in (408, 429, 500, 502, 503, 504):
                                raise error
                            last_error = error
                    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                        last_error = e

                    if attempt < attempts - 1:
                        await asyncio.sleep(2 ** attempt)
            finally:
                if owns_session:
                    await session.close()

            # 帶上例外類型，避免 TimeoutError 等 str() 為空時 log 看不出原因
            detail = f"{type(last_error).__name__}: {last_error}" if last_error else "未知錯誤"
            raise Exception(f"Ollama API 重試後仍失敗: {detail}")
        return "Error: Async vision not supported for this provider yet."

    @staticmethod
    def make_session() -> "aiohttp.ClientSession":
        """建立一個帶逾時設定的 ClientSession，供單一檔案的多張圖片重用連線。"""
        timeout = aiohttp.ClientTimeout(total=settings.VISION_REQUEST_TIMEOUT)
        return aiohttp.ClientSession(timeout=timeout)

    async def async_vision_smart_convert(self, image_path: str, session=None) -> str:
        """單次呼叫：同時分類並轉換圖片。

        回應第一行為 `TYPE: <TABLE|DOCUMENT|DIAGRAM|OTHER>`，其後為對應格式的內容。
        以一次 vision round-trip 取代原本的「分類 + 轉換」兩次呼叫。
        """
        prompt = self._load_prompt("vision_smart_convert")
        return await self._async_vision_call(
            image_path, prompt, model=settings.OLLAMA_MODEL_SMART, session=session
        )

    async def async_vision_to_document(self, image_path: str, session=None) -> str:
        """文件/表單 OCR：用於 DIAGRAM 轉 Mermaid 失敗時的降級提取。"""
        prompt = self._load_prompt("vision_to_document")
        return await self._async_vision_call(
            image_path, prompt, model=settings.OLLAMA_MODEL_OCR, session=session
        )

    def ocr_extract(self, image_path: str):
        """專門用於純文字提取的 OCR 任務"""
        system_prompt = "You are a professional OCR assistant. Extract all text from the image exactly as it appears. Output ONLY the extracted text."
        provider = settings.OCR_PROVIDER
        
        if provider == "ollama":
            import base64
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            
            response = self.ollama_client.chat.completions.create(
                model=settings.OLLAMA_MODEL_OCR,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": system_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                },
                            },
                        ],
                    }
                ],
            )
            return response.choices[0].message.content
        return self.vision_to_mermaid(image_path)

llm_client = LLMClient()
