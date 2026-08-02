# CLAUDE.md — StoryPlatform

## Bağlam
Sen bu repoda çalışan Claude Code'sun. **Sana yazdığın açıklamalar Türkçe; kod, commit mesajları ve ÜRÜN ARAYÜZÜ İngilizce.** Proje fazlar halinde ilerler; **her faz sonunda site deploy edilebilir ve çalışır durumda kalır.** Fazları sırayla yap, kabul kriterlerini geçmeden atlama, faz bitince tek paragraflık Türkçe özet ver.

## Proje Özeti
Bölüm hafızalı interaktif hikaye motoru + Wattpad benzeri okuma platformu. Uzun hikayelerde context window problemini çözer: her bölüm parçalanır (özet + karakter/mekan/eşya kartları + vektör), sonraki bölüme yalnızca **damıtılmış bağlam** gider. Ürünün tek satırlık tezi: *hikaye kaç bölüm olursa olsun prompt sabit boyutta kalır ve hiçbir şey unutulmaz.* Her mimari karar bu teze hizmet eder.

```
[ frontend/  Vue 3 + Vite ]  ← Arayüz dili İNGİLİZCE
        │ REST + SSE
[ backend/   Python 3.11+ FastAPI :8000 ]
        ├── PostgreSQL + pgvector (Docker)
        ├── Üretim LLM'i: OpenAI SDK, KULLANICININ anahtarıyla (BYOK)
        ├── Embedding: OpenAI text-embedding-3-small, SUNUCU anahtarıyla
        └── Showcase üretimi: SUNUCU (senin) anahtarınla, sadece öne çıkan hikayeler
```

Hedef kitle: **İngilizce konuşan BYOK / interactive-fiction / roleplay topluluğu** (SillyTavern, NovelAI, JanitorAI tarzı).

---

## Anahtar & Model Mimarisi (her fazda geçerli)
- **Üretim (bölüm yazımı, özet, entity çıkarımı):** KULLANICININ anahtarı. Her istekte `X-LLM-API-Key` (ops. `X-LLM-Base-URL`, `X-LLM-Model`). Sunucuda saklanmaz, loglanmaz, DB'ye yazılmaz, hata mesajına sızmaz. Arka plan görevine tetikleyen istekten argümanla taşınır.
- **Embedding:** SUNUCU anahtarı (`EMBEDDING_API_KEY` = senin OpenAI anahtarın). Kullanıcı embedding'i görmez. Bu anahtar ASLA üretimde, kullanıcı anahtarı ASLA embedding'de kullanılmaz.
- **Showcase:** `is_showcase=true` hikayeler senin `SHOWCASE_LLM_API_KEY`'inle üretilir (cold-start: boş siteye gelen ziyaretçi kaliteyi key yapıştırmadan görür). Yalnızca admin işaretleyebilir.
- **key_source enum** (`user`|`server`, default `user`) şemada durur; `server` yolu şimdilik yalnızca showcase+admin'de aktif. Gelecekteki kredi katmanı bununla açılır (ŞİMDİ YAPMA).

## Prompt Mimarisi (Faz 2.0'da kur — kritik, geleceğe açık)
Sistem promptunu **tek sabit string olarak yazma.** Bileşenlere ayır ve builder'da birleştir:
```
base_kimlik  +  seçili tür modülleri  +  yazarın style_prompt'u  +  (dev modda) elle enjeksiyon
```
- **base_kimlik İngilizce ama dil-agnostik:** modele "hikayenin/hamlenin dilinde yaz" talimatı. Sabit üslup DAYATMA; ton türden + `style_prompt`'tan gelir.
- **Tür modülleri** dile göre anahtarlı JSON'da (`prompts/genres.json`):
  ```json
  { "thriller":      {"en": "...", "tr": ""},
    "hurt_comfort":  {"en": "...", "tr": ""},
    "crack":         {"en": "...", "tr": ""},
    "fix_it":        {"en": "...", "tr": ""},
    "psychological": {"en": "...", "tr": ""} }
  ```
  `en` şimdi dolu, `tr` sonra. Yeni tür = JSON'a satır; kod değişmez. Yazar birkaçını toggle'lar, builder style_prompt'a ekler.

## Bağlam & Hafıza Kuralları (ürünün kalbi)
Hafıza **iki katmanlı**. İkisi farklı iş yapar, biri diğerinin yerine geçemez:

| | **Olaylar (events)** | **Chunk'lar** |
|---|---|---|
| Ne | LLM'in seçtiği 3-7 önemli olay | Bölümün ~400-600 token'lık parçaları |
| Nasıl | LLM çıkarımı (üretim JSON'unda, ekstra çağrı yok) | Düz metin bölme — LLM YOK |
| Kapsam | Seçici, **kayıplı**, yeniden yazım | **Eksiksiz**, verbatim, deterministik |
| Ne verir | İskelet + önem puanı + pinned | Rastgele detay ("dondurma") |
| Retrieval | Sorgudan **bağımsız** (pinned her zaman gider) | Sorguya **bağlı** (eşleşirse gider) |

Neden ikisi de: olayları "eksiksiz" yapmaya çalışma — LLM'den eksiksizlik garanti edilemez, üstelik her cümle olay olursa önem puanı anlamını yitirir. Bölümü **bütün olarak** tek vektöre gömme de çözüm değil: 3000 token tek vektöre sıkışınca ortalama çıkar, yerel detay erir. Chunk'lar toplamda bölümün tamamını kapsar ve yerel detayı korur.

- **Olaylar:** üretim JSON'undaki `events` alanı (özet+entity ile aynı çağrı). Her olay = metin + `importance` (0.0-1.0). Embed'lenir, **sonsuza dek saklanır.**
- **Silme yok, demote var (kritik):** düşük önem = "bu turda sabit omurgada gönderilmez"; **depodan ASLA silinmez.**
- **Dinamik önem:** yazımdaki `importance` bir ön-tahmindir; RAG'le çekildikçe azalan artışla yükselir (`IMPORTANCE_CEIL=0.95`), `retrieved_count++`. Statik puan mekanizmayı bozar.
- **Pinned çekirdek:** en yüksek puanlı olaylar + protagonist/çok-geçen entity'lere dokunan olaylar **her üretimde sorgudan bağımsız** gider. "1. bölümün başkarakteri 90. bölümde hâlâ bağlamda" garantisi budur.
- **Prose özet korunur** (rollup + UI). Rollup: son ~20 bölüm özeti tam; öncesi ~10'arlı ark özetlerine sıkışır (cache'li, içindeki bölüm düzenlenince yenilenir); en eski arklar tek paragraflık arka plana iner.
- **Entity: otomatik silme YOK** (hayalet-temizleme yok); silme yalnızca Studio'dan elle. Düzenlemede sadece *yeni giren* entity eklenir.
- Bağlam bütçesi: kalıcı talimat + negatif talimat + rollup özet + entity kartları + **pinned olaylar** + **RAG bloğu (chunk)** + **son N bölüm tam metin** (N hikaye bazlı ayar, **default 2**, aralık 1-5). N'i büyütme: uzun ham bağlam modeli taklide iter, yaratıcılığı düşürür ve aynı bilgiyi katbekat token'la tekrarlar. Süreklilik zayıfsa çözüm daha çok ham bölüm değil, daha iyi retrieval.
- Yumuşak ops tavanı: ~1000 bölüm/hikaye (configurable), kaçak maliyeti için.

## Embedding & Retrieval Kuralları
- Model `text-embedding-3-small`, boyut **768** (OpenAI API `dimensions=768` — API normalize eder, elle truncate/normalize ETME), pgvector **cosine**, **hnsw** index.
- `embeddings.py` soyutlaması: `EMBEDDING_PROVIDER=openai` default; `gemini` alternatif durur (değişim = tam re-embed).
- **Embedlenen şeyler:** olaylar, chunk'lar, ve entity'lerin `description` + `status`'ü (entity embed'i *seçim* içindir — hangi kartların prompta gireceğine karar vermek, D3).
- **`chapters.embedding` kolonu DÜŞÜRÜLÜR** (C4). İçindeki eski Gemini vektörleri OpenAI sorgusuyla kıyaslanamaz, yeni bölümlerde NULL. Yerine chunk katmanı geçer.
- **Arama akışı (C4'te bu hale gelir):**
  1. **Sorgu = kullanıcının hamlesi + son bölümün kuyruğu (~200 token).** Sadece hamle kullanmak yetmez: "içeri giriyorum" gibi kısa hamlenin vektörü hiçbir şeye benzemez, arama boş döner. Son bölüm kuyruğu mevcut sahne bağlamını taşır.
  2. Chunk'larda vektör araması → **en iyi 5**, son N bölüm hariç (zaten tam gidiyorlar).
  3. Her isabetin **aynı bölümdeki chunk±1**'i eklenir (sahnenin başı/sonu kesilmesin). Bölüm bazlı n±1 penceresi KALKAR.
  4. Çakışan/bitişik chunk'lar **tek bloğa birleşir** (aynı metin iki kez gitmesin).
  5. Kronolojik sıralanır (bölüm, sonra chunk sırası).
  6. RAG bloğu toplam **~2000 token tavanı**.
  7. Olaylar da ayrıca aranır; prompta **yalnızca chunk isabeti olmayan bölümlerden** ayrı blok olarak girer (aynı şeyi iki kez söyleme). Eşleşen olayın `importance`↑ + `retrieved_count++`.
- Eski `content[:1200]` (bölüm **başından** alıntı) mantığı tamamen kalkar — sahne bölümün sonundaysa alıntıda hiç görünmüyordu.
- Import'ta OpenAI **Batch API** (%50). Sunucu embedding anahtarında **billing açık**.
- Kötüye kullanım: `EMBED_DAILY_LIMIT` (default 300)/kullanıcı, aşımda 429.

## Token Sayma & Geliştirici Modu (Faz 3, altyapı Faz 2.0)
- **Token sayma (tahmin uydurma):** (1) gerçek — yanıttaki `usage.prompt_tokens`/`completion_tokens`; (2) gönderim öncesi — `tiktoken` ile **bölüm bazında kırılım** (özetler / son-2 / entity / RAG / talimat) + kaba maliyet (`token × model fiyatı`). BYOK'ta parayı kullanıcı ödediği için maliyet göstergesi güven verir.
- **Developer mode (3 katman, toggle default kapalı):** (1) üretimde modele giden **tam prompt** görüntüleme (bölüm kaydına yazılır, katlanır panel); (2) **token paneli** (yukarıdaki kırılım); (3) *gelecek* — elle prompt enjeksiyonu (altyapıyı Faz 2.0 prompt mimarisinde bırak, özelliği sonra aç).

## Ortam Değişkenleri (.env.prod commit ETME; `.env.prod.example` commit et)
`POSTGRES_PASSWORD`, `JWT_SECRET` (`openssl rand -hex 32`), `EMBEDDING_API_KEY` (OpenAI), `EMBEDDING_PROVIDER=openai`, `EMBEDDING_MODEL=text-embedding-3-small`, `EMBEDDING_DIM=768`, `EMBED_DAILY_LIMIT=300`, `SHOWCASE_LLM_API_KEY`, `SHOWCASE_LLM_MODEL`, `GOOGLE_OAUTH_CLIENT_ID`, `CORS_ORIGINS=https://<site>`, `ENV=production`

## Genel Kurallar
- **GIT'İ KULLANICI YÖNETİR.** Claude hiçbir koşulda `git commit`, `git add` veya `git push` ÇALIŞTIRMAZ — kullanıcı "commit'le" dese bile. Bunun yerine kopyalanıp yapıştırılacak komutu (add + commit mesajı) metin olarak verir; commit'i kullanıcı atar. (Okuma amaçlı `git status`/`git log`/`git diff` serbest.)
- Sır ASLA loglanmaz/commit edilmez; `.env*` `.gitignore`'da (doğrula).
- Endpoint sözleşmesi değişince frontend aynı commit'te güncellenir.
- Frontend'de `v-html` YASAK; kullanıcı/LLM içeriği text render (`white-space: pre-wrap`).
- Her yeni uçta üç soru: auth zorunlu mu, sahiplik/görünürlük (IDOR) var mı, Pydantic max limit var mı.
- Tek uvicorn worker (kilit süreç içi olabilir); worker artırmadan kilit DB-atomik olmalı.
- Prod'da `DEBUG=False`; ham stack-trace kullanıcıya dönmez.
- Küçük kararı kendin ver; mimari değişikliğinde tek cümle öneriyle sor.

---

## FAZ 0 — Çekirdek + BYOK + Prod paketleme (TAMAMLANDI)
- [x] BYOK dönüşümü; sunucuda üretim anahtarı yok. Docker + Caddy (SSE `flush_interval -1`, HSTS/X-Frame/nosniff) lokalde doğrulandı. Loglarda anahtar yok; restart sonrası veri duruyor.
- (Ertelendi) 0.4 Azure deploy → Faz 2.5.

## FAZ 1 — Google Girişi + Güvenlik Tabanı (TAMAMLANDI)
- [x] Google OAuth; e-posta/şifre (bcrypt) korunur; hesaplar tek e-postada birleşir. IDOR sahiplik kontrolleri (iki kullanıcıyla test). Rate limit (üretim 3/dk, auth 5/dk, arama 20/dk). Pydantic tavanları; pip-audit + npm audit temiz.

---

## FAZ 2.0 — Hafıza/Embedding/Prompt Refactor + Alembic (ÖNCE BU)
Okuyucu platformundan önce: şema ve çekirdek hafıza mantığı burada değişiyor, tek dalgada topla.

### A. Önce doğrula & düzelt (koddan; her madde ya düzeltilir ya "zaten halli" raporlanır)
Zaten halledilmiş, DOKUNMA (doğrula geç): RAG son-2 bölümü dışlıyor; `pending_edit_notes` tek-seferlik tüketiliyor; entity `status_change` üzerine yazıyor + tavanlar var; stuck GENERATING açılışta + exception'da resetleniyor.
Gerçek düzeltmeler:
1. **`edit_chapter` entity/olay re-extraction yapmıyor** — düzenlemede içerik+embedding+özet yenileniyor ama `_apply_entities` çağrılmıyor. Düzenlenen metin üzerinden **yeni giren** entity+olay eklenmeli (kullanıcı ctx'i mevcut). **Silme/hayalet-temizleme YOK** — entity ve olay asla otomatik silinmez (silme yalnızca Studio'dan elle). `source_chapter_id` gibi köken kolonuna gerek yok.
2. **`my_stories`/`story_detail` her hikayenin tüm bölüm metnini serialize ediyor** — dashboard için hafif liste DTO'su (başlık, durum, bölüm sayısı, kısa özet, istatistik); tam içerik yalnızca tek-hikaye detay ucunda.
3. Küçük: `_story_locks` dict'i temizlenmiyor (yavaş sızıntı) — kilidi kullanımdan sonra ayıkla ya da bounded yapı kullan.

### B. Alembic'e geçiş
Mevcut şema auto-create ile var. `alembic init` + async `env.py`, sonra **mevcut şemayı baseline al** (initial migration mevcut tabloları YENİDEN YARATMASIN — baseline'la stamp'le), auto-create/`ALTER TABLE` bloklarını kapat. Amaç: prod DB bozulmadan geçiş. **En riskli adım — dikkat.**

### C. Embedding OpenAI + olay katmanı (TAMAMLANDI)
`event` tablosu (hnsw/cosine), üretim JSON'unda `events`, OpenAI `text-embedding-3-small` `dimensions=768`, dinamik önem (azalan artış, `IMPORTANCE_CEIL=0.95`), lazy/bounded/idempotent backfill (`BACKFILL_PER_RUN=3`, `MAX_BACKFILL_ATTEMPTS=3`, events-only). Canlı doğrulandı.

### C4. Chunk katmanı + retrieval düzeltmeleri (TAMAMLANDI)
Olay katmanı iskeleti taşıyor ama **rastgele detayı kaçırıyor** ("1. bölümde dondurma yedi" → 90. bölümde bulunamıyor, çünkü olay listesine girmemiş). Chunk katmanı bu deliği kapatır. Bkz. "Bağlam & Hafıza" tablosu + "Embedding & Retrieval Kuralları" akışı.
1. **`chunks` tablosu:** `id`, `story_id`, `chapter_id` FK (CASCADE), `chunk_index`, `text`, `embedding vector(768)` (nullable), `created_at`; hnsw/cosine. Bölüm üretilince/düzenlenince ~400-600 token'lık parçalara böl (paragraf sınırlarına saygılı), **tek batch çağrıyla** embed'le, idempotent upsert (düzenlemede o bölümün chunk'ları yenilenir, yetim kalmaz). **LLM çağrısı YOK** — düz metin bölme.
2. **`chapters.embedding` kolonunu DÜŞÜR** (ayrı migration). Eski Gemini vektörleri OpenAI sorgusuyla kıyaslanamaz, yeni bölümlerde zaten NULL.
3. **Entity embed kolonları:** `characters`/`locations`/`items`'a `embedding vector(768)` nullable. `description` (+ karakterde `status`) birleştirilip embed'lenir; status değişince yeniden embed. **Kullanımı D3'te** (kart seçimi) — C4'te sadece doldur.
4. **Arama akışını "Embedding & Retrieval Kuralları"ndaki 7 adıma getir:** sorgu zenginleştirme (hamle + son bölüm kuyruğu), chunk top-5, chunk±1, bitişik blok birleştirme, kronolojik sıra, ~2000 token tavanı, olaylar yalnızca chunk isabeti olmayan bölümlerden. Bölüm bazlı n±1 ve `content[:1200]` mantığını KALDIR.
5. **Backfill:** mevcut bölümler için chunk üretimi — LLM gerektirmediği için olay backfill'inden bağımsız, ucuz ve hızlı; aynı lazy/bounded iskeleti kullan.

### D. Rollup + pinned çekirdek + prompt bileşenleştirme
- **D1 (TAMAMLANDI):** dil-agnostik prompt (Türkçe iskele kalmadı, CRITICAL LANGUAGE RULE eklendi) + cache-dostu bileşen sıralaması (sabit → büyüyen → yavaş → cache-kırıcı; hamle user mesajında) + `prompts/genres.json` iskeleti. Ölçüm: ortak prefix +525 token sabit kazanç, 30 bölümde ~2000.
- **D2 — Rollup:** son ~20 bölüm özeti tam; öncesi ~10'arlı ark özetleri (DB'de saklanır, her üretimde yeniden ÜRETİLMEZ; yalnızca içindeki bölüm düzenlenince yenilenir); en eski arklar tek paragraflık arka plan. Doğrulama: 60+ bölümlük sentetik hikayede özet bloğu token boyutu SABİT kalır **ve** 1. bölümün bilgisi hâlâ (sıkışmış olarak) bağlamda.
- **D3 — Pinned + token + prompt maddeleştirme + entity seçimi:**
  - Pinned çekirdek (bkz. "Bağlam & Hafıza"), sorgudan bağımsız.
  - Token: `usage.prompt_tokens`/`completion_tokens` yakala + tiktoken ile **bileşen bazlı kırılım** (sabit ön ek / rollup / entity / pinned / RAG / son-N / hamle) + kaba maliyet. UI Faz 3.
  - **Prompt maddeleştirme:** `style_prompt` ve `negative_prompt` tek blob olmaktan çıkıp **sıralı liste** olur (`id`, `text`, `enabled`, `order`). Faydası tek tek aç/kapa + izole etme + sıralama. **NOT: cache için ID-slot mantığı işe YARAMAZ** — prefix cache metin sırasını eşleştirir, ID'leri değil; ortadan yapılan her düzenleme o noktadan sonrasını zaten geçersiz kılar. Tek gerçek optimizasyon: kalıcı kurallar üstte, deneysel olanlar altta. Yazar ayda bir düzenler, bölüm başına değil — cache kırılması önemsiz.
  - **Entity seçimi:** her bölümde TÜM kartları gönderme. Her zaman giden: tüm entity'lerin **sadece isim listesi** (~3 token/isim — model "bu isim zaten var" bilsin, çift kayıt olmasın). **Tam kartlar** yalnızca alakalı olanlar için: hamlede adı geçenler + son N bölümde geçenler + RAG'le çekilenlerde geçenler + pinned çekirdek. Kartları ikiye böl: **sabit çekirdek** (protagonist/çok geçen) erken ve değişmez konumda (cache), **sahneye özel seçilenler** RAG yanında geç konumda.
  - Son N bölüm sayısı hikaye bazlı ayar (default 2, aralık 1-5).

### Faz 2.0 kabul
- [x] Doğrulama listesi kapandı (A); Alembic devrede (B); olay katmanı + OpenAI embedding + backfill çalışıyor (C); dil + cache sıralaması + genres.json (D1)
- [x] C4: chunk katmanı çalışıyor, `chapters.embedding` düşürüldü, entity embed'leri dolu, sorgu zenginleştirme devrede
- [x] D2 rollup: uzun hikayede özet bloğu sabit boyutta, kayıp yok
- [x] D3: pinned çekirdek sorgudan bağımsız gidiyor; token kırılımı yakalanıyor; prompt maddeleşti; entity seçimi devrede

---

## FAZ 2 — Okuyucu Platformu (TAMAMLANDI)

### Şema (Alembic migration)
`stories`: `visibility` (private|unlisted|public, default private), `description`, `tags` (text[]), `is_adult` (bool false), `is_showcase` (bool false), `key_source` (user|server, user), `published_at`. Yeni: `comments` (chapter_id, user_id, body ≤2k, is_author_pinned), `chapter_votes` (chapter_id, user_id, **unique**), `reports` (target_type, target_id, reporter_id, reason, status). `users.is_admin` (bool false). **Index:** visibility, published_at, tags (GIN), full-text `tsvector` (title+description) GIN. **Caching YOK** (bu ölçekte gereksiz).

### Uçlar + sayfalar (İngilizce arayüz)
- Yayımlama: stüdyoda visibility değiştirme. **public + is_adult ENGELLİ** (baştan kontrol). Public'e alırken kurallar onayı. **Public bölümler üretildikçe görünür** (ayrı snapshot yok — launch için bilinçli seçim).
- Ana sayfa: son yayımlananlar + arama (Postgres full-text; title/description/tags). pgvector ana sayfaya girmez.
- Okuma sayfası **mobile-first** (375px test): metin, önceki/sonraki, font boyutu, koyu tema.
- Beğeni: tek tık, geri alınabilir (unique). Yıldız YOK. Yorum: bölüm bazlı düz liste, sayfalı; yazar yorumu rozetli + sabitlenebilir; thread YOK. Yazar profili: kullanıcı adı, public hikayeler, toplam beğeni.
- Erişim: public okuma auth'suz (rate-limitli); unlisted = linki bilen; private = sadece sahibi. Private hiçbir public uçtan sızmaz.

### Faz 2 kabul
- [x] Yayımlanan hikaye ana sayfada+aramada; private sızmıyor; public+adult engelli
- [x] Girişsiz okuma çalışıyor; beğeni/yorum giriş istiyor; mobil okuma 375px'te düzgün

---

## FAZ 2.5 — Azure Deploy (SIRADAKİ)
`DEPLOY.md`: Azure for Students → Ubuntu 24.04, B2ls_v2 (2 vCPU / 4 GB), Poland Central, SSH key, NSG yalnızca 22/80/443, Static IP (`A.B.C.D` — ilk VM silindi, yeni sunucuda gerçek değer yazılacak) → docker+ufw → clone → `.env.prod` (sunucuda elle) → Caddyfile `A-B-C-D.sslip.io` → `up -d --build`. **Deploy öncesi: OpenAI + Google Cloud günlük hard spend cap ($5-10)** — embedding+showcase senin anahtarlarında.
Smoke test: HTTPS+kayıt/giriş(JWT+Google); BYOK üretim→SSE; eş zamanlı 409; düzenle+re-embed+arama; yayımla+oku+beğen+yorum; loglarda anahtar yok; restart sonrası veri duruyor.

## FAZ 3 — Import + Dev Modu UI + Prompt Şeffaflığı
- **Import (.txt, .docx):** yükle → ayrıştır ("Chapter/Bölüm X"/"#" regex; yoksa ~2500 kelime blok; docx→python-docx) → önizleme + maliyet onayı → arka plan: her bölüm özet+entity+olay+**olay/chunk-embed (Batch API)**, SSE ilerleme. Kısmi hata toleransı. PDF YOK.
- **Dev modu UI:** Faz 2.0'da kurulan token yakalama + prompt bileşenlerini arayüze bağla — tam prompt görüntüleme + token/maliyet paneli. Elle enjeksiyon *sonra*.
- **Düzenleme çakışması:** iyimser kilit (`updated_at`, uyuşmazsa 409).

## FAZ 4 — Moderasyon, İçerik Politikası, Operasyon
- **İçerik:** private serbest. **public'te açık cinsel içerik yasak** (operatör TR'de, 5651). `is_adult` ileri için rezerve. Mutlak yasaklar (özellikle çocuklara yönelik her şey, private dahil): anında sil + hesap kapat. Tek sayfa Terms + public onay kutusu.
- **Araçlar:** her bölüm/yorumda "Report" → `reports`. Admin (`is_admin`): rapor listesi, gizle/sil, dondur. Otomatik moderasyon YOK.
- **Ops:** gece `pg_dump` cron (7 gün) + haftalık Azure snapshot. Deploy: `git pull && docker compose -f docker-compose.prod.yml up -d --build`.

---

## Yapılmayacaklar (istemeden başlama)
Kredi/abonelik/ödeme; genel sunucu üretim anahtarı (showcase hariç); read caching; i18n çoklu-dil altyapısı (arayüz tek dil İngilizce; tür promptlarında `tr` alanı sonra); elle prompt enjeksiyonu özelliği (altyapı hazır, özellik sonra); token-token streaming (JSON çıktı formatıyla çelişir); takip/bildirim; yorum thread'leri; PDF/OCR; otomatik içerik moderasyonu; kapak görselleri; context caching (kredi katmanına kadar).
