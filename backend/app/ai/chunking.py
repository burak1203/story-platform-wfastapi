"""Deterministik metin parcalama (C4 chunk katmani). LLM YOK — duz metin bolme.

Bolumu ~400-600 token'lik parcalara boler: PARAGRAF sinirlarina saygili, CUMLE ortasindan
kesmez. Her parca embed'lenip (OpenAI uzayi) saklanir; retrieval kullanicinin hamlesini
chunk'larla eslestirerek olay katmaninin (kayipli) kacirdigi yerel detayi geri getirir.

Token sayimi tiktoken/cl100k_base ile yapilir (dil-agnostik, kaba ama tutarli). Encoder modul
seviyesinde bir kez kurulur.
"""

import re

import tiktoken

# Hedef ~400-600 token: TARGET'a ulasinca parca kapanir, tek bir unit MAX'i asamaz (asan
# paragraf cumleye, asan cumle token penceresine boluner). Cok kucuk son parca oncekiyle birlesir.
CHUNK_TARGET_TOKENS = 500
CHUNK_MAX_TOKENS = 600
CHUNK_MIN_TOKENS = 120

_enc = tiktoken.get_encoding("cl100k_base")


def _ntok(text: str) -> int:
    return len(_enc.encode(text))


def _split_sentences(text: str) -> list[str]:
    """Cumle sonu noktalama + bosluktan boler (kisaltma/ondalik icin kaba ama yeterli)."""
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    return [p for p in parts if p]


def _hard_split_by_tokens(text: str, max_tokens: int) -> list[str]:
    """Son care: tek cumle bile MAX'i asiyorsa kelime sinirina yaslanmis token penceresi.
    (Cumle ortasindan degil, kelime sinirindan boler.)"""
    words = text.split()
    chunks: list[str] = []
    cur: list[str] = []
    for w in words:
        cur.append(w)
        if _ntok(" ".join(cur)) >= max_tokens:
            chunks.append(" ".join(cur))
            cur = []
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def _atomic_units(text: str) -> list[str]:
    """Birlestirilebilir en kucuk parcalar: once paragraf; MAX'i asiyorsa cumle; o da asiyorsa
    token penceresi. Boylece hicbir unit tek basina CHUNK_MAX_TOKENS'i asmaz."""
    units: list[str] = []
    for para in re.split(r"\n\s*\n", text.strip()):
        para = para.strip()
        if not para:
            continue
        if _ntok(para) <= CHUNK_MAX_TOKENS:
            units.append(para)
            continue
        for sent in _split_sentences(para):
            if _ntok(sent) <= CHUNK_MAX_TOKENS:
                units.append(sent)
            else:
                units.extend(_hard_split_by_tokens(sent, CHUNK_MAX_TOKENS))
    return units


def split_into_chunks(text: str) -> list[str]:
    """Bolum metnini ~400-600 token'lik, paragraf/cumle sinirina saygili parcalara boler.
    LLM YOK; deterministik (ayni metin -> ayni parcalar). Bos metin -> []."""
    text = (text or "").strip()
    if not text:
        return []

    units = _atomic_units(text)
    chunks: list[str] = []
    cur_units: list[str] = []
    cur_tokens = 0

    for unit in units:
        ut = _ntok(unit)
        # Mevcut parca doluysa ve bu unit onu MAX'in ustune tasiyacaksa once flush et
        if cur_units and cur_tokens + ut > CHUNK_MAX_TOKENS:
            chunks.append("\n\n".join(cur_units))
            cur_units, cur_tokens = [], 0
        cur_units.append(unit)
        cur_tokens += ut
        # Hedefe ulastiysa kapat (parcalar ~TARGET civari kalsin)
        if cur_tokens >= CHUNK_TARGET_TOKENS:
            chunks.append("\n\n".join(cur_units))
            cur_units, cur_tokens = [], 0

    if cur_units:
        tail = "\n\n".join(cur_units)
        # Cok kucuk son parca tek basina zayif vektor uretir -> oncekiyle birlestir
        if chunks and cur_tokens < CHUNK_MIN_TOKENS:
            chunks[-1] = chunks[-1] + "\n\n" + tail
        else:
            chunks.append(tail)

    return chunks
