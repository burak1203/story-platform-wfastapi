import json
import re

from json_repair import repair_json


def _extract_brace_block(raw_text: str) -> str | None:
    """Ilk dengeli {...} blogunu dondurur. String icindeki suslu parantezleri
    saymamak icin tirnak/escape takibi yapar."""
    start_idx = raw_text.find("{")
    if start_idx == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for i in range(start_idx, len(raw_text)):
        ch = raw_text[i]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw_text[start_idx : i + 1]
    # Kapanmamis blok (muhtemelen max_tokens kesmesi): kalan kismi yine de dondur,
    # asagida json_repair toparlamayi dener.
    return raw_text[start_idx:]


def coverage_ratio(parsed: dict, raw_text: str) -> float:
    """Ayiklanan JSON, modelin URETTIGI metnin ne kadarini kapsiyor? 1.0'a yakin = her sey
    alindi; dusuk = ayristirma sirasinda modelin yazdiginin bir kismi SESSIZCE DUSTU.

    Neden gerekli: bozuk JSON'da json_repair "basarili" doner ama string'i erken kapatip
    gerisini atabilir. O durumda hata firlamaz, log cikmaz — bolum kirpilmis halde kaydedilir
    (kullanici "2 cumle geldi, devami yok" diye gorur). Bu oran o sessiz kaybi olculebilir yapar."""
    raw = (raw_text or "").strip()
    if not raw:
        return 1.0
    # Alan adlari/JSON noktalama disinda kalan GERCEK metni kiyasla
    recovered = sum(len(v) for v in parsed.values() if isinstance(v, str))
    recovered += len(json.dumps([v for v in parsed.values() if not isinstance(v, str)], ensure_ascii=False))
    return min(1.0, recovered / len(raw))


def parse_llm_json(raw_text: str) -> dict:
    """LLM ciktisindan JSON objesi ayiklar.

    Modeller sik sik bozuk JSON uretir: string icinde ham satir sonu, kacissiz
    tirnak, eksik virgul, max_tokens kesmesi... Sirasiyla denenir:
      1. Markdown ```json``` blogu (varsa)
      2. Dengeli {...} blogu, strict=False ile (string icindeki ham kontrol
         karakterlerine izin verir)
      3. json_repair ile onarim (eksik virgul/tirnak/kapanis parantezlerini duzeltir)
    """
    candidates: list[str] = []

    # GREEDY (.*): icerikte ``` gecerse non-greedy desen blogu erken kapatip metni kirpardi
    match = re.search(r"```(?:json)?\s*(.*)\s*```", raw_text, re.DOTALL)
    if match:
        candidates.append(match.group(1).strip())

    brace_block = _extract_brace_block(raw_text)
    if brace_block:
        candidates.append(brace_block)

    for candidate in candidates:
        try:
            result = json.loads(candidate, strict=False)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    for candidate in candidates:
        try:
            result = json.loads(repair_json(candidate), strict=False)
            if isinstance(result, dict) and result:
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    raise ValueError("Model cevabindan gecerli bir JSON objesi ayiklanamadi.")
