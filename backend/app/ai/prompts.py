"""Prompt sablonlari.

Ana fikir: modele hikayenin TAMAMI degil, damitilmis bir baglam verilir:
  - kosan ozet (running summary)
  - sadece son bolumun tam metni
  - varlik kartlari (karakter/mekan/esya, SillyTavern lorebook mantigi)
  - gerekiyorsa gecmisten semantik olarak ilgili bolum alintilari (n-1/n/n+1)
Boylece bolum sayisi kac olursa olsun prompt boyutu sabit kalir.
"""

from ..models import Story

JSON_FORMAT_BLOCK = """[ÇIKTI FORMATI - KESİN KURAL]
Cevabını SADECE aşağıdaki JSON formatında ver. JSON dışında tek bir kelime yazma:
{
  "content": "Yazdığın bölümün tamamı (sadece yeni bölüm, öncekileri tekrar etme)...",
  "new_characters": [{"name": "Yeni Karakter Adı", "description": "Kim olduğu, fiziksel özelliği ve rolü"}],
  "updated_characters": [{"name": "Bilinen Karakterin Adı", "status_change": "Bu bölümde ne yaptı / durumu nasıl değişti"}],
  "new_locations": [{"name": "Yeni Mekan Adı", "description": "Atmosferi ve detayı"}],
  "new_items": [{"name": "Yeni Nesne Adı", "description": "Özelliği ve önemi"}]
}
Kurallar:
- Bu bölümde İLK KEZ ortaya çıkan karakter/mekan/eşyaları "new_..." listelerine ekle.
- Bilinen listede olan bir karakter önemli bir şey yaşadıysa "updated_characters" içine ekle.
- İlgili bir şey yoksa listeyi boş bırak: []"""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]


def _entity_lines(entities, with_status: bool = False, desc_limit: int = 200) -> str:
    lines = []
    for e in entities:
        desc = (e.description or "").strip()
        if len(desc) > desc_limit:
            desc = desc[:desc_limit] + "..."
        line = f"- {e.name}: {desc}"
        if with_status and getattr(e, "status", None):
            line += f" (Güncel durumu: {e.status.strip()})"
        lines.append(line)
    return "\n".join(lines) if lines else "(henüz yok)"


def build_chapter_system_prompt(story: Story, retrieved_block: str | None) -> str:
    """Hem ilk bolum hem devam bolumleri icin tek sablon.

    Ilk bolumde ozet/son bolum/varlik bloklari bos olacagi icin dogal olarak sadelesir.
    """
    parts: list[str] = [
        "[KİMLİK VE TON]\n"
        "Sen usta, yaratıcı ve sürükleyici bir yazarsın. Betimlemelerin güçlü, diyalogların doğaldır. "
        "Asla klişe kalıplar kullanmazsın. İnteraktif bir hikaye yazıyorsun; okuyucunun hamleleri hikayeyi yönlendirir.",
        f"[HİKAYE BAŞLIĞI]\n{story.title}",
    ]

    if story.running_summary:
        parts.append(f"[ŞU ANA KADARKİ HİKAYENİN ÖZETİ]\n{story.running_summary.strip()}")

    if retrieved_block:
        parts.append(
            "[GEÇMİŞ BÖLÜMLERDEN İLGİLİ SAHNELER]\n"
            "Okuyucunun hamlesiyle bağlantılı olabilecek eski sahneler (tutarlılık için kullan):\n" + retrieved_block
        )

    if story.chapters:
        last = story.chapters[-1]
        parts.append(f"[SON BÖLÜM (Bölüm {last.index}) - TAM METİN]\n{_truncate(last.content, 15000)}")

    if story.chapters:
        parts.append(
            "[BİLİNEN EVREN]\n"
            f"Karakterler:\n{_entity_lines(story.characters, with_status=True)}\n\n"
            f"Mekanlar:\n{_entity_lines(story.locations)}\n\n"
            f"Eşyalar:\n{_entity_lines(story.items)}"
        )
        parts.append(
            "[GÖREV]\n"
            "Okuyucunun hamlesine göre hikayenin SADECE BİR SONRAKİ BÖLÜMÜNÜ yaz. "
            "Önceki metni tekrar etme, özetleme; kaldığı yerden akıcı şekilde devam et. "
            "Bilinen evrenle tutarlı kal ama yeni karakterler, mekanlar ve eşyalar icat etmekte tamamen özgürsün."
        )
    else:
        parts.append(
            "[GÖREV]\n"
            "Verilen konuya göre hikayenin İLK BÖLÜMÜNÜ yaz. Sürükleyici bir açılış yap, "
            "dünyayı ve ana karakterleri tanıt. Yeni karakterler, mekanlar ve eşyalar icat etmekte tamamen özgürsün."
        )

    parts.append(JSON_FORMAT_BLOCK)
    return "\n\n".join(parts)


def build_summary_fold_prompt(previous_summary: str | None) -> str:
    base = (
        "Sen usta bir editörsün. Görevin, uzun soluklu bir hikayenin 'koşan özetini' güncel tutmak. "
        "Sana hikayenin şu ana kadarki özeti ve yeni yazılan son bölüm verilecek. "
        "İkisini birleştirip GÜNCEL tek bir özet yazacaksın: ana olay örgüsü, karakterlerin son durumu, "
        "motivasyonları ve çözülmemiş düğümler. En fazla 3 paragraf. "
        "Cevabına SADECE Türkçe özet metnini yaz, başka hiçbir açıklama ekleme."
    )
    if not previous_summary:
        base += " Önceki özet henüz yok; özeti sıfırdan bu bölümden çıkar."
    return base
