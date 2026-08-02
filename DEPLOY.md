# Deploy Rehberi (Azure VM — Ubuntu 24.04)

Sunucu alındığı gün bu adımlar sırayla uygulanır. Ön koşul: repo GitHub'da
(private olabilir) ve VM şu özelliklerle açılmış olmalı:

- **Ubuntu 24.04 LTS, B2ls_v2 (2 vCPU / 4 GB), Poland Central**, SSH key ile giriş
- NSG gelen kurallar: yalnızca **22, 80, 443**
- Public IP: **Static** (IP'yi not al: `A.B.C.D`)

> **IP yer tutucu.** İlk VM silindi, eski IP artık geçersiz. Bu dosyada geçen
> `A.B.C.D` ve `A-B-C-D.sslip.io` değerleri yeni sunucu açıldığında gerçek statik
> IP ile değiştirilecek (nokta yerine tire: `1.2.3.4` → `1-2-3-4.sslip.io`).

## 0. Deploy ÖNCESİ (sunucuya dokunmadan, lokalde)

- [ ] **OpenAI günlük hard spend cap ($5–10)** — embedding SENİN anahtarınla yapılıyor,
      kaçak maliyet buradan sınırlanır (platform.openai.com → Settings → Limits)
- [ ] **Google Cloud hard spend cap** (OAuth kullanılacaksa)
- [ ] **Migration zinciri BOŞ bir DB'de baştan sona koşuyor.** Azure'daki DB sıfırdan
      kurulacağı için zincir orada ilk kez baştan çalışacak; mevcut DB üzerine artımlı
      uygulamak bunu kanıtlamaz. Boş bir DB'ye `alembic upgrade head` çalıştır.
- [ ] `npm audit` temiz **ve** prod imajında `pip-audit` temiz
      (`docker run --rm --entrypoint sh <imaj> -c "pip install -q pip-audit && pip-audit"`)
- [ ] `.env.prod.example` içinde **üretim LLM anahtarı YOK** (BYOK: base URL + model +
      anahtar üçü de kullanıcının tarayıcısından gelir)
- [ ] Bilgi: zayıf `JWT_SECRET` (32 byte altı/varsayılan), boş `EMBEDDING_API_KEY` ya da
      varsayılan `DATABASE_URL` şifresi ile backend `ENV=production`'da artık **açılmıyor**
      (bkz. `config.py` `validate_production_settings`) — `.env.prod`'u yanlış doldurursan
      bunu smoke test'te değil, ilk `docker compose up` loglarında göreceksin.

## 1. VM temel kurulum

```bash
ssh azureuser@A.B.C.D

sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker   # docker'i sudo'suz kullan
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
```

### 1a. SSH sertleştirme

⚠️ **KRİTİK UYARI:** `sshd` restart edilmeden ÖNCE mevcut SSH oturumunu KAPATMA — ikinci
bir terminalde yeni bir bağlantı aç ve **yeni oturumun açılabildiğini** doğrula. Key'de
bir sorun varsa (yanlış izin, yanlış kullanıcı) ve iki ayarı da kapatırsan VM'e erişim
tamamen kapanır; kurtarma yalnızca Azure seri konsoldan (portal → VM → Serial console)
mümkün olur.

Azure'ın Ubuntu imajında `/etc/ssh/sshd_config` en başta `Include
/etc/ssh/sshd_config.d/*.conf` çağırır ve o dizindeki `50-cloud-init.conf`
`PasswordAuthentication yes` ile gelir; SSH ilk gördüğü direktifi kullandığı
için (ana dosyayı sed'lemek burada işe yaramaz) hem yeni bir drop-in
(`99-hardening.conf`) yazıyoruz **hem de** `50-cloud-init.conf`'taki satırı
yorum satırı yapıyoruz — ikisi de gerekli, tek başına biri yetmez (99, 50'den
alfabetik sonra okunsa da 50'deki satır orada durduğu sürece kazanır).

```bash
# --- İkinci bir terminalde bu oturumu AÇIK TUT, aşağıyı ilkinde çalıştır ---

[ -f /etc/ssh/sshd_config.d/50-cloud-init.conf ] && sudo sed -i \
  -E 's/^[[:space:]]*PasswordAuthentication[[:space:]].*$/#&/' \
  /etc/ssh/sshd_config.d/50-cloud-init.conf

sudo tee /etc/ssh/sshd_config.d/99-hardening.conf > /dev/null <<'EOF'
PasswordAuthentication no
PermitRootLogin no
KbdInteractiveAuthentication no
EOF

sudo systemctl daemon-reload
sudo systemctl restart ssh.socket ssh   # Ubuntu 24.04: birim "ssh", "sshd" degil; socket activation da olabilir

# Efektif config'i dogrula (Include'lari coz, gercek degeri goster — sadece
# dosyayi okumak yeterli degil, sshd -T neyi UYGULADIGINI soyler):
sudo sshd -T | grep -iE "passwordauthentication|permitrootlogin"
# Beklenen: "passwordauthentication no" ve "permitrootlogin no"

# --- Restart'tan SONRA: ikinci terminalden YENİ bir SSH oturumu dene ---
# ssh azureuser@A.B.C.D
# Yeni oturum açılmıyorsa ilk (açık) oturumu KAPATMA, sorunu orada çöz.

sudo apt install -y fail2ban
# jail.conf'ta [sshd] varsayılan olarak KAPALI gelir; jail.local ile açıkça aç
printf '[sshd]\nenabled = true\n' | sudo tee /etc/fail2ban/jail.local
sudo systemctl enable --now fail2ban
sudo systemctl restart fail2ban
sudo fail2ban-client status sshd   # "Status for the jail: sshd" ile dönmeli (hata değil)
# 24.04'te auth loglari systemd journal'a gidebilir (ayri /var/log/auth.log
# olmayabilir): "Currently failed"/"Total banned" sayaci hep 0 gorunuyorsa
# jail.local'a "backend = systemd" ekleyip fail2ban'i yeniden baslat.
```

## 2. Repo ve ortam

```bash
git clone <REPO_URL> app && cd app
cp .env.prod.example .env.prod
nano .env.prod
```

`.env.prod` doldurma notları:

| Değişken | Değer |
|---|---|
| `SITE_ADDRESS` | IP `A.B.C.D` ise `A-B-C-D.sslip.io` (noktalar tire olur) |
| `POSTGRES_PASSWORD` | güçlü şifre: `openssl rand -hex 16` — **aynısını `DATABASE_URL` içine de yaz** |
| `JWT_SECRET` | `openssl rand -hex 32` |
| `EMBEDDING_API_KEY` | **OpenAI** anahtarın — yalnızca embedding için. Billing AÇIK olmalı (free tier prod'da 429 verir). Kullanıcı anahtarı burada ASLA kullanılmaz. |
| `EMBEDDING_PROVIDER` | `openai` (Gemini'den geçildi; sağlayıcı değişimi = tam re-embed) |
| `CORS_ORIGINS` | `https://A-B-C-D.sslip.io` |
| `GOOGLE_OAUTH_CLIENT_ID` | opsiyonel; boşsa Google girişi kapalı (aşağıya bak) |
| `MAX_REQUEST_BODY_SIZE` | Caddy'nin `/api/*` gövde tavanı (varsayılan 1MB); FastAPI'ye ulaşmadan kesilir |

**Üretim LLM anahtarı YOKTUR** — bölüm yazımı BYOK'tur, kullanıcının anahtarı her istekte
header ile gelir ve sunucuda saklanmaz. `.env.prod`'a üretim anahtarı ekleme.

⚠️ `POSTGRES_PASSWORD` yalnızca **volume ilk oluşturulurken** uygulanır. Deploy'dan sonra
değiştirirsen backend "password authentication failed" ile açılamaz; şifreyi değiştirmek
için `ALTER USER` gerekir (volume silmek TÜM VERİYİ siler).

## 3. Başlat

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f    # Caddy sertifika alana kadar izle
```

## 4. Canlı smoke test

`C=docker compose -f docker-compose.prod.yml` kısaltmasıyla.

**Altyapı**

- [ ] Migration boş prod DB'sinde temiz koştu:
      `$C logs backend | grep "Running upgrade"` → 10 satır;
      `$C exec postgres psql -U kurgu_admin -d kurgu_db -tAc "select version_num from alembic_version"`
- [ ] `https://A-B-C-D.sslip.io` **geçerli Let's Encrypt sertifikasıyla** açılıyor
      (`curl -sI https://A-B-C-D.sslip.io | head -1`; tarayıcıda kilit ikonu)
- [ ] Güvenlik başlıkları: `curl -sI https://.../ | grep -iE "strict-transport|x-frame|x-content"`
- [ ] `$C restart` sonrası veri duruyor (volume kalıcı)
- [ ] Tek uvicorn worker: `$C exec backend ps aux | grep -c uvicorn`

**Yazar tarafı (BYOK — kendi anahtarınla)**

- [ ] Kayıt + şifreyle giriş + (varsa) Google girişi
- [ ] 🔑 modalinden base URL + model + anahtar gir → bölüm üretimi → **SSE canlı akıyor**
      (Caddy `flush_interval -1`; akmıyorsa yanıt tamponlanıyordur)
- [ ] Üretim sürerken eş zamanlı ikinci üretim isteği → **409**
- [ ] **Üretim sürerken başka bir istek (örn. ana sayfa) BLOKE OLMUYOR** — rollup'ın
      "idle in transaction" düzeltmesi: LLM çağrısı boyunca DB transaction'ı açık tutulmamalı.
      Kontrol: `$C exec postgres psql -U kurgu_admin -d kurgu_db -c "select pid, state, age(clock_timestamp(), xact_start), left(query,60) from pg_stat_activity where state='idle in transaction'"`
      → üretim sırasında bile **boş** olmalı
- [ ] Bölüm düzenleme + özet yenileme + hikaye içi arama çalışıyor

**Okuyucu tarafı (Faz 2)**

- [ ] Stüdyoda **Yayımlama** panelinden hikayeyi `public` yap (kural onayı isteniyor)
- [ ] **public + yetişkin işareti** kombinasyonu reddediliyor (400)
- [ ] Ana sayfa (`/`) yayımlanan hikayeyi listeliyor; **arama** ve **etiket filtresi** buluyor
- [ ] Okuma sayfası (`/s/{id}/{index}`) **girişsiz** açılıyor; önceki/sonraki, font, tema çalışıyor
- [ ] Beğeni: girişsizken `/login`'e yönlendiriyor; girişliyken sayaç artıyor, geri alınabiliyor
- [ ] Yorum: girişsiz okunuyor, yazmak giriş istiyor; yazar rozeti + sabitleme çalışıyor
- [ ] **Private hikaye sızmıyor:** private bir hikayenin id'siyle
      `/api/public/stories/{id}` ve `.../chapters/1` → **404** (girişsiz, başka kullanıcı, SAHİBİ)
- [ ] `unlisted` hikaye id ile okunuyor ama ana sayfada/aramada **çıkmıyor**
- [ ] **Derin rota yenileme:** `https://.../s/1/1` adresini doğrudan aç → 404 değil,
      sayfa geliyor (Caddy `try_files` SPA fallback)
- [ ] Mobil: telefondan okuma sayfası düzgün (375px)

**Sır sızıntısı**

- [ ] `$C logs | grep -iE "sk-[a-zA-Z0-9]{20}|Bearer [A-Za-z0-9._-]{20}|\?token="` → **boş**
- [ ] `$C logs | grep -F "$(grep ^JWT_SECRET .env.prod | cut -d= -f2)"` → **boş**
- [ ] `$C logs | grep -F "$(grep ^EMBEDDING_API_KEY .env.prod | cut -d= -f2)"` → **boş**

## 5. Yedekleme (elle — cron Faz 4)

Bu, canlıya çıktığın gün en az bir kez elle çalıştırılır. Gece cron + haftalık
Azure snapshot Faz 4'te otomatikleşir (bkz. CLAUDE.md "FAZ 4 — Ops"); bu bölüm
onun yerine geçmez, ondan önceki elle güvenceyi sağlar.

```bash
# --- VM üzerinde: dump al ---
mkdir -p ~/backups
STAMP=$(date +%Y%m%d-%H%M%S)
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U kurgu_admin --clean --if-exists kurgu_db | gzip > ~/backups/kurgu_db-$STAMP.sql.gz
ls -lh ~/backups/
```

`$STAMP` yalnızca VM'deki oturumda tanımlı — kendi makinende boş genişler,
bu yüzden indirirken dosya adını `ls` çıktısından elle kopyala:

```bash
# --- Kendi makinende: dump'ı indir (dosya adını yukarıdaki ls çıktısından yapıştır) ---
scp azureuser@A.B.C.D:~/backups/kurgu_db-20260730-120000.sql.gz .
```

**Geri yükleme (bunu ASLA test etmeden bırakma — hiç geri yüklenmemiş bir yedek,
alınmamış bir yedek kadar tehlikelidir):**

```bash
# VM üzerinde, mevcut veriyi silip dump'ı geri yükler; --clean --if-exists dump'a
# DROP ifadeleri gomdugu ve ON_ERROR_STOP=1 ilk hatada durdurdugu icin -- bunlar
# olmadan psql var olan tablolara carpar, "already exists" hatalariyla YARIM doner
# ve yine de basarili gibi cikis kodu verebilir (test ettigini sanirsin, aslinda
# yarim kalmis olur) -- burada gercekten mevcut veriyi silip TAM geri yukler
gunzip -c ~/backups/kurgu_db-20260730-120000.sql.gz | \
  docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -v ON_ERROR_STOP=1 -U kurgu_admin -d kurgu_db
```

## 6. Google OAuth (istenildiği zaman, deploy'dan bağımsız)

1. https://console.cloud.google.com/apis/credentials → **Create Credentials → OAuth client ID → Web application**
2. "Authorized JavaScript origins": `https://A-B-C-D.sslip.io`
3. Client ID'yi `.env.prod`'daki `GOOGLE_OAUTH_CLIENT_ID`'ye yaz
4. `docker compose -f docker-compose.prod.yml up -d --build backend` — buton otomatik görünür

## 7. Güncelleme (sonraki deploylar)

```bash
cd app && git pull && docker compose -f docker-compose.prod.yml up -d --build
```
