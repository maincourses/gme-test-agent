<script setup>
import { Ban, CheckCircle2, Clipboard, Play, RotateCcw, Wrench } from "@lucide/vue";
import FailureTable from "../components/FailureTable.vue";
import MetricStrip from "../components/MetricStrip.vue";
import { useWorkspace } from "../composables/useWorkspace";

const {
  busyAction,
  failureStats,
  selectedFailure,
  failureDetailJson,
  failureFilter,
  copyText,
  fixSelectedFailure,
  reproduceSelectedFailure,
  markSelectedFailure,
} = useWorkspace();
</script>

<template>
  <section class="page">
    <div class="page-heading">
      <div>
        <span class="eyebrow">Fix Agent</span>
        <h1>修复 Agent</h1>
      </div>
      <MetricStrip
        :items="[
          { label: '未修复', value: failureStats.open },
          { label: '处理中', value: failureStats.fixing },
          { label: '已修复', value: failureStats.fixed },
        ]"
      />
    </div>

    <section class="panel action-panel">
      <button class="primary-button" type="button" :disabled="!!busyAction" @click="fixSelectedFailure">
        <Wrench :size="16" />
        修复选中失败
      </button>
      <button class="ghost-button" type="button" :disabled="!!busyAction" @click="reproduceSelectedFailure">
        <Play :size="16" />
        复现失败
      </button>
      <button class="ghost-button" type="button" :disabled="!!busyAction" @click="markSelectedFailure('fixed')">
        <CheckCircle2 :size="16" />
        标记为已修复
      </button>
      <button class="ghost-button" type="button" :disabled="!!busyAction" @click="markSelectedFailure('ignored')">
        <Ban :size="16" />
        标记为忽略
      </button>
      <button class="ghost-button" type="button" :disabled="!!busyAction" @click="markSelectedFailure('open')">
        <RotateCcw :size="16" />
        重新打开失败
      </button>
    </section>

    <div class="fix-layout">
      <FailureTable />

      <section class="panel failure-detail">
        <div class="panel-title-row">
          <h2>失败详情</h2>
          <button class="ghost-button compact" type="button" @click="copyText(failureFilter(selectedFailure || {}))">
            <Clipboard :size="15" />
            复制过滤器
          </button>
        </div>
        <pre class="code-block tall">{{ selectedFailure ? failureDetailJson : "未选择失败用例" }}</pre>
      </section>
    </div>
  </section>
</template>
