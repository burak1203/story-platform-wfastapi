"""Prompt sablonlari.

Baglam duzeni (bolum sayisi kac olursa olsun sinirli kalir):
  - yazarin kalici talimatlari (style/negative prompt)
  - TUM bolum ozetleri, kronolojik sirayla (her biri kisa; cok uzarsa en eskiler atlanir)
  - gecmisten semantik olarak ilgili bolum alintilari (n-1/n/n+1)
  - SON IKI bolumun tam metni (baglam kopmasin diye)
  - varlik kartlari (karakter/mekan/esya, SillyTavern lorebook mantigi)
  - yazarin son duzenlemelerine dair notlar ("burada su degisti")
"""

import json

from ..models import Story

# Baglam butcesi sabitleri
SUMMARY_CHAR_CAP = 300        # tek bolum ozetinin prompta girecek azami uzunlugu
MAX_SUMMARIES_IN_PROMPT = 60  # bundan fazlasi varsa en eskiler atlanir
LAST_CHAPTER_CAP = 12000      # son bolumun tam metni icin karakter tavani
PREV_CHAPTER_CAP = 6000       # sondan onceki bolum icin karakter tavani

JSON_FORMAT_BLOCK = """[ÇIKTI FORMATI - KESİN KURAL]
Cevabını SADECE aşağıdaki JSON formatında ver. JSON dışında tek bir kelime yazma:
{
  "content": "Yazdığın bölümün tamamı (sadece yeni bölüm, öncekileri tekrar etme)...",
  "chapter_summary": "Bu bölümde olanların 2-3 cümlelik özeti (kim ne yaptı, ne değişti)",
  "new_characters": [{"name": "Yeni Karakter Adı", "description": "Kim olduğu, fiziksel özelliği ve rolü"}],
  "updated_characters": [{"name": "Bilinen Karakterin Adı", "status_change": "Bu bölümde ne yaptı / durumu nasıl değişti"}],
  "new_locations": [{"name": "Yeni Mekan Adı", "description": "Atmosferi ve detayı"}],
  "new_items": [{"name": "Yeni Nesne Adı", "description": "Özelliği ve önemi"}]
}
Kurallar:
- Bu bölümde İLK KEZ ortaya çıkan karakter/mekan/eşyaları "new_..." listelerine ekle.
- Bilinen listede olan bir karakter önemli bir şey yaşadıysa "updated_characters" içine ekle.
- İlgili bir şey yoksa listeyi boş bırak: []"""


def _head(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "..."


def _tail(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def _entity_lines(entities, with_status: bool = False, desc_limit: int = 200) -> str:
    lines = []
    for e in entities:
        line = f"- {e.name}: {_head(e.description or '', desc_limit)}"
        if with_status and getattr(e, "status", None):
            line += f" (Güncel durumu: {e.status.strip()})"
        lines.append(line)
    return "\n".join(lines) if lines else "(henüz yok)"


def _summaries_block(story: Story) -> str | None:
    summarized = [c for c in story.chapters if c.summary]
    if not summarized:
        return None
    skipped = len(summarized) - MAX_SUMMARIES_IN_PROMPT
    if skipped > 0:
        summarized = summarized[skipped:]
    lines = [f"Bölüm {c.index}: {_head(c.summary, SUMMARY_CHAR_CAP)}" for c in summarized]
    header = ""
    if skipped > 0:
        header = f"(en eski {skipped} bölümün özeti atlandı; gerekirse 'geçmiş sahneler' bloğuna bak)\n"
    return header + "\n".join(lines)


def parse_edit_notes(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        notes = json.loads(raw)
        return [str(n) for n in notes if str(n).strip()]
    except (json.JSONDecodeError, TypeError):
        return []


def build_chapter_system_prompt(story: Story, retrieved_block: str | None) -> str:
    """Hem ilk bolum hem devam bolumleri icin tek sablon."""
    parts: list[str] = [
        "[KİMLİK VE TON]\n"
        "Sen usta, yaratıcı ve sürükleyici bir yazarsın. Betimlemelerin güçlü, diyalogların doğaldır. "
        "Asla klişe kalıplar kullanmazsın. İnteraktif bir hikaye yazıyorsun; okuyucunun hamleleri hikayeyi yönlendirir.",
        f"[HİKAYE BAŞLIĞI]\n{story.title}",
    ]

    if story.style_prompt and story.style_prompt.strip():
        parts.append(
            "[YAZARIN KALICI TALİMATI - HER BÖLÜMDE UYGULA]\n" + story.style_prompt.strip()
        )
    if story.negative_prompt and story.negative_prompt.strip():
        parts.append(
            "[YASAKLAR - BUNLARDAN KESİNLİKLE KAÇIN]\n" + story.negative_prompt.strip()
        )

    summaries = _summaries_block(story)
    if summaries:
        parts.append("[BÖLÜM ÖZETLERİ - KRONOLOJİK]\n" + summaries)

    if retrieved_block:
        parts.append(
            "[GEÇMİŞ BÖLÜMLERDEN İLGİLİ SAHNELER]\n"
            "Okuyucunun hamlesiyle bağlantılı olabilecek eski sahneler (tutarlılık için kullan):\n" + retrieved_block
        )

    if story.chapters:
        last = story.chapters[-1]
        if len(story.chapters) >= 2:
            prev = story.chapters[-2]
            parts.append(
                f"[ÖNCEKİ BÖLÜM (Bölüm {prev.index}) - TAM METİN]\n{_tail(prev.content, PREV_CHAPTER_CAP)}"
            )
        parts.append(
            f"[SON BÖLÜM (Bölüm {last.index}) - TAM METİN]\n{_tail(last.content, LAST_CHAPTER_CAP)}"
        )
        parts.append(
            "[BİLİNEN EVREN]\n"
            f"Karakterler:\n{_entity_lines(story.characters, with_status=True)}\n\n"
            f"Mekanlar:\n{_entity_lines(story.locations)}\n\n"
            f"Eşyalar:\n{_entity_lines(story.items)}"
        )

    edit_notes = parse_edit_notes(story.pending_edit_notes)
    if edit_notes:
        parts.append(
            "[YAZARIN SON DÜZENLEMELERİ - ÇOK ÖNEMLİ]\n"
            "Yazar geçmiş bölümlerde elle değişiklik yaptı. Hikayenin GÜNCEL hali aşağıdaki gibidir; "
            "eski haliyle çelişme:\n- " + "\n- ".join(edit_notes)
        )

    if story.chapters:
        parts.append(
            "[GÖREV]\n"
            "Okuyucunun hamlesine göre hikayenin SADECE BİR SONRAKİ BÖLÜMÜNÜ yaz. "
            "Önceki metni tekrar etme, özetleme; kaldığı yerden akıcı şekilde devam et. "
            "Özetler ve bilinen evrenle TUTARLI kal; ama sen bir tekrar makinesi değilsin: "
            "hikayeyi her bölümde İLERİ taşı. Yeni karakterler, mekanlar, olaylar ve eşyalar "
            "İCAT ETMEKTEN çekinme — icat etmek bu işin kalbidir."
        )
    else:
        parts.append(
            "[GÖREV]\n"
            "Verilen konuya göre hikayenin İLK BÖLÜMÜNÜ yaz. Sürükleyici bir açılış yap, "
            "dünyayı ve ana karakterleri tanıt. Yeni karakterler, mekanlar ve eşyalar icat etmekte tamamen özgürsün."
        )

    parts.append(JSON_FORMAT_BLOCK)
    return "\n\n".join(parts)


SINGLE_CHAPTER_SUMMARY_PROMPT = (
    "Sen usta bir editörsün. Sana bir hikaye bölümü verilecek. Bu bölümde olanları "
    "EN FAZLA 3 KISA CÜMLEYLE özetle: kim ne yaptı, ne değişti, hangi yeni şey ortaya çıktı. "
    "Cümlelerini mutlaka tamamla. Cevabına SADECE Türkçe özet metnini yaz, başka hiçbir şey ekleme."
)
