/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  // Okuma sayfasinda tema ELLE secilebilmeli (isletim sisteminin tercihi degil, okurun
  // tercihi belirler) -> 'media' degil 'class'. Studio gorunumleri `dark:` varyanti
  // kullanmiyor, renkleri sabit; bu degisiklik onlari etkilemez.
  darkMode: 'class',
  theme: {
    extend: {},
  },
  plugins: [require('@tailwindcss/typography')],
}
