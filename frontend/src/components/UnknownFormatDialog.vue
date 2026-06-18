<script setup lang="ts">
/**
 * UnknownFormatDialog — 当后端返回 422 unknown_format 时弹出
 *
 * 显示从后端提取的诊断信息（banner、列名、pending 路径），
 * 提示用户联系管理员添加新版本。
 */

defineProps<{
  banner: string | null
  headerColumns: string[] | null
  pendingPath: string
}>()

defineEmits<{ close: [] }>()
</script>

<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal-card">
      <h3>未识别的 iostat 格式</h3>
      <p class="lead">后端无法识别当前日志的格式。样本已归档，请联系管理员添加新版本。</p>

      <dl class="diag">
        <dt>Banner</dt>
        <dd><code>{{ banner ?? '(未提取到)' }}</code></dd>

        <dt>Device header 列名</dt>
        <dd>
          <code v-if="headerColumns && headerColumns.length">{{ headerColumns.join(' ') }}</code>
          <code v-else>(未提取到)</code>
        </dd>

        <dt>归档路径</dt>
        <dd><code class="path">{{ pendingPath }}</code></dd>
      </dl>

      <div class="actions">
        <button class="btn btn-primary" @click="$emit('close')">我知道了</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-card {
  background: #fff;
  border-radius: 8px;
  padding: 24px;
  width: min(560px, 92vw);
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
}

h3 {
  margin: 0 0 8px 0;
  font-size: 18px;
}

.lead {
  color: #666;
  font-size: 14px;
  margin: 0 0 16px 0;
  line-height: 1.5;
}

dl.diag {
  margin: 0 0 20px 0;
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 8px 12px;
  font-size: 13px;
}

dl.diag dt {
  color: #999;
  font-weight: 500;
}

dl.diag dd {
  margin: 0;
}

code {
  background: #f5f5f5;
  padding: 2px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 12px;
  word-break: break-all;
}

code.path {
  background: #fff8e1;
  display: inline-block;
  max-width: 100%;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.btn {
  padding: 6px 16px;
  border: 1px solid #d0d0d0;
  background: #fff;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
}

.btn-primary {
  background: #1976d2;
  border-color: #1976d2;
  color: #fff;
}

.btn-primary:hover {
  background: #1565c0;
}
</style>
