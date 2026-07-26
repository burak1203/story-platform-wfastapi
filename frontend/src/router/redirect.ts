const DEFAULT_AFTER_LOGIN = '/dashboard'

/**
 * `?redirect=` degerini guvenli bir UYGULAMA ICI yola indirger.
 *
 * GUVENLIK — acik yonlendirme (open redirect): bu deger URL'den gelir, yani saldirganin
 * kontrolundedir. Dogrudan kullanilirsa "giris yap" baglantisi kurbani giristen hemen
 * sonra sahte bir siteye atabilir. Bu yuzden YALNIZCA tek "/" ile baslayan goreli yollar
 * kabul edilir:
 *   "//kotu.site" ve "/\kotu.site" -> tarayici bunlari MUTLAK adres sayar, reddedilir
 *   "https://kotu.site"            -> reddedilir
 * Ayrica dizi gelen (?redirect=a&redirect=b) hali de reddedilir.
 */
export function safeRedirect(value: unknown): string {
  if (typeof value !== 'string') return DEFAULT_AFTER_LOGIN
  if (!value.startsWith('/')) return DEFAULT_AFTER_LOGIN
  if (value.startsWith('//') || value.startsWith('/\\')) return DEFAULT_AFTER_LOGIN
  return value
}
