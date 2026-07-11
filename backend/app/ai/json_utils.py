import json
import re


def parse_llm_json(raw_text: str) -> dict:
    """LLM ciktisindan ilk gecerli JSON objesini ayiklar.

    Model bazen JSON'u markdown blogu icine alir veya basina/sonuna metin ekler;
    bu yuzden once markdown blogu, sonra parantez sayarak ham blok denenir.
    """
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    start_idx = raw_text.find("{")
    if start_idx == -1:
        raise ValueError("Model cevabinda JSON bulunamadi.")

    brace_count = 0
    for i in range(start_idx, len(raw_text)):
        if raw_text[i] == "{":
            brace_count += 1
        elif raw_text[i] == "}":
            brace_count -= 1
            if brace_count == 0:
                return json.loads(raw_text[start_idx : i + 1])

    raise ValueError("Model cevabindaki JSON tamamlanmamis.")
