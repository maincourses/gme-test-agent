<script setup>
import { useWorkspace } from "../composables/useWorkspace";

const {
  currentFailures,
  selectedFailureId,
  selectFailure,
  shortId,
  failureStatus,
  statusTone,
} = useWorkspace();
</script>

<template>
  <section class="panel table-panel">
    <h2>失败用例</h2>
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>状态</th>
            <th>测试套件</th>
            <th>测试名</th>
            <th>文件</th>
            <th>行号</th>
            <th>原因</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="failure in currentFailures"
            :key="failure.id"
            :class="{ selected: selectedFailureId === failure.id }"
            @click="selectFailure(failure.id)"
          >
            <td><code>{{ shortId(failure.id) }}</code></td>
            <td><span class="status-pill" :class="statusTone(failure.status)">{{ failureStatus(failure) }}</span></td>
            <td>{{ failure.test_suite }}</td>
            <td>{{ failure.test_name }}</td>
            <td class="truncate">{{ failure.file }}</td>
            <td>{{ failure.line }}</td>
            <td class="truncate">{{ failure.reason }}</td>
          </tr>
          <tr v-if="!currentFailures.length">
            <td colspan="7" class="empty-cell">暂无失败用例</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
