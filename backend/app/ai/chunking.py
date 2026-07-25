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


def count_tokens(text: str) -> int:
    """Kaba token sayimi (cl100k_base). RAG token tavani ve chunk boyutu icin ortak olcu."""
    return len(_enc.encode(text))


def _ntok(text: str) -> int:
    return count_tokens(text)


def tail_by_tokens(text: str, limit: int) -> str:
    """Metnin SON `limit` token'i. Sorgu zenginlestirmede kullanilir: kisa bir hamlenin
    ("iceri giriyorum") vektoru hicbir seye benzemez; son bolumun kuyrugu mevcut sahne
    baglamini tasir."""
    tokens = _enc.encode(text or "")
    if len(tokens) <= limit:
        return (text or "").strip()
    return _enc.decode(tokens[-limit:]).strip()


def truncate_by_tokens(text: str, limit: int) -> str:
    """Metni ILK `limit` token'a kirpar (RAG token tavani icin son care)."""
    tokens = _enc.encode(text or "")
    if len(tokens) <= limit:
        return text or ""
    return _enc.decode(tokens[:limit]).rstrip() + "..."


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


def _atomic_units(text: str) -> list[tuple[str, str]]:
    """Birlestirilebilir en kucuk parcalar: once paragraf; MAX'i asiyorsa cumle; o da asiyorsa
    token penceresi. Boylece hicbir unit tek basina CHUNK_MAX_TOKENS'i asmaz.

    Her unit (metin, ONCESINDEKI ayirac) doner: paragraf sinirinda "\\n\\n", ayni paragraf
    icinde bolunmus cumleler arasinda " ". Boylece chunk metni ORIJINALIN bicimini korur —
    paragrafsiz bir bolumu cumle cumle "\\n\\n" ile yeniden yazmaz."""
    units: list[tuple[str, str]] = []
    for para in re.split(r"\n\s*\n", text.strip()):
        para = para.strip()
        if not para:
            continue
        if _ntok(para) <= CHUNK_MAX_TOKENS:
            units.append((para, "\n\n"))
            continue
        # Paragraf cok buyuk: cumlelere bol. ILK parca paragraf sinirinda, sonrakiler
        # ayni paragrafin icinde -> aralarinda bosluk kullanilir.
        first = True
        for sent in _split_sentences(para):
            pieces = [sent] if _ntok(sent) <= CHUNK_MAX_TOKENS else _hard_split_by_tokens(sent, CHUNK_MAX_TOKENS)
            for piece in pieces:
                units.append((piece, "\n\n" if first else " "))
                first = False
    return units


def _join_units(units: list[tuple[str, str]]) -> str:
    """Unit'leri kendi ayiraclariyla birlestirir (ilk unit'in ayiraci yok sayilir)."""
    out = units[0][0]
    for text, sep in units[1:]:
        out += sep + text
    return out


def split_into_chunks(text: str) -> list[str]:
    """Bolum metnini ~400-600 token'lik, paragraf/cumle sinirina saygili parcalara boler.
    LLM YOK; deterministik (ayni metin -> ayni parcalar). Bos metin -> []."""
    text = (text or "").strip()
    if not text:
        return []

    units = _atomic_units(text)
    if not units:
        return []
    chunks: list[str] = []
    cur_units: list[tuple[str, str]] = []
    cur_tokens = 0

    for unit in units:
        ut = _ntok(unit[0])
        # Mevcut parca doluysa ve bu unit onu MAX'in ustune tasiyacaksa once flush et
        if cur_units and cur_tokens + ut > CHUNK_MAX_TOKENS:
            chunks.append(_join_units(cur_units))
            cur_units, cur_tokens = [], 0
        cur_units.append(unit)
        cur_tokens += ut
        # Hedefe ulastiysa kapat (parcalar ~TARGET civari kalsin)
        if cur_tokens >= CHUNK_TARGET_TOKENS:
            chunks.append(_join_units(cur_units))
            cur_units, cur_tokens = [], 0

    if cur_units:
        tail = _join_units(cur_units)
        # Cok kucuk son parca tek basina zayif vektor uretir -> oncekiyle birlestir
        if chunks and cur_tokens < CHUNK_MIN_TOKENS:
            chunks[-1] = chunks[-1] + cur_units[0][1] + tail
        else:
            chunks.append(tail)

    return chunks
