<script setup>
import { computed, ref, watch } from "vue"


const props = defineProps({
  answer: { type: Object, required: true },
  question: { type: Object, required: true },
  trend: { type: Array, default: () => [] },
  transcriptSaving: { type: Boolean, default: false },
  transcriptUpdateMessage: { type: String, default: "" },
})

const emit = defineEmits(["practice-again", "update-transcript"])

const report = computed(() => props.answer.report)
const transcriptDraft = ref("")
watch(
  [() => props.answer.id, () => props.answer.transcript],
  () => {
    transcriptDraft.value = props.answer.transcript || ""
  },
  { immediate: true },
)
const transcriptChanged = computed(
  () => transcriptDraft.value.trim() !== (props.answer.transcript || "").trim(),
)
const canRestoreAsr = computed(
  () =>
    Boolean(props.answer.asr_transcript) &&
    props.answer.asr_transcript !== props.answer.transcript,
)

function saveTranscript() {
  const value = transcriptDraft.value.trim()
  if (value && transcriptChanged.value) emit("update-transcript", value)
}

function restoreAsrTranscript() {
  if (!props.answer.asr_transcript) return
  transcriptDraft.value = props.answer.asr_transcript
  emit("update-transcript", props.answer.asr_transcript)
}
const radarAxes = [
  { key: "题目相关", label: "题目相关", x: 100, y: 12 },
  { key: "结构完整", label: "结构完整", x: 188, y: 100 },
  { key: "事实成果", label: "事实成果", x: 100, y: 188 },
  { key: "表达流畅", label: "表达流畅", x: 12, y: 100 },
]

const radarPoints = computed(() =>
  radarAxes
    .map((axis) => {
      const value = Number(report.value?.radar?.[axis.key] || 0) / 100
      const x = 100 + (axis.x - 100) * value
      const y = 100 + (axis.y - 100) * value
      return `${x},${y}`
    })
    .join(" "),
)

const orderedTrend = computed(() =>
  [...props.trend].reverse().slice(-8),
)

function pauseStyle(pause) {
  const totalMs = Math.max(1, Number(props.answer.metrics?.total_duration_sec || 1) * 1000)
  const left = Math.min(100, Math.max(0, (pause.start_ms / totalMs) * 100))
  const width = Math.max(0.8, Math.min(100 - left, (pause.duration_ms / totalMs) * 100))
  return { left: `${left}%`, width: `${width}%` }
}

function formatDate(value) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))
}
</script>

<template>
  <div v-if="report" class="report-panel">
    <div class="report-hero">
      <div class="score-ring">
        <strong>{{ report.scores.total }}</strong>
        <span>规则基线分</span>
      </div>
      <div class="report-summary">
        <p class="eyebrow dark">ANALYSIS REPORT</p>
        <h3>{{ report.summary }}</h3>
        <p>{{ report.disclaimer }}</p>
      </div>
      <button type="button" class="outline-action" @click="$emit('practice-again')">
        再次练习本题
      </button>
    </div>

    <div class="report-overview-grid">
      <article class="radar-card">
        <div class="panel-title">
          <div>
            <span>能力雷达</span>
            <strong>四维原始证据映射</strong>
          </div>
          <small>{{ report.engine_version }}</small>
        </div>
        <div class="radar-wrap">
          <svg viewBox="0 0 200 200" role="img" aria-label="回答能力四维雷达图">
            <polygon class="radar-grid outer" points="100,12 188,100 100,188 12,100" />
            <polygon class="radar-grid" points="100,56 144,100 100,144 56,100" />
            <line x1="100" y1="12" x2="100" y2="188" />
            <line x1="12" y1="100" x2="188" y2="100" />
            <polygon class="radar-value" :points="radarPoints" />
          </svg>
          <span class="radar-label top">题目相关 {{ report.radar['题目相关'] }}</span>
          <span class="radar-label right">结构 {{ report.radar['结构完整'] }}</span>
          <span class="radar-label bottom">事实成果 {{ report.radar['事实成果'] }}</span>
          <span class="radar-label left">表达 {{ report.radar['表达流畅'] }}</span>
        </div>
      </article>

      <article class="score-breakdown">
        <div class="panel-title">
          <div>
            <span>分数拆解</span>
            <strong>每一分都有依据</strong>
          </div>
        </div>
        <div class="score-bars">
          <div v-for="(component, key) in report.scores.components" :key="key">
            <div class="score-bar-label">
              <span>{{ {
                relevance: '题目相关', structure: '结构完整', evidence: '事实成果',
                pace: '表达语速', pause: '停顿表现', filler_duration: '语气词与时长'
              }[key] }}</span>
              <strong>{{ component.score }}/{{ component.max_score }}</strong>
            </div>
            <div class="score-track">
              <span :style="{ width: `${component.score / component.max_score * 100}%` }"></span>
            </div>
            <small>{{ component.basis }}</small>
          </div>
        </div>
      </article>
    </div>

    <div class="report-section">
      <div class="panel-title">
        <div>
          <span>回答原文</span>
          <strong>内容分析以当前转写为依据</strong>
        </div>
      </div>
      <textarea
        v-model="transcriptDraft"
        class="report-transcript-editor"
        rows="5"
        maxlength="10000"
        aria-label="可修正的回答转写"
      ></textarea>
      <div class="transcript-actions">
        <span>
          {{ answer.transcript_source === "user_corrected" ? "当前为人工修正文本" : "当前为模型原始转写" }}
        </span>
        <div>
          <button
            v-if="canRestoreAsr"
            type="button"
            class="outline-action"
            :disabled="transcriptSaving"
            @click="restoreAsrTranscript"
          >
            恢复原始转写
          </button>
          <button
            type="button"
            class="primary-action transcript-save"
            :disabled="transcriptSaving || !transcriptChanged || !transcriptDraft.trim()"
            @click="saveTranscript"
          >
            {{ transcriptSaving ? "重新生成中…" : "保存并重新评分" }}
          </button>
        </div>
      </div>
      <p v-if="transcriptUpdateMessage" class="metric-note transcript-message">
        {{ transcriptUpdateMessage }}
      </p>
    </div>

    <div class="report-detail-grid">
      <article class="report-section">
        <div class="panel-title">
          <div>
            <span>题目要点</span>
            <strong>
              命中 {{ report.keyword_coverage.hit_count }}/{{ report.keyword_coverage.total }}
            </strong>
          </div>
        </div>
        <div class="evidence-list">
          <div
            v-for="item in report.keyword_coverage.items"
            :key="item.point"
            class="evidence-item"
            :class="{ hit: item.hit }"
          >
            <span>{{ item.hit ? "✓" : "○" }}</span>
            <div>
              <strong>{{ item.point }}</strong>
              <small>{{ item.evidence || "当前转写中未检测到明确证据" }}</small>
            </div>
          </div>
        </div>
      </article>

      <article class="report-section">
        <div class="panel-title">
          <div>
            <span>{{ report.structure_analysis.label }}</span>
            <strong>
              完成 {{ report.structure_analysis.present_count }}/{{ report.structure_analysis.total }}
            </strong>
          </div>
        </div>
        <div class="structure-grid">
          <div
            v-for="item in report.structure_analysis.dimensions"
            :key="item.key"
            :class="{ present: item.present }"
          >
            <span>{{ item.key }}</span>
            <strong>{{ item.label }}</strong>
            <small>{{ item.evidence || "待补充" }}</small>
          </div>
        </div>
        <div class="evidence-list compact">
          <div
            v-for="item in report.evidence_analysis.dimensions"
            :key="item.key"
            class="evidence-item"
            :class="{ hit: item.present }"
          >
            <span>{{ item.present ? "✓" : "○" }}</span>
            <div>
              <strong>{{ item.label }}</strong>
              <small>{{ item.evidence || "当前转写中未检测到明确证据" }}</small>
            </div>
          </div>
        </div>
      </article>
    </div>

    <div class="report-section">
      <div class="panel-title">
        <div>
          <span>表达节奏</span>
          <strong>语音指标与停顿时间轴</strong>
        </div>
        <small>总时长 {{ answer.metrics.total_duration_sec }} 秒</small>
      </div>
      <div class="metric-grid report-metrics">
        <article>
          <span>有效语速</span>
          <strong>{{ answer.metrics.speaking_rate_per_min }}</strong>
          <small>表达单位/分钟</small>
        </article>
        <article>
          <span>明显停顿</span>
          <strong>{{ answer.metrics.pause_count }}</strong>
          <small>≥ 0.5 秒</small>
        </article>
        <article>
          <span>最长停顿</span>
          <strong>{{ answer.metrics.longest_pause_sec }}</strong>
          <small>秒</small>
        </article>
        <article>
          <span>语气词</span>
          <strong>{{ answer.metrics.filler_count }}</strong>
          <small>仅作客观计数</small>
        </article>
      </div>
      <div class="pause-timeline" aria-label="停顿时间轴">
        <div class="timeline-track">
          <span
            v-for="(pause, index) in report.pause_timeline"
            :key="index"
            class="pause-mark"
            :class="pause.level"
            :style="pauseStyle(pause)"
            :title="`${(pause.start_ms / 1000).toFixed(1)}–${(pause.end_ms / 1000).toFixed(1)} 秒`"
          ></span>
        </div>
        <div class="timeline-labels"><span>0 秒</span><span>{{ answer.metrics.total_duration_sec }} 秒</span></div>
      </div>
      <p class="metric-note">{{ answer.metrics.metric_note }}</p>
    </div>

    <div class="report-detail-grid feedback-grid">
      <article class="report-section">
        <div class="panel-title"><div><span>做得不错</span><strong>已检测到的证据</strong></div></div>
        <div class="feedback-list strengths">
          <div v-for="item in report.strengths" :key="item.title">
            <strong>{{ item.title }}</strong>
            <p>{{ item.evidence }}</p>
          </div>
        </div>
      </article>
      <article class="report-section">
        <div class="panel-title"><div><span>优先改进</span><strong>下一次只关注三件事</strong></div></div>
        <div class="feedback-list suggestions">
          <div v-for="item in report.suggestions" :key="item.priority">
            <span>0{{ item.priority }}</span>
            <div><strong>{{ item.title }}</strong><p>{{ item.reason }}</p><small>{{ item.action }}</small></div>
          </div>
        </div>
      </article>
    </div>

    <div v-if="orderedTrend.length" class="report-section trend-section">
      <div class="panel-title">
        <div><span>同题趋势</span><strong>只比较你在本机上的历次练习</strong></div>
        <small>{{ orderedTrend.length }} 次</small>
      </div>
      <div class="trend-chart">
        <div v-for="item in orderedTrend" :key="item.answer_id" class="trend-column">
          <strong>{{ item.scores.total }}</strong>
          <div><span :style="{ height: `${item.scores.total}%` }"></span></div>
          <small>{{ formatDate(item.created_at) }}</small>
        </div>
      </div>
      <p class="metric-note">趋势分数仅用于观察个人变化；规则调整后，不同规则版本的分数不应直接比较。</p>
    </div>
  </div>
</template>
