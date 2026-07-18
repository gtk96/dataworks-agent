<template>
  <div class="message-bubble" :class="[role, { streaming }]">
    <div class="avatar">
      <div v-if="role === 'user'" class="avatar-user">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
          <circle cx="12" cy="7" r="4"/>
        </svg>
      </div>
      <div v-else class="avatar-agent">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2L2 7l10 5 10-5-10-5z"/>
          <path d="M2 17l10 5 10-5"/>
          <path d="M2 12l10 5 10-5"/>
        </svg>
      </div>
    </div>
    <div class="bubble-wrapper">
      <div class="bubble" v-html="renderedContent" />
      <section
        v-if="interaction"
        class="interaction-card"
        :class="{ 'interaction-card--inactive': !interactionActionable }"
        data-interaction-card
      >
        <header class="interaction-header">
          <div>
            <span class="interaction-kicker">CONVERSATION CHECKPOINT</span>
            <strong>{{ interaction.prompt }}</strong>
          </div>
          <span class="interaction-status">{{ interactionStatusLabel }}</span>
        </header>
        <div v-if="interaction.options.length" class="interaction-options">
          <button
            v-for="option in interaction.options"
            :key="option.id"
            class="interaction-option"
            :class="{ selected: selectedId === option.id }"
            type="button"
            :disabled="!interactionActionable || Boolean(selectedId)"
            :data-interaction-option="option.id"
            @click="onInteractionOption(option)"
          >
            <span class="interaction-option__main">
              <span>{{ option.label }}</span>
              <small v-if="option.description">{{ option.description }}</small>
            </span>
            <span v-if="option.layer" class="chip-layer">{{ option.layer.toUpperCase() }}</span>
            <span class="interaction-option__arrow">→</span>
          </button>
        </div>
        <div v-if="interaction.allow_custom_input && interactionActionable" class="interaction-custom">
          <input
            v-model="interactionCustomText"
            :placeholder="interaction.custom_input_placeholder || '输入自定义回答'"
            :disabled="!interactionActionable || Boolean(selectedId)"
            data-interaction-custom
            @keydown.enter.exact.prevent="onInteractionCustomSubmit"
          />
          <button
            type="button"
            :disabled="!interactionActionable || Boolean(selectedId) || !interactionCustomText.trim()"
            data-interaction-submit
            @click="onInteractionCustomSubmit"
          >
            继续
          </button>
        </div>
      </section>
      <!-- Legacy option chips remain available for old history rows. -->
      <div v-if="!interaction && optionChips.length" class="option-chips">
        <div
          v-for="chip in optionChips"
          :key="chip.id"
          class="option-chip"
          :class="['option-chip--' + chip.type, { selected: selectedId === chip.id }]"
          @click="onChipClick(chip)"
        >
          <div v-if="chip.type === 'pick_table'" class="chip-main">
            <div class="chip-label">
              <span class="chip-table">{{ chip.label }}</span>
              <span v-if="chip.layer" class="chip-layer">{{ chip.layer.toUpperCase() }}</span>
            </div>
            <div v-if="chip.subtitle" class="chip-subtitle">{{ chip.subtitle }}</div>
          </div>
          <div v-else class="chip-main chip-main--custom">
            <div class="chip-label">
              <span class="chip-table">{{ chip.label }}</span>
            </div>
            <input
              v-if="chip.type === 'free_text' && customOpen"
              v-model="customText"
              class="chip-input"
              :placeholder="chip.placeholder || 'project.table 或 SELECT ...'"
              @keydown.enter.exact.prevent="onCustomSubmit"
              @click.stop
            />
            <button
              v-if="chip.type === 'free_text' && customOpen"
              class="chip-submit"
              :disabled="!customText.trim()"
              @click.stop="onCustomSubmit"
            >
              提交
            </button>
          </div>
        </div>
      </div>
      <div v-if="streaming" class="streaming-indicator">
        <span class="dot"></span>
        <span class="dot"></span>
        <span class="dot"></span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { renderMarkdown } from '@/utils/markdown-render'
import type { AgentInteraction, AgentInteractionOption, InteractionAnswer } from './chatInteraction'

export interface OptionChip {
  id: string
  type: 'pick_table' | 'free_text'
  label: string
  subtitle?: string
  layer?: string
  value?: string
  placeholder?: string
}

interface Props {
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  optionChips?: OptionChip[]
  interaction?: AgentInteraction
  activeInteractionId?: string | null
}

const props = withDefaults(defineProps<Props>(), {
  streaming: false,
  optionChips: () => [],
  interaction: undefined,
  activeInteractionId: null,
})

const emit = defineEmits<{
  pick: [value: string]
  'answer-interaction': [payload: { message: string; answer: InteractionAnswer }]
}>()

const selectedId = ref<string | null>(null)
const customOpen = ref(true)
const customText = ref('')
const interactionCustomText = ref('')

const interactionActionable = computed(() => props.interaction?.status === 'pending')

const interactionStatusLabel = computed(() => {
  if (!props.interaction) return ''
  if (interactionActionable.value) return '等待回答'
  if (props.interaction.status === 'answered') return '已回答'
  return '已失效'
})

watch(
  () => [props.interaction?.interaction_id, props.interaction?.status, props.activeInteractionId],
  () => {
    if (interactionActionable.value) {
      selectedId.value = null
      interactionCustomText.value = ''
    }
  },
)

const renderedContent = computed(() => {
  if (props.role === 'user') {
    const escaped = props.content
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br>')
    return escaped
  }
  return renderMarkdown(props.content).html
})

function emitInteraction(message: string, answer: InteractionAnswer) {
  if (!interactionActionable.value || selectedId.value) return
  selectedId.value = answer.option_id || 'custom'
  emit('answer-interaction', { message, answer })
}

function onInteractionOption(option: AgentInteractionOption) {
  if (!props.interaction) return
  emitInteraction(option.label, {
    interaction_id: props.interaction.interaction_id,
    option_id: option.id,
    state_version: props.interaction.state_version,
  })
}

function onInteractionCustomSubmit() {
  if (!props.interaction) return
  const value = interactionCustomText.value.trim()
  if (!value) return
  emitInteraction(value, {
    interaction_id: props.interaction.interaction_id,
    custom_text: value,
    state_version: props.interaction.state_version,
  })
}

function onChipClick(chip: OptionChip) {
  if (selectedId.value) {
    return // already locked to a choice
  }
  if (chip.type === 'free_text') {
    if (!customOpen.value) {
      customOpen.value = true
    }
    return
  }
  selectedId.value = chip.id
  emit('pick', String(chip.value || chip.label || ''))
}

function onCustomSubmit() {
  const value = customText.value.trim()
  if (!value) {
    return
  }
  selectedId.value = 'opt_custom'
  emit('pick', value)
}
</script>

<style scoped>
.message-bubble {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  align-items: flex-start;
}

.message-bubble.user {
  flex-direction: row-reverse;
}

.avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: grid;
  place-items: center;
}

.avatar-user {
  background: #1E293B;
  color: #94A3B8;
}

.avatar-user svg {
  width: 18px;
  height: 18px;
}

.avatar-agent {
  background: linear-gradient(135deg, #6366F1, #8B5CF6);
  color: #fff;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.avatar-agent svg {
  width: 18px;
  height: 18px;
}

.bubble-wrapper {
  max-width: min(75%, 720px);
  min-width: 0;
}

.bubble {
  padding: 12px 16px;
  border-radius: 16px;
  line-height: 1.65;
  font-size: 14px;
  word-break: break-word;
}

.message-bubble.user .bubble {
  background: linear-gradient(135deg, #6366F1, #4F46E5);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.message-bubble.assistant .bubble {
  background: #F1F5F9;
  color: #1E293B;
  border: 1px solid #E2E8F0;
  border-bottom-left-radius: 4px;
}

/* Markdown styles inside assistant bubbles */
.bubble :deep(h1), .bubble :deep(h2), .bubble :deep(h3) {
  margin: 12px 0 6px;
  font-weight: 600;
}

.bubble :deep(h1) { font-size: 1.3em; }
.bubble :deep(h2) { font-size: 1.15em; }
.bubble :deep(h3) { font-size: 1.05em; }

.bubble :deep(p) {
  margin: 0 0 8px;
}

.bubble :deep(p:last-child) {
  margin-bottom: 0;
}

.bubble :deep(code) {
  background: rgba(99, 102, 241, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.88em;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  color: #4F46E5;
}

.message-bubble.user :deep(code) {
  background: rgba(255, 255, 255, 0.18);
  color: #fff;
}

.bubble :deep(pre) {
  margin: 10px 0;
  padding: 12px 14px;
  background: #0F172A;
  border-radius: 10px;
  overflow-x: auto;
  border: 1px solid #1E293B;
}

.bubble :deep(pre code) {
  background: none;
  padding: 0;
  color: #E2E8F0;
  font-size: 0.85em;
  line-height: 1.5;
}

.bubble :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
  font-size: 13px;
}

.bubble :deep(th), .bubble :deep(td) {
  padding: 8px 12px;
  border: 1px solid #CBD5E1;
  text-align: left;
}

.bubble :deep(th) {
  background: #F8FAFC;
  font-weight: 600;
}

.bubble :deep(ul), .bubble :deep(ol) {
  margin: 6px 0;
  padding-left: 20px;
}

.bubble :deep(li) {
  margin-bottom: 4px;
}

.bubble :deep(blockquote) {
  margin: 8px 0;
  padding: 8px 14px;
  border-left: 3px solid #6366F1;
  background: rgba(99, 102, 241, 0.05);
  color: #475569;
}

.bubble :deep(a) {
  color: #6366F1;
  text-decoration: underline;
}

.message-bubble.user :deep(a) {
  color: #C7D2FE;
}

/* Structured conversation checkpoint */
.interaction-card {
  margin-top: 12px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--color-accent-blue) 34%, var(--color-border-primary));
  border-radius: 12px;
  background: linear-gradient(145deg, color-mix(in srgb, var(--color-accent-blue) 7%, var(--color-bg-card)), var(--color-bg-card));
}
.interaction-card--inactive { opacity: 0.68; }
.interaction-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--color-border-primary);
}
.interaction-header > div { display: grid; gap: 3px; }
.interaction-header strong { color: var(--color-text-primary); font-size: 13px; line-height: 1.45; }
.interaction-kicker { color: var(--color-accent-blue); font-size: 9px; font-weight: 800; letter-spacing: 0.11em; }
.interaction-status {
  flex-shrink: 0;
  padding: 3px 7px;
  border-radius: 999px;
  background: var(--color-bg-tertiary);
  color: var(--color-text-tertiary);
  font-size: 10px;
  font-weight: 700;
}
.interaction-options { display: grid; gap: 6px; padding: 10px; }
.interaction-option {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 10px;
  border: 1px solid var(--color-border-primary);
  border-radius: 9px;
  background: var(--color-bg-card);
  color: var(--color-text-primary);
  text-align: left;
  cursor: pointer;
  transition: border-color .16s ease, transform .16s ease, background .16s ease;
}
.interaction-option:hover:not(:disabled) { transform: translateX(2px); border-color: var(--color-accent-blue); background: var(--color-bg-hover); }
.interaction-option:disabled { cursor: default; }
.interaction-option.selected { border-color: var(--color-accent-blue); }
.interaction-option__main { display: grid; gap: 2px; min-width: 0; flex: 1; }
.interaction-option__main > span { font-size: 12px; font-weight: 700; overflow-wrap: anywhere; }
.interaction-option__main small { color: var(--color-text-tertiary); font-size: 10px; }
.interaction-option__arrow { color: var(--color-accent-blue); font-weight: 800; }
.interaction-custom { display: flex; gap: 8px; padding: 10px; border-top: 1px solid var(--color-border-primary); }
.interaction-custom input {
  min-width: 0;
  flex: 1;
  padding: 8px 10px;
  border: 1px solid var(--color-border-primary);
  border-radius: 8px;
  background: var(--color-bg-primary);
  color: var(--color-text-primary);
  outline: none;
}
.interaction-custom input:focus { border-color: var(--color-accent-blue); }
.interaction-custom button {
  padding: 0 13px;
  border: 0;
  border-radius: 8px;
  background: var(--color-accent-blue);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.interaction-custom button:disabled { opacity: .45; cursor: default; }

/* Option chips */
.option-chips {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
  max-width: min(75%, 720px);
}

.option-chip {
  border: 1px solid #E2E8F0;
  border-radius: 12px;
  padding: 10px 14px;
  background: #fff;
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 13px;
  color: #1E293B;
}

.option-chip:hover {
  border-color: #6366F1;
  background: rgba(99, 102, 241, 0.04);
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.08);
}

.option-chip.selected {
  border-color: #6366F1;
  background: rgba(99, 102, 241, 0.08);
  cursor: default;
}

.option-chip--free_text {
  background: #F8FAFC;
  border-style: dashed;
}

.chip-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.chip-main--custom {
  gap: 8px;
}

.chip-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}

.chip-table {
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12.5px;
  color: #4F46E5;
  word-break: break-all;
}

.chip-layer {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 6px;
  background: rgba(99, 102, 241, 0.12);
  color: #4F46E5;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.chip-subtitle {
  font-size: 12px;
  color: #64748B;
  line-height: 1.45;
}

.chip-input {
  flex: 1;
  border: 1px solid #CBD5E1;
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 13px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  background: #fff;
  color: #1E293B;
  outline: none;
  transition: border-color 0.15s;
}

.chip-input:focus {
  border-color: #6366F1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.chip-submit {
  border: none;
  background: #6366F1;
  color: #fff;
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.chip-submit:hover:not(:disabled) {
  background: #4F46E5;
}

.chip-submit:disabled {
  background: #CBD5E1;
  cursor: not-allowed;
}

/* Streaming indicator */
.streaming-indicator {
  display: flex;
  gap: 4px;
  padding: 4px 0 0 4px;
}

.streaming-indicator .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #6366F1;
  animation: pulse 1.2s ease-in-out infinite;
}

.streaming-indicator .dot:nth-child(2) {
  animation-delay: 0.2s;
}

.streaming-indicator .dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes pulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}

/* Empty message */
.empty-message {
  height: 2px;
}
</style>
