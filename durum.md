# Durum — nerede kaldık

Güncelleme: 27 Temmuz 2026

---

## Tamamlananlar

| Faz | İçerik | Durum |
|---|---|---|
| 0 | BYOK dönüşümü, Docker + Caddy prod paketleme | ✅ |
| 1 | Google OAuth, IDOR taraması, rate limit, Pydantic tavanları | ✅ |
| 2.0 | Alembic, olay + chunk katmanları, OpenAI embedding, rollup, pinned çekirdek, token muhasebesi, entity seçimi, prompt maddeleri | ✅ |
| 2 | Okuyucu platformu: yayımlama, public uçlar, beğeni, yorum, mobile-first arayüz | ✅ |
| 2.5.1 | Deploy öncesi lokal doğrulamalar | ✅ |

**Sırada:** 2.5.2 (Azure kurulumu) → 2.5.3 (canlı smoke test) → Faz 3 (import + dev
modu UI) → Faz 4 (moderasyon + operasyon).

---

## Sunucu

- Azure VM, **Poland Central**, **B2ls_v2** (2 vCPU / 4 GB)
- Statik IP: **74.248.32.128** → site adresi `74-248-32-128.sslip.io`
- NSG: yalnızca 22, 80, 443
- Not: DEPLOY.md'de West Europe + B2s yazıyor, güncellenmeli (o boyut abonelikte yoktu)

---

## Şema (tablolar)

`users` · `stories` · `chapters` · `events` · `chunks` · `arcs` · `characters` ·
`locations` · `items` · `prompt_items` · `comments` · `chapter_votes` · `reports` ·
`embed_usage` · `alembic_version`

Vektör taşıyanlar: `events`, `chunks`, `characters`, `locations`, `items` — hepsi
768 boyut, cosine, hnsw. `chapters.embedding` düşürüldü (eski Gemini uzayıydı).

---

## Bilinen eksikler ve riskler

**Yedekleme yok.** En büyük açık. `pg_dump` cron + Azure snapshot Faz 4'te planlı ama
canlıya çıkmadan önce en azından bir kere elle alınmalı. Sunucu ölürse veri gider.

**İzleme/uyarı yok.** Site çökerse haberin olmaz. Faz 4.

** okuyucu arayüzü İngilizce.** Hedef kitle İngilizce olduğu
için Studio da çevrilmeli — mekanik iş, deploy'u geciktirmesin diye ertelendi.

**Bölüm 17 kırpık.** JSON ayrıştırma hatası yüzünden metnin çoğu kayboldu; özet ve
olaylar tam. Studio'dan elle tamamlanmalı, yoksa sonraki bölümler okuyucunun görmediği
olaylara atıf yapar. (Emniyet ağı eklendi: `coverage_ratio` < %55 ise yeniden deneniyor.)

**Ark özeti kalitesi gerçek LLM'le görülmedi.** Rollup yapısı doğrulandı ama gerçek
ark özetleri sentetik/sahte sıkıştırıcıyla test edildi. 20+ bölümlük bir hikayede
tarayıcıdan bakılmalı.

**Unlisted hikayelere beğeni/yorum açık.** Bilinçli bırakıldı; ileride hikaye başına
"yorumlar açık/kapalı" anahtarı doğru çözüm.

**Otomatik moderasyon yok.** `reports` tablosu var, admin araçları Faz 4'te. Şu an
manuel.

---

## Deploy öncesi kullanıcının yapacakları

- [ ] OpenAI panelinde **günlük hard spend cap ($5-10)** — embedding senin anahtarında
- [ ] Google Cloud spend cap (OAuth kullanılacaksa)
- [ ] `.env.prod` değerleri: `openssl rand -hex 32` ile JWT_SECRET, güçlü
      POSTGRES_PASSWORD, OpenAI embedding anahtarı (billing AÇIK — free tier prod'da
      429 verir)
- [ ] En az bir kere elle `pg_dump` alma alışkanlığı

---

## Deploy sırasında dikkat edilecekler

Bunlar geçmişte gerçekten sorun çıkardı:

- **`POSTGRES_PASSWORD` yalnızca volume ilk oluşurken uygulanır.** Sonradan
  değiştirirsen backend "password authentication failed" ile açılamaz.
- **Konteyner sessiz ölümü** — `alembic/env.py`'de `disable_existing_loggers=False`
  düzeltmesi yapıldı; olmasaydı açılış hatasında konteyner tek satır yazmadan sonsuz
  restart dönerdi.
- **SSE Caddy üzerinden** — `flush_interval -1` şart, yoksa bölüm üretimi canlı
  akmaz, tamponlanır.
- **Derin rota yenileme** (`/s/1/1`) — Caddy `try_files` SPA fallback'i olmadan 404.
- **Tek uvicorn worker** — eş zamanlılık kilidi süreç içi; worker artırmadan önce
  kilidin DB-atomik olduğu doğrulanmalı.
- **`idle in transaction`** — rollup'ta LLM çağrısı boyunca DB transaction'ı açık
  tutuluyordu, tabloyu kilitliyordu. Düzeltildi; canlıda da doğrulanmalı.
