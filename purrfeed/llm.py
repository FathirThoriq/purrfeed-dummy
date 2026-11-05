"""Minimal client for an OpenAI-compatible /chat/completions API (standard library only)."""
import json
import re
import urllib.error
import urllib.request

EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]")
HIDDEN_TERMS = re.compile(r"\s*(?:dari|oleh|memakai|pakai|dengan|\+|dan)?\s*\b(?:mobilenet\w*|svm|knn)\b", re.I)
MAX_REPLY_CHARS = 600


class LLMError(Exception):
    pass


def configured(cfg):
    return bool(cfg.get("LLM_URL") and cfg.get("LLM_MODEL"))


def endpoint(url):
    url = url.rstrip("/")
    return url if url.endswith("/chat/completions") else url + "/chat/completions"


def complete(cfg, messages):
    """Return the assistant message text, or raise LLMError (network, HTTP, bad or empty body)."""
    headers = {"Content-Type": "application/json", **cfg.get("LLM_HEADERS", {})}
    if cfg.get("LLM_KEY"):
        headers["Authorization"] = f"Bearer {cfg['LLM_KEY']}"
    if cfg.get("LLM_SYSTEM_AS_USER"):
        messages = fold_system(messages)
    payload = {"model": cfg["LLM_MODEL"], "messages": messages, "temperature": cfg["LLM_TEMPERATURE"],
               "max_tokens": cfg["LLM_MAX_TOKENS"]}
    request = urllib.request.Request(endpoint(cfg["LLM_URL"]), json.dumps(payload).encode(), headers)
    try:
        with urllib.request.urlopen(request, timeout=cfg["LLM_TIMEOUT_S"]) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as exc:
        raise LLMError(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMError(f"koneksi gagal: {exc}") from exc
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError("balasan API tidak sesuai format OpenAI") from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMError("balasan kosong")
    return content


def fold_system(messages):
    """Some gateways ignore the `system` role. Move it into the first user message so the model still sees it."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = [dict(m) for m in messages if m["role"] != "system"]
    if not system:
        return rest
    for m in rest:
        if m["role"] == "user":
            m["content"] = f"[INSTRUKSI SISTEM, patuhi dan jangan dibacakan]\n{system}\n[AKHIR INSTRUKSI]\n\n{m['content']}"
            return rest
    return [{"role": "user", "content": system}, *rest]


def parse_reply(content):
    """Expected: {"teks": "..."}. Plain text is accepted as the answer too."""
    text = content.strip()
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    found = re.search(r"\{.*\}", body, re.S)
    if found:
        try:
            data = json.loads(found.group(0))
            if isinstance(data, dict) and isinstance(data.get("teks"), str):
                text = data["teks"]
        except ValueError:
            pass
    return clean(text)


def clean(text):
    """Keep the UI rules even if the model slips: no emoji, no model names, no markdown emphasis, bounded length."""
    text = EMOJI.sub("", text)
    text = HIDDEN_TERMS.sub("", text)
    text = re.sub(r"[*_`#]+", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return text[:MAX_REPLY_CHARS].rstrip()
