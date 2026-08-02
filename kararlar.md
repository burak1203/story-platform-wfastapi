# Kararlar — neden böyle yapıldı
 
Bu dosya "ne yapıldı"yı değil **"neden öyle yapıldı"yı** tutar. Bir kararı değiştirmek
isteyen önce buradaki gerekçeyi çürütmeli.
 
---
 
## Para ve anahtarlar
 
**BYOK (kullanıcı kendi anahtarını getirir), kredi/abonelik değil.**
Kredi modeli sunucu anahtarı gerektirir; o da her ücretsiz kullanıcının faturasını
kullanıcının cebinden ödemek demek. Üstüne TR'de ödeme entegrasyonu (iyzico/BKM, KVKK,
fatura, mesafeli satış) haftalar sürer. BYOK'un tek dezavantajı churn; karşılığında
sıfır maliyet, sıfır ödeme entegrasyonu, sıfır hukuki yük ve bugün canlıya çıkabilme.
Ayrıca ilk kitle zaten SillyTavern/NovelAI kullanan, anahtar yapıştırmayı bilen
power-user'lar. Kredi katmanı **sonra** eklenecek: `key_source` enum'u şemada hazır.
 
**Cold-start çözümü kredi değil, showcase.** "Boş siteye kimse gelmez" endişesi haklı
ama çözümü herkese açık üretim değil: `is_showcase` hikayeler sunucu anahtarıyla
üretilir, ziyaretçi anahtar yapıştırmadan kaliteyi okur, sonra kendi anahtarını girer.
 
**Embedding sunucu tarafında.** Kullanıcı API anahtarını bilir ama embedding modelini
bilmez; üstelik model değişirse TÜM hikayelerin yeniden embed'lenmesi gerekir — bu
kullanıcının eline bırakılamaz. Maliyet zaten sente vuruyor.
 
**OpenAI text-embedding-3-small, Gemini değil.** Hedef kitle İngilizce olunca Gemini'nin
çok dilli üstünlüğü anlamsızlaştı; 3-small 7.5 kat ucuz ($0.02 vs $0.15 / 1M) ve
8191 token context'i chunk'lamada rahat. Karar anı erkendi çünkü provider değişimi
= tam re-embed.
 
**Boyut 768.** pgvector'ün hnsw index'i standart `vector` tipinde 2000 boyuta kadar
indexlenir; 3072 doğrudan indexlenmez. Ayrıca 1M vektör 3072'de ~12GB, 768'de ~3GB.
Kurgu RAG'inde recall kazancı marjinal, maliyet gerçek.
 
**DeepSeek V4 Flash varsayılan (kullanıcı istediğini girebilir).** 1000 bölüm ~$2.4.
**Thinking her yerde kapalı** — DeepSeek dokümanına göre thinking modunda
`temperature/top_p/penalty` sessizce yok sayılıyor; bizim üretim `temperature=0.8` ile
çeşitlilik sağlıyor, thinking açıkken bu ölür ve üretimler tekdüzeleşir.
 
---
 
## Hafıza mimarisi (ürünün kalbi)
 
**İki katman: olaylar + chunk'lar.** Biri diğerinin yerine geçemez:
 
| | Olaylar | Chunk'lar |
|---|---|---|
| Nasıl | LLM seçer (3-7/bölüm) | Düz metin bölme, LLM yok |
| Kapsam | Seçici, kayıplı, parafraz | Eksiksiz, verbatim, deterministik |
| Verir | İskelet + önem + pinned | Rastgele detay |
| Çekilir | Sorgudan **bağımsız** | Sorguya **bağlı** |
 
Olayları "eksiksiz" yapmaya çalışmak yanlış: LLM'den eksiksizlik garanti edilemez ve
her cümle olay olursa önem puanı anlamını yitirir. Bölümü bütün olarak tek vektöre
gömmek de çözüm değil: 3000 token tek vektöre sıkışınca ortalama çıkar, yerel detay
erir. **Kanıt testi:** 1. bölümün 7790. karakterindeki, olay listesine girmemiş
"dondurma" detayı ileri bir bölümde ilgili hamleyle RAG'le bulundu.
 
**Silme yok, demote var.** Düşük önem = "bu turda sabit omurgada gönderilmez";
depodan asla silinmez. Aksi halde 1. bölümün düşük puanlı detayı 90. bölümde alakalı
olduğunda geri getirilemez — ki ürünün varlık sebebi tam olarak bu.
 
**Önem dinamik, yazımda donmaz.** Olay yazıldığında puan bir ön-tahmindir; RAG'le
çekildikçe azalan artışla yükselir (tavan 0.95, sonsuza kadar 1.0'a koşmasın diye
— yoksa her şey "çok önemli" olur ve ayrım kaybolur).
 
**Rollup: son ~20 bölüm tam özet + 10'arlı ark özetleri + tek paragraf arka plan.**
Düz kesme (eski hali) 60. bölümden sonra hikayenin başını unutuyordu; hiç kesmeme ise
prompt'u lineer büyütür ve "lost in the middle" yüzünden kaliteyi düşürür. Ark özetleri
DB'de saklanır, her üretimde yeniden üretilmez; yalnızca içindeki bölüm düzenlenince
yenilenir. **Ölçüm:** 60→120 bölümde özet bloğu 879→977 token (%11), sert tavan ~3100.
 
**Son N bölüm tam metin: default 2 (1-5 ayarlanabilir).** Büyütmek tutarlılığı bir
miktar artırır ama modeli taklide iter, yaratıcılığı düşürür ve aynı bilgiyi
katbekat token'la tekrarlar. Süreklilik zayıfsa çözüm daha çok ham bölüm değil,
daha iyi retrieval.
 
**Entity kartları seçmeli, isim listesi her zaman.** Eski `MAX_ENTITIES_PER_KIND=60`
tavanı uzun hikayede en eski entity'leri bağlamdan tamamen siliyordu — model onları
yeniden icat edip çift kayıt açabilirdi. Yeni düzen: tüm isimler her zaman (~3 token),
tam kartlar yalnızca alakalı olanlar. **Ölçüm:** 120 entity'de 8891→2383 token (%73).
 
**Retrieval sorgusu = hamle + son bölümün kuyruğu.** "İçeri giriyorum" gibi kısa bir
hamlenin vektörü hiçbir şeye benzemez; son bölüm kuyruğu mevcut sahne bağlamını taşır.
 
**Prompt bileşen sırası cache-dostu:** sabit (kimlik/tür/talimat/görev/format) →
büyüyen (özetler) → yavaş (entity/pinned) → cache-kırıcı (son N/RAG/hamle). Sağlayıcı
en uzun eşleşen ön eki cache'ler; değişkeni öne koymak indirimi tamamen kaybettirir.
**Ölçüm:** +525 token sabit kazanç; canlıda %34 cache-hit görüldü.
 
---
 
## Güvenlik ve gizlilik
 
**Private için 404, 403 değil.** 403 "bu id'de bir hikaye var" bilgisini sızdırır.
Sahibi bile kendi private hikayesini public uçlardan değil, yazar uçlarından okur.
 
**Görünürlük filtresi sorgunun içinde.** "Önce çek, sonra kontrol et" deseni er geç
bir uçta unutulur; filtre `WHERE` içindeyse atlanamaz.
 
**Okuyucu DTO'ları sıfırdan yazıldı.** `story_detail` yeniden kullanılsaydı, yarın
yazar tarafına eklenen bir alan sessizce okuyucuya sızardı. "Şunu çıkar" değil
"şunu ekle" mantığı.
 
**v-html yasak, backend HTML strip etmiyor.** İçerik olduğu gibi saklanır, text olarak
render edilir. Strip etmek hem yazarın metnini bozar hem yanlış güvenlik hissi verir.
 
**Beğeni `ON CONFLICT DO NOTHING`.** `try/IntegrityError` deseni patlayan INSERT'le
transaction'ı zehirler, sonraki sorgular da düşer.
 
**SSE token'ı ana JWT değil, ayrı kısa ömürlü tek kullanımlık token.**
`EventSource` header gönderemiyor, token'ın URL'e girmesi bu yüzden kaçınılmaz —
soru "ne girecek" sorusu. Fetch tabanlı SSE'ye geçip token'ı Authorization
header'ına taşımak (a) daha temiz olurdu ama SSE tüketimini (yeniden bağlanma,
hata yönetimi) baştan yazmayı gerektiriyordu; güvenlik odaklı bir değişiklik için
gereksiz büyük bir yüzey. Bunun yerine (b): normal JWT'yle (header'dan, loglanmaz)
alınan, yalnızca tek bir hikayenin stream'i için geçerli, ~60sn ömürlü, tek
kullanımlık ayrı bir token URL'e giriyor. Sızsa bile (log, tarayıcı geçmişi,
referrer) değeri neredeyse sıfır — meşru istemci onu zaten tüketmiş oluyor.
 
---
 
## İçerik politikası
 
**Private yazım serbest, public'te açık cinsel içerik yasak.** Gerekçe hukuki, ahlaki
değil: operatör Türkiye'de ve 5651 kapsamında site erişim engeline tek şikayetle
gidebilir; tek kişilik projede bu taşınamaz. `is_adult` bayrağı şemada hazır, ciddi
kitle oluşursa yaş kapılı bölüm o gün tartışılır. Mutlak yasaklar (özellikle çocuklara
yönelik her şey, private dahil): anında sil + hesap kapat.
 
---
 
## Reddedilen fikirler (ve neden)
 
- **Ham metin chunk'lamayı atmak** — bir kez atıldı, geri alındı: olay katmanı
  rastgele detayı kaçırıyor.
- **Hayalet entity temizliği** — 90 bölüm geçmeyen karakteri silmek ürünün tezine
  aykırı. Silme yalnızca elle.
- **Cache için ID-slot mantığı** — prefix cache metin sırasını eşleştirir, ID'leri
  değil; ortadan yapılan her düzenleme o noktadan sonrasını zaten geçersiz kılar.
- **Read caching (Faz 2)** — sıfır trafikte cache invalidation bug'ı üretmekten başka
  işe yaramaz. Düzgün index yeterli.
- **Yıldız puanlama** — az kullanıcıda anlamsız (3 oyla 2.3 yıldız hikayeyi öldürür)
  ve spam yönetimi ister. Tek tık beğeni yeter.
- **OpenRouter'ı kendi testinde kullanmak** — %5.5 platform ücreti; doğrudan sağlayıcı
  ucuz. Ama *kullanıcılar için* birinci sınıf desteklenmeli, hedef kitle orayı kullanıyor.
- **PrimeVue** — v4.5.5 MIT ama donmuş; v5 PrimeUI çatısında ticari lisansa geçti,
  Community tier bile anahtar zorunlu kılıyor ve anahtar client bundle'ına gömülüyor.
  Tek kişilik projede hukuki takip yükü taşınmaz (bkz. BYOK gerekçesi). Naive UI seçildi:
  MIT, aktif, TS tema override nesnesi.
