import os
import re
import typer
import base64
import aiohttp
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

    async def async_vision_to_mermaid(self, image_path: str) -> str:
        system_prompt = self._load_prompt("vision_to_mermaid")
        provider = settings.VISION_PROVIDER
        
        if provider == "ollama":
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            
            payload = {
                "model": settings.OLLAMA_MODEL_VISION,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": system_prompt},
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
            
            # OpenAI compatible endpoint on Ollama
            endpoint = f"{settings.OLLAMA_API_BASE.rstrip('/')}/chat/completions"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(endpoint, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data["choices"][0]["message"]["content"]
                    else:
                        text = await response.text()
                        raise Exception(f"Ollama API 錯誤: HTTP {response.status} - {text}")
        return "Error: Async vision not supported for this provider yet."

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
