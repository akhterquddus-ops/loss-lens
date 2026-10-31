"""
LLM connector. Pick a provider by putting ONE key in the .env file:

  ANTHROPIC_API_KEY=...    (Claude)
  OPENAI_API_KEY=...       (OpenAI)
  GEMINI_API_KEY=...       (Google Gemini)
  OLLAMA_MODEL=qwen2.5-coder:7b   (local model via Ollama, no key)

Optional: LLM_MODEL=<model name> to override the default model.
With no key, the app runs in offline mode (matched worked examples).
"""
import json
import os
import re

import requests

TIMEOUT = 60


def provider() -> str | None:
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    if os.getenv("OLLAMA_MODEL"):
        return "ollama"
    return None


DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5-5",
    "openai": "gpt-4.1-mini",
    "gemini": "gemini-2.5-flash",
}


def model_name() -> str:
    p = provider()
    if p == "ollama":
        return os.getenv("OLLAMA_MODEL")
    return os.getenv("LLM_MODEL") or DEFAULT_MODELS.get(p, "")


def chat(system: str, user: str, max_tokens: int = 1200) -> str:
    """Send one system + user message, return the text reply."""
    p = provider()
    m = model_name()
    if p == "anthropic":
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                     "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": m, "max_tokens": max_tokens, "system": system,
                  "messages": [{"role": "user", "content": user}]},
            timeout=TIMEOUT)
        _raise(r)
        return "".join(b.get("text", "") for b in r.json()["content"])
    if p == "openai":
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={"model": m, "messages": [{"role": "system", "content": system},
                                          {"role": "user", "content": user}]},
            timeout=TIMEOUT)
        _raise(r)
        return r.json()["choices"][0]["message"]["content"]
    if p == "gemini":
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
            headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            json={"systemInstruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "user", "parts": [{"text": user}]}]},
            timeout=TIMEOUT)
        _raise(r)
        return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
    if p == "ollama":
        r = requests.post(
            os.getenv("OLLAMA_URL", "http://localhost:11434") + "/api/chat",
            json={"model": m, "stream": False,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=180)
        _raise(r)
        return r.json()["message"]["content"]
    raise RuntimeError("No AI provider configured.")


def _raise(r: requests.Response) -> None:
    if r.status_code >= 400:
        try:
            detail = json.dumps(r.json())[:400]
        except Exception:
            detail = r.text[:400]
        raise RuntimeError(f"AI provider error {r.status_code}: {detail}")


def extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    return (m.group(1) if m else text).strip()
