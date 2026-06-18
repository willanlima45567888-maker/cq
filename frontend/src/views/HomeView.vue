<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()

/** OSW 工具卡片清单
 * - ready=true: 已实现，点击跳转
 * - ready=false: 占位，灰显，hover 提示"即将推出"
 */
interface ToolCard {
  id: string          // 路由 id（与 router name 对应）
  slug: string        // osw 工具目录名（如 oswiostat / oswps）
  title: string       // 卡片标题
  desc: string        // 采集的指标一句话描述
  status: 'ready' | 'coming' | 'wip'
  routeName?: string  // status=ready 时填，要跳的路由 name
}

const tools: ToolCard[] = [
  {
    id: 'iostat',
    slug: 'oswiostat',
    title: 'iostat',
    desc: '磁盘 I/O 设备指标（rrqm/s、w/s、%util 等）+ avg-cpu',
    status: 'ready',
    routeName: 'iostat',
  },
  {
    id: 'ps',
    slug: 'oswps',
    title: 'ps',
    desc: '进程快照：PID、CPU%、内存、状态、命令行',
    status: 'ready',
    routeName: 'ps',
  },
  {
    id: 'top',
    slug: 'oswtop',
    title: 'top',
    desc: '系统 top 快照：进程、负载、CPU/内存使用',
    status: 'ready',
    routeName: 'top',
  },
  {
    id: 'netstat',
    slug: 'oswnetstat',
    title: 'netstat',
    desc: '网络统计：每个接口的 RX/TX 流量 + 内核 IP/TCP/UDP 计数器',
    status: 'ready',
    routeName: 'netstat',
  },
  {
    id: 'mpstat',
    slug: 'oswmpstat',
    title: 'mpstat',
    desc: '多核 CPU 统计：每 CPU 的 %user/%system/%iowait',
    status: 'coming',
  },
  {
    id: 'vmstat',
    slug: 'oswvmstat',
    title: 'vmstat',
    desc: '虚拟内存统计：si/so/bi/bo/cs/us/sy 等',
    status: 'coming',
  },
  {
    id: 'meminfo',
    slug: 'oswmeminfo',
    title: 'meminfo',
    desc: '/proc/meminfo 内存细分（MemFree/Buffers/Cached/Swap）',
    status: 'coming',
  },
  {
    id: 'lsof',
    slug: 'oswlsof',
    title: 'lsof',
    desc: '打开的文件描述符与对应进程',
    status: 'coming',
  },
]

function go(card: ToolCard) {
  if (card.status === 'ready' && card.routeName) {
    router.push({ name: card.routeName })
  }
}
</script>

<template>
  <div class="home">
    <header class="hero">
      <h1>OSW-View</h1>
      <p class="subtitle">OSW 采集日志可视化分析工具集</p>
      <p class="hint">选择下方任一 OSW 工具开始分析 · 文件可上传到 <code>oswupdownload_file/</code> 目录</p>
    </header>

    <section class="grid">
      <article
        v-for="card in tools"
        :key="card.id"
        class="card"
        :class="[`status-${card.status}`]"
        :tabindex="card.status === 'ready' ? 0 : -1"
        :role="card.status === 'ready' ? 'button' : undefined"
        @click="go(card)"
        @keyup.enter="go(card)"
      >
        <div class="card-head">
          <code class="slug">{{ card.slug }}/</code>
          <span class="badge" :class="card.status">
            {{
              card.status === 'ready' ? '已就绪'
              : card.status === 'wip' ? '开发中'
              : '即将推出'
            }}
          </span>
        </div>
        <h2 class="card-title">{{ card.title }}</h2>
        <p class="card-desc">{{ card.desc }}</p>
        <div v-if="card.status === 'ready'" class="card-action">点击进入 →</div>
        <div v-else class="card-action disabled">敬请期待</div>
      </article>
    </section>
  </div>
</template>

<style scoped>
.home {
  max-width: 1200px;
  margin: 0 auto;
  padding: 40px 24px;
}

.hero {
  text-align: center;
  margin-bottom: 32px;
}
.hero h1 {
  font-size: 32px;
  font-weight: 700;
  color: #1e3a8a;
  margin-bottom: 8px;
}
.subtitle {
  font-size: 15px;
  color: #555;
  margin-bottom: 4px;
}
.hint {
  font-size: 12px;
  color: #888;
}
.hint code {
  background: #f0f4ff;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  color: #1e3a8a;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}

.card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 18px 20px;
  cursor: pointer;
  transition: all 0.15s;
  display: flex;
  flex-direction: column;
  gap: 8px;
  outline: none;
}
.card:hover {
  border-color: #93c5fd;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.08);
  transform: translateY(-1px);
}
.card:focus-visible {
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
}

.card.status-coming {
  cursor: not-allowed;
  background: #fafafa;
  border-style: dashed;
}
.card.status-coming:hover {
  border-color: #d1d5db;
  box-shadow: none;
  transform: none;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.slug {
  background: #f0f4ff;
  color: #1e3a8a;
  padding: 1px 8px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
}
.status-coming .slug {
  background: #f3f4f6;
  color: #6b7280;
}

.badge {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 10px;
  font-weight: 500;
}
.badge.ready {
  background: #dcfce7;
  color: #14532d;
}
.badge.coming {
  background: #f3f4f6;
  color: #6b7280;
}
.badge.wip {
  background: #fef3c7;
  color: #92400e;
}

.card-title {
  font-size: 22px;
  font-weight: 600;
  color: #1f2937;
  margin: 0;
}
.status-coming .card-title {
  color: #9ca3af;
}

.card-desc {
  font-size: 13px;
  color: #6b7280;
  line-height: 1.5;
  flex: 1;
  margin: 0;
}

.card-action {
  font-size: 13px;
  color: #2563eb;
  font-weight: 500;
  margin-top: 4px;
}
.card-action.disabled {
  color: #9ca3af;
  font-weight: 400;
}
</style>
