<script setup lang="ts">
/**
 * MatchedVersionDialog — 解析成功时弹出
 *
 * 聚合展示本次命中的 iostat 版本，附可展开的文件清单。
 * 复用 UnknownFormatDialog 的 modal 样式，色调改为信息蓝。
 */

defineProps<{
  /** version_id -> [basenames]，来自 ParseResponse.matched_versions */
  matchedVersions: Record<string, string[]>
  /** 已注册的版本元信息（version_id -> {display_name}），用于展示友好名 */
  versionDisplayNames: Record<string, string>
  /** 本次解析的总文件数（用于 "全部 N 个" 兜底） */
  totalFiles: number
}>()

defineEmits<{ close: [] }>()
</script>

<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal-card info">
      <h3>iostat 版本已识别</h3>
      <p class="lead">
        本次解析共 {{ totalFiles }} 个文件，命中情况如下：
      </p>

      <ul class="agg">
        <li v-for="(files, ver) in matchedVersions" :key="ver">
          按
          <code class="ver">{{ versionDisplayNames[ver] || ver }}</code>
          <code class="ver-id">({{ ver }})</code>
          解析 {{ files.length }} 个文件
        </li>
      </ul>

      <details class="expand">
        <summary>查看每个文件匹配的版本</summary>
        <table class="file-table">
          <thead>
            <tr><th>文件</th><th>版本</th></tr>
          </thead>
          <tbody>
            <tr v-for="(_, ver) in matchedVersions" :key="`group-${ver}`">
              <td colspan="2" class="group-row">
                <code class="ver">{{ versionDisplayNames[ver] || ver }}</code>
                <code class="ver-id">({{ ver }})</code>
              </td>
            </tr>
            <template v-for="(files, ver) in matchedVersions" :key="`${ver}-files`">
              <tr v-for="f in files" :key="f">
                <td><code>{{ f }}</code></td>
                <td><code class="ver-id">{{ ver }}</code></td>
              </tr>
            </template>
          </tbody>
        </table>
      </details>

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
  width: min(620px, 92vw);
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
  border-top: 4px solid #2563eb;
}

h3 {
  margin: 0 0 8px 0;
  font-size: 18px;
  color: #1e3a8a;
}

.lead {
  color: #555;
  font-size: 14px;
  margin: 0 0 16px 0;
  line-height: 1.5;
}

ul.agg {
  margin: 0 0 16px 0;
  padding-left: 20px;
  font-size: 13px;
  line-height: 1.8;
  color: #333;
}

ul.agg li {
  list-style: disc;
}

.expand {
  border: 1px solid #e0e7ff;
  border-radius: 4px;
  padding: 8px 12px;
  background: #f5f7ff;
  margin-bottom: 16px;
}

.expand summary {
  cursor: pointer;
  font-size: 13px;
  color: #2563eb;
  user-select: none;
}

.file-table {
  width: 100%;
  margin-top: 8px;
  border-collapse: collapse;
  font-size: 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}

.file-table th,
.file-table td {
  text-align: left;
  padding: 4px 8px;
  border-bottom: 1px solid #e0e7ff;
}

.file-table th {
  color: #888;
  font-weight: 500;
  background: #eef2ff;
}

.group-row {
  background: #eef2ff;
  font-weight: 500;
}

code {
  background: #f0f4ff;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12px;
  word-break: break-all;
}

code.ver {
  background: #dbeafe;
  color: #1e3a8a;
  font-weight: 500;
}

code.ver-id {
  background: transparent;
  color: #6b7280;
  font-size: 11px;
  padding-left: 2px;
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
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
}

.btn-primary:hover {
  background: #1d4ed8;
}
</style>
