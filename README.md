# StoryPlatform — Bölüm Hafızalı İnteraktif Hikaye Motoru

StoryPlatform, uzun soluklu yapay zeka destekli hikayelerde yaşanan **context window (bağlam penceresi) problemini** çözmek için tasarlanmış interaktif bir hikaye/RPG motorudur. İlham kaynağı SillyTavern'dir.

Temel fikir: hikayenin tamamını her seferinde modele göndermek yerine, her bölüm yazıldığında **parçalanır** (karakterler, mekanlar, eşyalar, özet) ve hafızaya atılır. Sonraki bölüm yazdırılırken modele yalnızca **damıtılmış bağlam** verilir. Böylece hikaye kaç bölüme ulaşırsa ulaşsın prompt boyutu sabit kalır ve model bağlamdan kopmaz.

## Mimari

Eski çoklu-servis yapı (Spring Boot + Kafka + ayrı Python worker) tek bir FastAPI servisinde birleştirildi:

```
[ Frontend (Vue 3 + Vite) :5173 ]
            │  REST + SSE
            ▼
[ Backend (Python 3.11+ / FastAPI) :8000 ]
            │
            ├── PostgreSQL + pgvector  (hikayeler, bölümler, varlıklar, vektörler)
            └── Gemini API (OpenAI SDK uyumlu endpoint üzerinden)
```

- Bölüm üretimi **asyncio arka plan görevlerinde** çalışır; sonuç **SSE** ile tarayıcıya anında iletilir (Kafka kaldırıldı — bu ölçekte gereksizdi).
- Aynı hikaye için eş zamanlı iki üretim, atomik durum geçişi + hikaye bazlı kilitle engellenir (ikinci istek `409` alır).
- LLM erişimi **OpenAI SDK** ile yapılır; `.env`'deki `LLM_BASE_URL` / `LLM_API_KEY` / model adları değiştirilerek sağlayıcı tek satırla değiştirilebilir.

## Hafıza Yaşam Döngüsü

1. **Bölüm üretimi:** Model her bölümü tek JSON'da döner: bölüm metni + **bölüm özeti** + `new_characters` / `updated_characters` / `new_locations` / `new_items`.
2. **Varlık hafızası (lorebook):** Varlıklar hikaye bazında isimle **upsert** edilir; kopya oluşmaz. Bilinen karakterlerin durum değişimleri (`status_change`) karakter kartına işlenir. Studio'dan elle eklenebilir/düzenlenebilir/silinebilir.
3. **Bölüm özetleri:** Her bölümün kendi kısa özeti vardır; hepsi kronolojik sırayla birleşip hikayenin omurgasını oluşturur. Özetler elle de düzenlenebilir.
4. **Vektör hafıza:** Her bölüm `gemini-embedding-001` ile (768 boyut) ayrı ayrı vektörlenir ve pgvector'de saklanır.
5. **Sonraki bölümün bağlamı:** yazarın kalıcı talimatı + negatif talimat + tüm bölüm özetleri (sıralı, tavanlı) + **son iki bölümün tam metni** + varlık kartları + hamleyle anlamca eşleşen eski bölümlerin **n-1/n/n+1 penceresi** + varsa "yazar şu bölümü değiştirdi" notları.
6. **Düzenleme akışı:** Her bölüm Studio'dan düzenlenebilir; kaydedilince bölüm yeniden özetlenir, vektörü yenilenir ve bir sonraki üretime "burada şu değişti" notu taşınır.

## Yerel Kurulum

### 1. Veritabanı
```bash
docker-compose up -d
```
> **Not:** Eski (Spring Boot'lu) sürümü çalıştırdıysan tablo şemaları uyumsuzdur; veritabanını bir kez sıfırla: `docker-compose down -v && docker-compose up -d`

### 2. Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: .\venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env            # LLM_API_KEY'e Gemini anahtarını yaz

uvicorn app.main:app --reload --port 8000
```
Tablolar ilk açılışta otomatik oluşturulur (`CREATE EXTENSION vector` dahil).

### 3. Frontend
```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

## API Özeti

| Uç | Açıklama |
|---|---|
| `POST /api/auth/register`, `/authenticate` | JWT tabanlı kayıt/giriş |
| `GET/POST /api/stories`, `GET /api/stories/my-stories` | Hikaye oluşturma/listeleme |
| `POST /api/stories/{id}/continue` | Yeni bölüm üretimini başlatır (async) |
| `GET /api/stories/{id}/stream` | SSE: üretim bitince canlı güncelleme |
| `PUT /api/stories/{id}/chapters/{index}` | Bölüm metnini düzenle (vektör de yenilenir) |
| `GET /api/stories/{id}/search?query=` | Bölümler üzerinde semantik arama (n±1 pencereli) |
| `PUT/DELETE /api/elements/{kind}/{id}` | Karakter/mekan/eşya düzenleme-silme |

## Yol Haritası

- [ ] Arayüzün bölüm bazlı görünüme taşınması (bölüm listesi, geçmiş bölüm düzenleme)
- [ ] Arama penceresinin devam promptuna kullanıcı kontrolünde enjeksiyonu
- [ ] Alembic migration altyapısı
- [ ] Yayınlama platformu (Wattpad benzeri keşfet/okuma akışı)
