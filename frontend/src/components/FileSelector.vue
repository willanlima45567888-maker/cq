<script setup lang="ts">
defineProps<{
  files: string[]
  selected: string[]
}>()

const emit = defineEmits<{
  toggle: [string]
  'select-all': []
  'deselect-all': []
}>()
</script>

<template>
  <div class="file-selector">
    <div class="actions">
      <button @click="emit('select-all')">全选</button>
      <button @click="emit('deselect-all')">取消</button>
    </div>
    <div class="files-list">
      <label v-for="file in files" :key="file" class="file-item">
        <input
          type="checkbox"
          :checked="selected.includes(file)"
          @change="emit('toggle', file)"
        />
        {{ file }}
      </label>
    </div>
  </div>
</template>

<style scoped>
.file-selector {
  background: white;
  border-radius: 8px;
  padding: 12px;
}
.actions {
  margin-bottom: 8px;
  display: flex;
  gap: 8px;
}
.actions button {
  padding: 4px 12px;
  border: 1px solid #ddd;
  background: #f5f5f5;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
}
.files-list {
  max-height: 200px;
  overflow-y: auto;
}
.file-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  cursor: pointer;
  font-size: 13px;
  font-family: monospace;
}
</style>
