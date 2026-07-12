<script setup>
import { Clipboard } from "@lucide/vue";
import { jobTypeLabels, useWorkspace } from "../composables/useWorkspace";

const {
  testJobs,
  selectedJob,
  selectedJobId,
  selectJob,
  copyText,
  shortId,
  jobStatus,
  statusTone,
} = useWorkspace();
</script>

<template>
  <section class="panel table-panel">
    <div class="panel-title-row">
      <h2>测试任务</h2>
      <button class="ghost-button compact" type="button" @click="copyText(selectedJob?.worktree_path || '')">
        <Clipboard :size="15" />
        复制工作区
      </button>
    </div>
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>类型</th>
            <th>状态</th>
            <th>标题</th>
            <th>模块</th>
            <th>目标仓库</th>
            <th>测试目标</th>
            <th>更新时间</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="job in testJobs"
            :key="job.id"
            :class="{ selected: selectedJobId === job.id }"
            @click="selectJob(job.id)"
          >
            <td><code>{{ shortId(job.id) }}</code></td>
            <td>{{ jobTypeLabels[job.type] || job.type }}</td>
            <td><span class="status-pill" :class="statusTone(job.status)">{{ jobStatus(job) }}</span></td>
            <td>{{ job.title }}</td>
            <td>{{ job.module }}</td>
            <td>{{ job.metadata?.target_repo || "" }}</td>
            <td class="truncate">{{ job.api_name }}</td>
            <td>{{ job.updated_at }}</td>
          </tr>
          <tr v-if="!testJobs.length">
            <td colspan="8" class="empty-cell">暂无任务</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
