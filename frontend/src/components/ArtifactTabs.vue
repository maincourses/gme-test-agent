<script setup>
import { GitPullRequest } from "@lucide/vue";
import { useWorkspace } from "../composables/useWorkspace";

const {
  activeJobTab,
  eventsText,
  diffText,
  codexText,
  agentNotesText,
  jobDetailJson,
  openPr,
} = useWorkspace();
</script>

<template>
  <section class="panel detail-panel">
    <div class="tabbar">
      <button type="button" :class="{ active: activeJobTab === 'logs' }" @click="activeJobTab = 'logs'">日志</button>
      <button type="button" :class="{ active: activeJobTab === 'diff' }" @click="activeJobTab = 'diff'">代码变更</button>
      <button type="button" :class="{ active: activeJobTab === 'codex' }" @click="activeJobTab = 'codex'">Codex 输出</button>
      <button type="button" :class="{ active: activeJobTab === 'notes' }" @click="activeJobTab = 'notes'">分析文件</button>
      <button type="button" :class="{ active: activeJobTab === 'details' }" @click="activeJobTab = 'details'">任务详情</button>
      <button class="tab-action" type="button" @click="openPr">
        <GitPullRequest :size="15" />
        打开 PR
      </button>
    </div>
    <pre v-if="activeJobTab === 'logs'" class="code-block tall">{{ eventsText || "暂无日志" }}</pre>
    <pre v-if="activeJobTab === 'diff'" class="code-block tall">{{ diffText || "暂无代码变更" }}</pre>
    <pre v-if="activeJobTab === 'codex'" class="code-block tall">{{ codexText || "暂无 Codex 输出" }}</pre>
    <pre v-if="activeJobTab === 'notes'" class="code-block tall">{{ agentNotesText || "暂无 .gme-agent 分析文件" }}</pre>
    <pre v-if="activeJobTab === 'details'" class="code-block tall">{{ jobDetailJson }}</pre>
  </section>
</template>
