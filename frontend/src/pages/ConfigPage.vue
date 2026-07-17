<script setup>
import { FolderOpen, Save, ShieldCheck } from "@lucide/vue";
import { useWorkspace } from "../composables/useWorkspace";

const {
  busyAction,
  validation,
  configForm,
  branchOptions,
  remoteOptions,
  modelOptions,
  selectedModelOption,
  isCustomModel,
  reasoningEffortOptions,
  sandboxOptions,
  approvalPolicyOptions,
  saveConfig,
  chooseDirectory,
  chooseFile,
  validateEnvironment,
} = useWorkspace();
</script>

<template>
  <section class="page">
    <div class="page-heading">
      <div>
        <span class="eyebrow">Configuration</span>
        <h1>配置</h1>
      </div>
      <div class="heading-actions">
        <button class="primary-button" type="button" :disabled="!!busyAction" @click="saveConfig">
          <Save :size="16" />
          保存配置
        </button>
      </div>
    </div>

    <div class="config-grid">
      <section class="panel">
        <h2>路径</h2>
        <label class="field">
          <span>GME 仓库</span>
          <div class="input-action">
            <input v-model="configForm.gme_repo_path" />
            <button class="ghost-button compact" type="button" @click="chooseDirectory('gme_repo_path')">
              <FolderOpen :size="15" />
              选择
            </button>
          </div>
        </label>
        <label class="field">
          <span>工作区根目录</span>
          <div class="input-action">
            <input v-model="configForm.worktree_root" />
            <button class="ghost-button compact" type="button" @click="chooseDirectory('worktree_root')">
              <FolderOpen :size="15" />
              选择
            </button>
          </div>
        </label>
        <label class="field">
          <span>产物目录</span>
          <div class="input-action">
            <input v-model="configForm.artifact_root" />
            <button class="ghost-button compact" type="button" @click="chooseDirectory('artifact_root')">
              <FolderOpen :size="15" />
              选择
            </button>
          </div>
        </label>
        <label class="field">
          <span>数据库</span>
          <div class="input-action">
            <input v-model="configForm.database_path" />
            <button
              class="ghost-button compact"
              type="button"
              @click="chooseFile('database_path', [{ name: 'SQLite 数据库', extensions: ['db', 'sqlite', 'sqlite3'] }, { name: '全部文件', extensions: ['*'] }])"
            >
              <FolderOpen :size="15" />
              选择
            </button>
          </div>
        </label>
      </section>

      <section class="panel">
        <h2>Codex 与 Git</h2>
        <div class="two-col">
          <label class="field">
            <span>基准分支</span>
            <select v-model="configForm.base_branch">
              <option v-for="item in branchOptions" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label class="field">
            <span>Git 远端</span>
            <select v-model="configForm.github_remote">
              <option v-for="item in remoteOptions" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
        </div>
        <div class="two-col">
          <label class="field">
            <span>模型</span>
            <select v-model="selectedModelOption">
              <option v-for="item in modelOptions" :key="item.id" :value="item.id">
                {{ item.display_name }}
              </option>
            </select>
            <input v-if="isCustomModel" v-model.trim="configForm.model" placeholder="输入模型 ID，例如 gpt-5.6-sol" />
          </label>
          <label class="field">
            <span>推理强度</span>
            <select v-model="configForm.reasoning_effort">
              <option v-for="item in reasoningEffortOptions" :key="item.value" :value="item.value">
                {{ item.label }}
              </option>
            </select>
          </label>
        </div>
        <div class="two-col">
          <label class="field">
            <span>沙箱</span>
            <select v-model="configForm.sandbox">
              <option v-for="item in sandboxOptions" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label class="field">
            <span>审批策略</span>
            <select v-model="configForm.approval_policy">
              <option v-for="item in approvalPolicyOptions" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
        </div>
      </section>

      <section class="panel">
        <div class="panel-title-row">
          <h2>环境检查结果</h2>
          <button class="ghost-button compact" type="button" @click="validateEnvironment">
            <ShieldCheck :size="15" />
            检查
          </button>
        </div>
        <pre class="code-block">{{ validation ? JSON.stringify(validation, null, 2) : "暂无检查结果" }}</pre>
      </section>
    </div>
  </section>
</template>
