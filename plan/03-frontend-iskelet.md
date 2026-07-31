# Faz 3.1 — Frontend İskelet: Naive UI + Navigasyon + Sidebar

> Bu dosyayı `plan/03-frontend-iskelet.md` olarak repoya koy.
> Claude Code'a: **"plan/03-frontend-iskelet.md dosyasını oku ve ADIM 1'den başla."**

---

## Amaç

Şu an sitede sayfalar arası geçiş yok. Ana sayfa, hikayelerim, profil, ayarlar
arasında dolaşılamıyor; her ekranı görmek için URL elle yazılıyor. Bu iş bittiğinde
gezinilebilir bir uygulama kabuğu olacak.

**Bu iş görsel cila DEĞİL.** Amaç iskelet: navigasyon, kabuk, sidebar davranışı.
Renk/tipografi ince ayarı sonraki bir işte yapılacak. Ama tema **token'lar üzerinden**
kurulacak ki o iş geldiğinde bileşenleri yeniden yazmak gerekmesin, sadece token
değerleri değişsin.

---

## Değişmezler (bunlara aykırı bir şey yapma)

- **Arayüz dili İNGİLİZCE.** Bu işte yazılan her yeni UI metni İngilizce olacak.
  Mevcut Türkçe metinleri çevirmek bu işin kapsamında DEĞİL (ayrı iş), ama yeni
  Türkçe metin de EKLENMEYECEK.
- **`v-html` YASAK.** Kullanıcı/LLM içeriği text olarak render edilir
  (`white-space: pre-wrap`).
- **Backend'e dokunma.** Bu iş tamamen `frontend/` içinde. Endpoint sözleşmesi
  değişmiyor. Backend'de bir eksik fark edersen düzeltme, RAPORLA.
- **Git'i kullanıcı yönetir.** `git add`/`commit`/`push` ÇALIŞTIRMA. İş bitince
  kopyalanacak komutu metin olarak ver. (`git status`/`diff` okuma amaçlı serbest.)
- **Okuma sayfası mobile-first.** 375px'te bozulan hiçbir şey kabul edilmez.

---

## Çalışma ritmi

Beş adım var. **HER ADIMDAN SONRA DUR**, ne yaptığını 3-5 satırla özetle, kullanıcının
`npm run dev` ile göz doğrulaması yapmasını bekle ve onay iste. Onay almadan sonraki
adıma geçme.

Sebep: bir şey bozulduğunda hangi adımda bozulduğu net olsun. Frontend'de tek dalgada
30 dosya değişirse ve site açılmazsa nereden başlanacağı belli olmaz.

---

## Mimari karar: İKİ ayrı kabuk

Bu en önemli karar, ADIM 2'den önce oku.

Tek bir kabuk kurup her sayfayı içine koymak **yanlış olur**. İki farklı kullanıcı
modu var ve ihtiyaçları çelişiyor:

| | **Reader shell** | **Studio shell** |
|---|---|---|
| Kim | Girişsiz ziyaretçi dahil herkes | Giriş yapmış yazar |
| Sayfalar | Ana sayfa, yazar profili, hikaye tanıtımı | Dashboard, hikaye düzenleme, ayarlar |
| Sidebar | YOK | VAR (açılır/kapanır) |
| Öncelik | Metin okunabilirliği, mobil, sade | Yoğun araç erişimi, panel |

Okuma sayfasına Studio sidebar'ı koyarsan mobilde okuma deneyimi ölür — ekranın
yarısını navigasyon yer. Bu yüzden iki ayrı layout bileşeni olacak, router bunları
nested route ile seçecek.

**Üçüncü grup: KABUKSUZ.** Her sayfa bir kabuğa girmez. Şunlar doğrudan render olur:

- **Okuma sayfası (`ReadView`)** — kendi ince çubuğu var ve bu bilinçli bir tasarım
  (gerekçesi `SiteHeader`'ın tepesinde yazılı). ReaderLayout'a sokmak çift başlık üretir.
- **`LoginView` / `RegisterView`** — ortalanmış tam ekran düzenleri korunmalı; header'lı
  kabuğa girerlerse bu ortalama bozulur.

Bu grup için **boş bir layout bileşeni İCAT ETME.** Kabuksuz route'lar router'da
layout sarmalayıcısı olmadan, doğrudan tanımlanır.

**İçerik genişliği kabukta SABİT YAZILMAZ.** ReaderLayout genişliği route meta'sından
okur: `meta: { width: 'wide' | 'narrow' }`. Aksi halde hikaye tanıtımının dar okunabilir
kolonu ile ana sayfanın geniş ızgarası aynı genişliğe hapsolur.

---

## ADIM 1 — Naive UI kurulumu ve tema

> **Kütüphane seçimi:** Naive UI (MIT, aktif geliştirilen). PrimeVue değerlendirildi ve
> REDDEDİLDİ — gerekçe `kararlar.md` → "Reddedilen fikirler".

1. Naive UI'ı kur ve Vue uygulamasına bağla. **Sürümü `package.json`'da SABİTLE**
   (`^`/`~` koyma, tam sürüm yaz) ki beklenmedik bir major atlaması olmasın.
   **ÖNEMLİ:** Ezberden import yolu yazma — önce `node_modules` içindeki kurulu sürümü
   kontrol et, **o sürümün geçerli tema kurulum yöntemini** kullan.
2. Hazır temayı **kendi token katmanınla sarmala.** Temayı doğrudan kullanma; üstüne
   proje token'ları binen bir katman olsun. Naive UI'da bunun doğal karşılığı
   `GlobalThemeOverrides` nesnesidir (`NConfigProvider :theme-overrides`). Böylece
   ileride renk/yuvarlaklık değiştirmek tek dosyada yapılır.
3. **Dark mode altyapısı kurulsun.** Okuma sayfasında koyu tema zaten var
   (`readerPrefsStore`, `<html>` üzerinde `dark` sınıfı); Naive UI bileşenleri **aynı
   anahtarı** dinlemeli, ayrı bir tema anahtarı OLMASIN. Pratikte: aynı store alanı hem
   Tailwind'in `dark:` varyantını hem de `NConfigProvider`'ın `:theme`'ini sürer.
4. **Stil sırasına dikkat:** Naive UI CSS-in-JS kullanır ve stillerini çalışma anında
   enjekte eder. `index.html`'e `<meta name="naive-ui-style">` çapası konmazsa stiller
   Tailwind'den SONRA girer ve bir bileşene `class="w-full"` vermek işe yaramaz.
5. Icon seti kur (`@vicons/*` ailesinden biri — **birini seç, karıştırma**).
6. Doğrulama olarak geçici bir sayfaya birkaç Naive UI bileşeni koy (Button, Card,
   Input), açık/koyu temada göründüğünü gör, sonra o geçici sayfayı SİL.

**Bileşen seçimi kısıtı:** Standart bileşenlerde kal (Button, Card, Input, Dialog,
Drawer, DataTable). Egzotik bileşenlere derin bağımlılık kurma — ileride kütüphane
değiştirmek gerekirse çıkış maliyeti düşük kalsın.

**Kabul kriteri:** `npm run dev` çalışıyor, konsolda hata yok, Naive UI bileşeni
render ediliyor, tema anahtarı okuma sayfasındakiyle aynı, bileşene verilen Tailwind
utility'si tutuyor.

**DUR, özet ver, onay iste.**

---

## ADIM 2 — Uygulama kabukları

1. Önce **mevcut durumu keşfet**: `frontend/src` altındaki router tanımını, mevcut
   view'ları (`HomeView`, `ReadView`, `StoryView`, `DashboardView`, `AuthorView`) ve
   `SiteHeader` bileşenini oku. Ne var, ne yok RAPORLA. Varsayımla ilerleme.
2. `ReaderLayout` oluştur: üstte ince bir header (logo/site adı, arama girişi,
   giriş/profil), altta `<router-view />`. Sidebar YOK. Mobilde header sadeleşsin.
3. `StudioLayout` oluştur: solda sidebar, üstte header, ortada `<router-view />`.
4. Mevcut `SiteHeader` bileşenini sıfırdan yazma — içeriğini `ReaderLayout`'a taşı,
   Naive UI bileşenleriyle yeniden kur, sonra eskisini sil.
5. **Kalite tabanı** (duyurmadan uygula): 375px'te bozulmuyor, klavye ile
   gezilebiliyor ve odak (`:focus-visible`) görünür, `prefers-reduced-motion`
   dinleniyor.

**Kabul kriteri:** İki layout da render ediliyor, 375px'te taşma yok, sekme tuşuyla
gezerken odak halkası görünüyor.

**DUR, özet ver, onay iste.**

---

> **SIRA DEĞİŞTİ — sidebar (eski ADIM 4) artık router'dan (eski ADIM 3) ÖNCE.**
> Sebep: router adımı navigasyon bağlantılarını sidebar'ın içine koyuyor, sidebar adımı
> ise sidebar'ı baştan kuruyor. Eski sırayla aynı bağlantılar iki kez yazılırdı — önce
> geçici bir sidebar'a, sonra gerçeğine. Sidebar önce kurulunca router adımı hazır bir
> kaba bağlantı koyar.

## ADIM 3 — Sidebar davranışı

**Masaüstü (≥1024px) — ray + üstüne açılma:**

1. Varsayılan **ray modu**: ikon genişliğinde (~56-64px) dar şerit, sabit sol tarafta.
2. Fare rayın üstüne gelince **üstüne açılır** (overlay ~240px) — içeriği **İTMEZ**,
   sayfa daralmaz. Fare çıkınca geri kapanır.
3. Kazara tetiklenmesin: açılma gecikmesi ~150ms, kapanma ~300ms.
4. **Sabitleme (pin) düğmesi** rayın üstünde. Sabitlenince ray açık kalır ve **o zaman
   içeriği iter** — sabitlemenin amacı budur. Tercih `localStorage`'da hatırlansın.
5. Klavye: sekme ile raya odak gelince ray açılsın (hover'a bağlı kalmasın).

**Mobil (<1024px) — drawer:**

6. Hover YOK. Hamburger'a basınca drawer overlay olarak açılsın.
7. Rota değişince otomatik kapansın. Esc kapatsın. Açıkken odak drawer içinde kalsın
   (focus trap).

**Ray içeriği (yukarıdan aşağı):** Dashboard · "Hikayelerim" listesi (son N hikaye,
aktif olan vurgulu) · Ayarlar · *(altta)* tema düğmesi · *(altta)* "Back to site".

8. Hikaye listesi **Pinia store'da tutulur, her rota değişiminde yeniden ÇEKİLMEZ.**
9. `prefers-reduced-motion` açıkken açılma/kapanma animasyonu olmasın, anında olsun.

**Kabul kriteri:** 375px'te hamburger çalışıyor, rota değişince drawer kapanıyor, Esc
kapatıyor; masaüstünde ray hover ile üstüne açılıyor ve içeriği itmiyor, sabitlenince
itiyor, sabitleme tercihi yenilemeden sonra korunuyor.

**DUR, özet ver, onay iste.**

---

## ADIM 4 — Router ve navigasyon

1. Route'ları üç gruba ayır (kabuklu olanları nested route ile layout'a bağla):
   - **Reader kabuğu:** ana sayfa, hikaye tanıtımı (`/s/:id`), yazar profili
   - **Studio kabuğu:** dashboard, hikaye düzenleme, ayarlar, profil
   - **Kabuksuz (doğrudan render):** okuma sayfası (`/s/:id/:index`), giriş, kayıt
2. Studio route'larına **auth guard** ekle: giriş yoksa `/login`'e yönlendir,
   nereden geldiğini `redirect` query'sinde taşı ki giriş sonrası oraya dönsün.
3. Navigasyona gerçek bağlantıları koy (ADIM 3'te kurulan sidebar'a ve Reader
   header'ına). Aktif route vurgulanmalı.
4. Reader ↔ Studio geçişi net olsun: Studio'ya girişte "Studio" / çıkışta
   "Back to site" gibi tek bir belirgin bağlantı. (Not: bu bir **rol** değişimi
   değil, sadece bir sayfa geçişi — arka planda rol/yetki mantığı YOK.)
5. **404 route'u** ekle: tanımsız yol Reader kabuğunda anlamlı bir sayfaya düşsün.

**Kabul kriteri:** Her sayfaya tıklayarak ulaşılıyor. Girişsizken Studio route'u
`/login`'e atıyor, giriş sonrası hedefe dönüyor. Tanımsız URL 404 sayfası gösteriyor.

**DUR, özet ver, onay iste.**

---

## ADIM 5 — Mevcut sayfaları kabuğa oturtma

1. Var olan view'ları uygun layout'un altına taşı. **İç içeriklerini yeniden
   TASARLAMA** — sadece kabuğa oturt, bozulan yerleşimi düzelt.
2. Layout değişikliği yüzünden kırılan CSS varsa düzelt (özellikle `position: fixed`
   ve tam ekran varsayan yerler).
3. Artık kullanılmayan bileşen/stil dosyalarını sil.
4. `npm run build` çalıştır, hatasız bittiğini doğrula.

**Kabul kriteri:** Tüm sayfalar kendi kabuğunda düzgün. Okuma sayfası 375px'te
sidebar'sız ve temiz. `npm run build` hatasız.

**DUR, özet ver.**

---

## Bu işte YAPILMAYACAKLAR

- Yeni özellik ekleme (import, token paneli, chat bot — hepsi ayrı iş)
- Backend değişikliği
- Türkçe metinleri çevirme (ayrı iş — ama yeni Türkçe metin de yazma)
- Görsel kimlik çalışması: özel tipografi seçimi, illüstrasyon, animasyon
- Rol/yetki sistemi (yok, eklenmeyecek)
- i18n altyapısı (arayüz tek dil: İngilizce)

---

## UI metni yazarken

Bu işte az sayıda yeni metin yazacaksın (nav başlıkları, boş durum mesajları, 404).
Kurallar:

- Sistemin nasıl kurulduğunu değil, kullanıcının ne yaptığını adlandır.
- Etken çatı ve sentence case: "Save changes", "SUBMIT" değil.
- Bir eylem akış boyunca aynı adı taşır: "Publish" düğmesi "Published" bildirimi verir.
- Hata mesajı özür dilemez, ne olduğunu ve nasıl düzeltileceğini söyler.
- Boş ekran bir davettir: ne yapılacağını söyler.

---

## Bitirme

Beş adım da onaylandıktan sonra:

- `git commit` ATMA. Kullanıcının kopyalayacağı `git add` + `git commit` komutunu
  metin olarak ver.
- Tek paragraflık Türkçe özet.
- **Ayrı bir bölümde:** bu iş sırasında fark ettiğin ama dokunmadığın sorunları
  listele (backend eksikleri, bozuk görünen ekranlar, ölü kod). Düzeltme, sadece
  raporla — sonraki işlerin listesine gireceler.
