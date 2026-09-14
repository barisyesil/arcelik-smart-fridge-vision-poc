"""Prompt Lab yerel dev sunucusu (FastAPI).

Çalıştırma (repo kökünden):
    uvicorn playground.server:app --reload --port 8900

Gemini'yi gerçekten çağırmak için ortamda GEMINI_API_KEY olmalı (bkz.
.env.example). Anahtar sunucuda kalır; tarayıcıya/istemciye ASLA gitmez.

Bu sunucu ÜRETİM API'sinden bağımsızdır: Cognito yok, DynamoDB yok, S3 yok.
Yalnızca `core` çıkarım sözleşmesini + Gemini'yi kullanır. Amaç prompt
mühendisliği: sürüm dene, tam prompt'u gör, token ve tahmini maliyeti ölç.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.taxonomy import (
    QUANTITY_UNITS,
    category_values,
    package_state_values,
    subcategory_values,
)
from playground import pricing as pricing_mod
from playground import prompts as prompts_mod
from playground.gemini import PlaygroundGeminiError, run_extraction

app = FastAPI(title="Smart Fridge — Prompt Lab", version="1.0.0")

# Yerel Vite dev sunucusu farklı porttan (5173) çağırır; dev aracı olduğu için
# origin'leri geniş bırakıyoruz. Bu sunucu asla üretime deploy edilmez.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_MAX_IMAGE_BYTES = 12 * 1024 * 1024  # Lab için makul üst sınır (12 MB).


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY ortam değişkeni ayarlı değil. Sunucuyu anahtarla başlat.",
        )
    return key


@app.get("/health")
def health() -> dict:
    return {"ok": True, "has_api_key": bool(os.environ.get("GEMINI_API_KEY", "").strip())}


@app.get("/playground/meta")
def meta() -> dict:
    """UI'ın ihtiyaç duyduğu sabitler: birimler, kategoriler, modeller, fiyatlar."""
    versions = prompts_mod.list_versions()
    return {
        "units": list(QUANTITY_UNITS),
        "categories": category_values(),
        "subcategories": subcategory_values(),
        "package_states": package_state_values(),
        "models": [
            {
                "id": model_id,
                "input_per_1m": p.input_per_1m,
                "output_per_1m": p.output_per_1m,
                "note": p.note,
            }
            for model_id, p in pricing_mod.PRICING.items()
        ],
        "default_model": "gemini-2.5-flash",
        "default_prompt_id": versions[0].id if versions else None,
        "has_api_key": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
    }


@app.get("/playground/prompts")
def get_prompts() -> dict:
    return {"versions": [v.to_dict() for v in prompts_mod.list_versions()]}


class SavePromptBody(BaseModel):
    id: str
    label: str = ""
    description: str = ""
    system_prompt: str


@app.post("/playground/prompts")
def post_prompt(body: SavePromptBody) -> dict:
    try:
        version = prompts_mod.save_version(
            body.id, body.label, body.description, body.system_prompt
        )
    except prompts_mod.PromptError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return version.to_dict()


@app.delete("/playground/prompts/{version_id}")
def delete_prompt(version_id: str) -> dict:
    if not prompts_mod.delete_version(version_id):
        raise HTTPException(
            status_code=400,
            detail="Silinemedi: sürüm bulunamadı ya da yerleşik (silinemez).",
        )
    return {"deleted": version_id}


@app.post("/playground/extract")
async def extract(
    image: UploadFile = File(...),
    prompt_id: str | None = Form(default=None),
    system_prompt: str | None = Form(default=None),
    model: str = Form(default="gemini-2.5-flash"),
    temperature: float = Form(default=0.1),
) -> dict:
    """Görseli seçilen/verilen promptla Gemini'ye gönder; her şeyi geri döndür.

    `system_prompt` verilirse o ham metin kullanılır (Lab'da anlık düzenleme).
    Verilmezse `prompt_id`'nin metni kullanılır. İkisi de yoksa üretim promptu.
    """
    # 1) Kullanılacak sistem promptunu çöz.
    used_prompt_id = prompt_id
    if system_prompt and system_prompt.strip():
        resolved_prompt = system_prompt
        used_prompt_id = prompt_id or "(anlık düzenleme)"
    else:
        versions = prompts_mod.list_versions()
        chosen = None
        if prompt_id:
            chosen = prompts_mod.get_version(prompt_id)
        elif versions:
            chosen = versions[0]
        if chosen is None:
            raise HTTPException(status_code=400, detail="Geçerli bir prompt sürümü bulunamadı.")
        resolved_prompt = chosen.system_prompt
        used_prompt_id = chosen.id

    # 2) Görseli oku ve doğrula.
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Boş görsel.")
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Görsel çok büyük (>12 MB).")
    mime_type = image.content_type or "image/jpeg"

    # 3) Sıcaklığı makul aralığa sıkıştır.
    try:
        temp = min(2.0, max(0.0, float(temperature)))
    except (TypeError, ValueError):
        temp = 0.1

    # 4) Çalıştır.
    try:
        run = run_extraction(
            api_key=_api_key(),
            image_bytes=image_bytes,
            mime_type=mime_type,
            system_prompt=resolved_prompt,
            model=model,
            temperature=temp,
        )
    except PlaygroundGeminiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cost = pricing_mod.estimate_cost(
        run.model, run.usage["prompt_tokens"], run.usage["output_tokens"]
    )

    return {
        "prompt_id": used_prompt_id,
        "model": run.model,
        "temperature": run.temperature,
        "latency_ms": run.latency_ms,
        "product_count": len(run.products),
        "products": run.products,
        "usage": run.usage,
        "cost": cost,
        "system_prompt": run.system_prompt,
        "response_schema": run.response_schema,
        "raw_response": run.raw_response,
    }
