<script setup lang="ts">
/**
 * UploadResultDialog — 上传完成后弹出
 *
 * 展示本次上传的成功 / 失败 / 重命名情况。
 * 复用 MatchedVersionDialog 的 modal 样式，色调改为成功绿。
 */

interface UploadedItem {
  original: string
  saved_as: string
  path: string
}

interface FailedItem {
  filename: string
  reason: string
}

defineProps<{
  uploaded: UploadedItem[]
  failed: FailedItem[]
}>()

defineEmits<{ close: [] }>()
</script>

<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal-card success">
      <h3>上传完成</h3>
      <p class="lead">
        成功 <strong class="ok">{{ uploaded.length }}</strong> 个，失败
        <strong :class="failed.length ? 'bad' : 'ok'">{{ failed.length }}</strong> 个
      </p>

      <div v-if="uploaded.length" class="block">
        <h4>成功</h4>
        <ul class="files">
          <li
            v-for="item in uploaded"
            :key="item.saved_as"
            :class="{ renamed: item.original !== item.saved_as }"
          >
            <code class="name">{{ item.saved_as }}</code>
            <span v-if="item.original !== item.saved_as" class="rename-hint">
              （原 <code>{{ item.original }}</code> 已存在，自动重命名以避免覆盖）
            </span>
            <code class="path">{{ item.path }}</code>
          </li>
        </ul>
      </div>

      <div v-if="failed.length" class="block">
        <h4>失败</h4>
        <ul class="files failed">
          <li v-for="(item, idx) in failed" :key="`${item.filename}-${idx}`">
            <code class="name">{{ item.filename || '(未命名)' }}</code>
            <span class="reason">{{ item.reason }}</span>
          </li>
        </ul>
      </div>

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
  width: min(680px, 92vw);
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
  border-top: 4px solid #16a34a;
}

h3 {
  margin: 0 0 8px 0;
  font-size: 18px;
  color: #14532d;
}

.lead {
  color: #555;
  font-size: 14px;
  margin: 0 0 16px 0;
  line-height: 1.5;
}
.lead strong.ok {
  color: #16a34a;
}
.lead strong.bad {
  color: #dc2626;
}

.block {
  margin-bottom: 16px;
}
.block h4 {
  margin: 0 0 6px 0;
  font-size: 13px;
  color: #555;
  font-weight: 600;
}

ul.files {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid #e0e7ff;
  border-radius: 4px;
  background: #f5f7ff;
}
ul.files.failed {
  border-color: #fecaca;
  background: #fef2f2;
}
ul.files li {
  padding: 6px 12px;
  border-bottom: 1px solid #e0e7ff;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
ul.files.failed li {
  border-bottom-color: #fecaca;
}
ul.files li:last-child {
  border-bottom: none;
}
ul.files li.renamed {
  background: #fff7ed;
}

code {
  background: #f0f4ff;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12px;
  word-break: break-all;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
code.name {
  background: #dcfce7;
  color: #14532d;
  font-weight: 500;
}
code.path {
  background: transparent;
  color: #6b7280;
  font-size: 11px;
  padding: 0;
}
.rename-hint {
  font-size: 11px;
  color: #9a3412;
}
.rename-hint code {
  background: #fed7aa;
  color: #9a3412;
  font-size: 11px;
}
.reason {
  font-size: 12px;
  color: #b91c1c;
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
  background: #16a34a;
  border-color: #16a34a;
  color: #fff;
}
.btn-primary:hover {
  background: #15803d;
  border-color: #15803d;
}
</style>
