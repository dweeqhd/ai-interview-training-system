<script setup>
defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: "" },
})

defineEmits(["open", "refresh", "back"])

function formatDate(value) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))
}
</script>

<template>
  <section class="history-shell">
    <div class="history-heading">
      <div>
        <p class="eyebrow dark">TRAINING HISTORY</p>
        <h2>每一次练习，都留下可复盘的证据</h2>
        <p>这里只显示当前电脑本地数据库中已完成的分析，不包含账号同步。</p>
      </div>
      <div class="history-actions">
        <button type="button" class="outline-action" @click="$emit('refresh')">刷新</button>
        <button type="button" class="primary-action" @click="$emit('back')">返回题库</button>
      </div>
    </div>

    <div v-if="loading" class="state-panel">正在读取本机训练记录…</div>
    <div v-else-if="error" class="state-panel error">{{ error }}</div>
    <div v-else-if="!items.length" class="empty-history">
      <span>0</span>
      <h3>还没有已完成的报告</h3>
      <p>完成一次录音分析后，报告会自动出现在这里。</p>
      <button type="button" class="primary-action" @click="$emit('back')">开始第一次练习</button>
    </div>
    <div v-else class="history-list">
      <article v-for="(item, index) in items" :key="item.answer_id" class="history-card">
        <div class="history-index">{{ String(items.length - index).padStart(2, "0") }}</div>
        <div class="history-copy">
          <div class="history-meta">
            <span>{{ item.category }}</span>
            <time>{{ formatDate(item.created_at) }}</time>
          </div>
          <h3>{{ item.question }}</h3>
          <p>{{ item.summary }}</p>
        </div>
        <div class="history-scores">
          <div><strong>{{ item.scores.total }}</strong><span>总分</span></div>
          <div><strong>{{ item.scores.content }}</strong><span>内容 / 60</span></div>
          <div><strong>{{ item.scores.fluency }}</strong><span>表达 / 40</span></div>
        </div>
        <button type="button" class="history-open" @click="$emit('open', item)">查看报告 →</button>
      </article>
    </div>
  </section>
</template>
