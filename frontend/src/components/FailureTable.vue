<script setup>
import { computed } from "vue";
import { useWorkspace } from "../composables/useWorkspace";

const {
  failureJobGroups,
  selectedFailureJobId,
  selectedFailureJobFailures,
  selectedFailureId,
  selectFailureJob,
  selectFailure,
  shortId,
  jobStatus,
  failureStatus,
  statusTone,
} = useWorkspace();

const openCount = computed(() => selectedFailureJobFailures.value.filter((failure) => failure.status === "open").length);

function fullName(failure) {
  return failure?.test_suite && failure?.test_name ? `${failure.test_suite}.${failure.test_name}` : "未知测试";
}

function shortFile(path) {
  const value = String(path || "").replace(/\\/g, "/");
  const marker = "/tests/gme/";
  const index = value.lastIndexOf(marker);
  return index >= 0 ? value.slice(index + marker.length) : value.split("/").slice(-3).join("/");
}

function shortFailureId(id) {
  const value = String(id || "");
  return value.startsWith("gmefail-") ? `gmefail-${value.slice(-8)}` : shortId(value);
}
</script>

<template>
  <section class="panel failure-list-panel">
    <div class="failure-browser-section">
      <div class="panel-title-row">
        <div>
          <h2>来源测试任务</h2>
          <p>{{ failureJobGroups.length }} 个任务包含待处理失败</p>
        </div>
      </div>

      <div class="failure-task-list">
        <button
          v-for="group in failureJobGroups"
          :key="group.job.id"
          type="button"
          class="failure-task-item"
          :class="{ selected: selectedFailureJobId === group.job.id }"
          @click="selectFailureJob(group.job.id)"
        >
          <span class="failure-task-main">
            <span>
              <code>{{ shortId(group.job.id) }}</code>
              <span class="module-label">{{ group.job.module || "未知模块" }}</span>
            </span>
            <strong>{{ group.job.title || `${group.job.module || "模块"} 测试任务` }}</strong>
            <small>{{ jobStatus(group.job) }}</small>
          </span>
          <span class="failure-task-count">
            <strong>{{ group.failures.length }}</strong>
            <small>失败</small>
          </span>
        </button>

        <div v-if="!failureJobGroups.length" class="empty-state compact-empty">
          <strong>暂无待修复任务</strong>
          <span>测试任务产生真实失败后会显示在这里。</span>
        </div>
      </div>
    </div>

    <div class="failure-browser-divider"></div>

    <div class="failure-browser-section failure-cases-section">
      <div class="panel-title-row">
        <div>
          <h2>失败用例</h2>
          <p>{{ selectedFailureJobFailures.length }} 条记录，{{ openCount }} 条待修复</p>
        </div>
      </div>

      <div class="failure-list">
        <button
          v-for="failure in selectedFailureJobFailures"
          :key="failure.id"
          type="button"
          class="failure-item"
          :class="{ selected: selectedFailureId === failure.id }"
          @click="selectFailure(failure.id)"
        >
          <span class="failure-item-top">
            <code>{{ shortFailureId(failure.id) }}</code>
            <span class="status-pill" :class="statusTone(failure.status)">{{ failureStatus(failure) }}</span>
          </span>
          <strong>{{ fullName(failure) }}</strong>
          <small>{{ shortFile(failure.file) }}{{ failure.line ? `:${failure.line}` : "" }}</small>
        </button>

        <div v-if="selectedFailureJobId && !selectedFailureJobFailures.length" class="empty-state compact-empty">
          <strong>该任务暂无待处理失败</strong>
          <span>已修复、已忽略和已提交 skip PR 的用例不会显示。</span>
        </div>
      </div>
    </div>
  </section>
</template>
