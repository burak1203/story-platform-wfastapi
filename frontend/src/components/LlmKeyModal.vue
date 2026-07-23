<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useLlmKeyStore, PROVIDERS, presetOf } from '@/stores/llmKeyStore'

const store = useLlmKeyStore()

const provider = ref(store.provider)
const baseUrl = ref(store.baseUrl)
const model = ref(store.model)
const key = ref(store.key)
const saved = ref(false)

const preset = computed(() => presetOf(provider.value))
const isCustom = computed(() => provider.value === 'custom')

// Modal her açıldığında formu kayıtlı ayarlarla eşitle
watch(
  () => store.isModalOpen,
  (open) => {
    if (open) {
      provider.value = store.provider
      baseUrl.value = store.baseUrl
      model.value = store.model
      key.value = store.key
      saved.value = false
    }
  },
)

// Sağlayıcı değişince base URL (ve boşsa model) otomatik dolar; custom'da elle bırakılır
const onProviderChange = () => {
  const p = presetOf(provider.value)
  if (p.id !== 'custom') {
    baseUrl.value = p.baseUrl
    if (!model.value || PROVIDERS.some((x) => x.model === model.value)) {
      model.value = p.model
    }
  }
  store.validationResult = null
}

const config = () => ({
  provider: provider.value,
  baseUrl: baseUrl.value,
  model: model.value,
  key: key.value,
})

const complete = computed(
  () => !!(provider.value && baseUrl.value.trim() && model.value.trim() && key.value.trim()),
)

const handleValidate = () => {
  if (!complete.value) return
  store.validate(config())
}

const handleSave = () => {
  store.saveConfig(config())
  saved.value = true
  setTimeout(() => store.closeModal(), 600)
}
</script>

<template>
  <div
    v-if="store.isModalOpen"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
    @click.self="store.closeModal()"
  >
    <div class="w-full max-w-md bg-slate-800 border border-slate-600 rounded-xl p-6 text-gray-200">
      <div class="flex justify-between items-center mb-4">
        <h2 class="text-lg font-bold text-amber-500">LLM Provider Settings</h2>
        <button @click="store.closeModal()" class="text-slate-400 hover:text-slate-200 text-xl leading-none">
          &times;
        </button>
      </div>

      <p class="text-sm text-slate-400 mb-4">
        Chapters are generated with your own provider key. Pick a provider, or use “Custom” for a
        manual base URL.
      </p>

      <label class="block text-xs font-medium text-slate-400 mb-1">Provider</label>
      <select
        v-model="provider"
        @change="onProviderChange"
        class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-amber-500 mb-3"
      >
        <option v-for="p in PROVIDERS" :key="p.id" :value="p.id">{{ p.label }}</option>
      </select>

      <label class="block text-xs font-medium text-slate-400 mb-1">Base URL</label>
      <input
        v-model="baseUrl"
        type="text"
        :readonly="!isCustom"
        placeholder="https://..."
        class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-amber-500 mb-3"
        :class="{ 'opacity-70': !isCustom }"
      />

      <label class="block text-xs font-medium text-slate-400 mb-1">Model</label>
      <input
        v-model="model"
        type="text"
        placeholder="model name"
        class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-amber-500 mb-3"
      />

      <label class="block text-xs font-medium text-slate-400 mb-1">
        API Key
        <a
          v-if="preset.keyUrl"
          :href="preset.keyUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="text-amber-500 hover:underline ml-1"
        >(get key)</a>
      </label>
      <input
        v-model="key"
        type="password"
        :placeholder="preset.keyHint || 'API key'"
        autocomplete="off"
        class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-amber-500 mb-3"
      />

      <div class="flex items-center gap-2 mb-4">
        <button
          @click="handleValidate"
          :disabled="store.isValidating || !complete"
          class="bg-slate-700 hover:bg-slate-600 px-4 py-2 rounded text-sm transition-colors disabled:opacity-50"
        >
          {{ store.isValidating ? 'Validating...' : 'Validate' }}
        </button>
        <span v-if="store.validationResult === true" class="text-emerald-400 text-sm">✓ Working</span>
        <span v-else-if="store.validationResult === false" class="text-red-400 text-sm">✗ Not working</span>
      </div>

      <button
        @click="handleSave"
        :disabled="!complete"
        class="w-full bg-amber-600 hover:bg-amber-500 text-slate-900 font-bold py-2 rounded transition-colors disabled:opacity-50"
      >
        {{ saved ? '✓ Saved' : 'Save' }}
      </button>

      <p class="text-xs text-slate-500 mt-4">
        Your settings are stored only in your browser; never saved or logged on the server.
      </p>
    </div>
  </div>
</template>
