/**
 * Markdown 报告生成器（spec 一-八章节）
 *
 * 输入：ps analyze 的响应（PsAnalysisResponse）
 * 输出：完整的 .md 报告字符串
 *
 * 设计原则：
 *   - 纯函数（无副作用），便于测试
 *   - 所有数据用表格 + 列表，不依赖外部图（图表由 Vue 页面提供交互视图）
 *   - 数字格式化用中文习惯（千分位、KB/MB/G）
 */

import type { PsAnalysisResponse, PsLifecycleEntry } from '../../api/ps'

function formatKB(kb: number): string {
  if (kb >= 1024 * 1024) return `${(kb / 1024 / 1024).toFixed(2)} G`
  if (kb >= 1024) return `${(kb / 1024).toFixed(1)} M`
  return `${Math.round(kb)} K`
}

function shortCmd(cmd: string, max = 50): string {
  if (cmd.length <= max) return cmd
  return cmd.slice(0, max) + '...'
}

function _fmtDur(sec: number): string {
  if (!sec || sec < 0) return '0s'
  if (sec < 60) return `${sec.toFixed(0)}s`
  if (sec < 3600) {
    const m = Math.floor(sec / 60)
    const s = Math.floor(sec % 60)
    return s > 0 ? `${m}m ${s}s` : `${m}m`
  }
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

function nowStr(): string {
  return new Date().toLocaleString('zh-CN', { hour12: false })
}

export function buildMarkdownReport(a: PsAnalysisResponse, fileName: string): string {
  const lines: string[] = []

  lines.push('# OSWatcher ps 日志分析报告')
  lines.push('')
  lines.push(`- **源文件**：\`${fileName}\``)
  lines.push(`- **采样周期数**：${a.cycle_count}`)
  lines.push(`- **时间范围**：${a.time_range.start} → ${a.time_range.end}`)
  lines.push(`- **匹配格式版本**：${Object.keys(a.matched_versions).join(', ')}`)
  lines.push(`- **报告生成时间**：${nowStr()}`)
  lines.push('')
  lines.push('---')
  lines.push('')

  // 一、总体概览
  lines.push('## 一、总体概览')
  lines.push('')
  const ov = a.overview
  lines.push('| 分类 | 累计出现次数 |')
  lines.push('| --- | ---: |')
  lines.push(`| 总进程数 | ${ov.total.toLocaleString()} |`)
  lines.push(`| Oracle 进程 | ${ov.oracle.toLocaleString()} |`)
  lines.push(`| Grid 进程 | ${ov.grid.toLocaleString()} |`)
  lines.push(`| 用户进程（人类） | ${ov.user.toLocaleString()} |`)
  lines.push(`| Kernel 线程 | ${ov.kernel.toLocaleString()} |`)
  lines.push(`| 系统守护进程 | ${ov.system_daemon.toLocaleString()} |`)
  lines.push(`| 用户脚本 | ${ov.user_script.toLocaleString()} |`)
  lines.push('')
  lines.push('### 按 USER 分布')
  lines.push('')
  lines.push('| USER | 进程数（去重 PID） |')
  lines.push('| --- | ---: |')
  for (const u of ov.by_user) {
    lines.push(`| \`${u.user}\` | ${u.process_count} |`)
  }
  lines.push('')
  lines.push('### 趋势摘要')
  lines.push('')
  lines.push('| 分类 | 平均 | 峰值 |')
  lines.push('| --- | ---: | ---: |')
  const t = a.trends
  const avg = (arr: number[]) => (arr.length ? (arr.reduce((s, x) => s + x, 0) / arr.length).toFixed(1) : '0')
  const mx = (arr: number[]) => (arr.length ? Math.max(...arr).toString() : '0')
  lines.push(`| 总进程 | ${avg(t.total)} | ${mx(t.total)} |`)
  lines.push(`| Oracle | ${avg(t.oracle)} | ${mx(t.oracle)} |`)
  lines.push(`| Grid | ${avg(t.grid)} | ${mx(t.grid)} |`)
  lines.push(`| Kernel | ${avg(t.kernel)} | ${mx(t.kernel)} |`)
  lines.push(`| 用户 | ${avg(t.user)} | ${mx(t.user)} |`)
  lines.push(`| PX 并行 | ${avg(t.px)} | ${mx(t.px)} |`)
  lines.push(`| Job | ${avg(t.job)} | ${mx(t.job)} |`)
  lines.push('')
  lines.push('> 图表详见 HTML Dashboard：进程总数趋势图（多线）。')
  lines.push('')

  lines.push('## 二、指标时间线（按周期）')
  lines.push('')
  lines.push('| 指标 | 平均 | 峰值 |')
  lines.push('| --- | ---: | ---: |')
  const metricDefs: { key: keyof typeof t; label: string }[] = [
    { key: 'total',         label: '总进程数' },
    { key: 'oracle',        label: 'Oracle 进程' },
    { key: 'grid',          label: 'Grid 进程' },
    { key: 'kernel',        label: 'Kernel 线程' },
    { key: 'user',          label: '用户进程' },
    { key: 'system_daemon', label: '系统守护' },
    { key: 'user_script',   label: '用户脚本' },
    { key: 'px',            label: 'PX 并行' },
    { key: 'job',           label: 'Job 队列' },
  ]
  for (const m of metricDefs) {
    const arr = t[m.key] as number[]
    lines.push(`| ${m.label} | ${avg(arr)} | ${mx(arr)} |`)
  }
  lines.push('')
  lines.push('> 详细趋势图见 HTML Dashboard：指标时间线（每指标一张折线图，9 张图网格布局）。')
  lines.push('')

  // 三、进程 WCHAN（等待的内核函数）
  lines.push('## 三、进程 WCHAN（等待的内核函数）')
  lines.push('**重要程度 ★★★★★**。WCHAN 字段是排查 IO 阻塞 / 锁竞争 / 网络等待的关键。')
  lines.push('')
  const w = a.wchan
  lines.push('| 类别 | 含义 | 峰值 | 全周期累加 |')
  lines.push('| --- | --- | ---: | ---: |')
  for (const c of w.category_order) {
    const total = w.category_total[c] ?? 0
    const max = w.category_max[c] ?? 0
    if (total === 0 && max === 0) continue
    const isAbn = (c === 'io' || c === 'lock') && (max > 0)
    const mark = isAbn ? ' ⚠️' : ''
    lines.push(`| \`${c}\`${mark} | ${w.category_legend[c] ?? c} | ${max} | ${total.toLocaleString()} |`)
  }
  lines.push('')
  lines.push('### Top WCHAN 排行')
  lines.push('')
  lines.push('| # | WCHAN | 类别 | 出现次数 |')
  lines.push('| ---: | --- | --- | ---: |')
  for (let i = 0; i < Math.min(15, w.top_wchans.length); i++) {
    const tw = w.top_wchans[i]
    lines.push(`| ${i + 1} | \`${tw.wchan}\` | ${tw.category} | ${tw.count.toLocaleString()} |`)
  }
  lines.push('')
  if (w.stuck_pids.length > 0) {
    lines.push('**持续卡在 IO / Lock 等待的进程**（连续 ≥ 5 cycle）：')
    lines.push('')
    lines.push('| PID | USER | COMMAND | WCHAN | 类别 | 卡住 cycle |')
    lines.push('| ---: | --- | --- | --- | --- | ---: |')
    for (const p of w.stuck_pids) {
      lines.push(`| ${p.pid} | \`${p.user}\` | \`${shortCmd(p.command, 60)}\` | \`${p.wchan}\` | ${p.category} | ${p.cycles} |`)
    }
    lines.push('')
  }
  lines.push('> 详细图表见 HTML Dashboard：进程 WCHAN。')
  lines.push('')

  // 四、TOP 进程（核心 8 字段）
  lines.push('## 四、TOP 进程（核心 8 字段）')
  lines.push('')
  lines.push('| USER | PID | %CPU max | RSS max | STATE | WCHAN | STARTED | COMMAND |')
  lines.push('| --- | ---: | ---: | ---: | --- | --- | --- | --- |')
  // 合并 cpu_top + mem_top（按 pid 去重）
  const topByPid = new Map<number, any>()
  for (const c of a.cpu_top) {
    topByPid.set(c.pid, {
      user: c.user, pid: c.pid,
      cpu: c.cpu_pct_max, rss: c.rss_max_kb ?? 0,
      state: c.state ?? 'S', wchan: c.wchan ?? '',
      first_seen: c.first_seen,
      command: c.command,
    })
  }
  for (const m of a.mem_top) {
    const existing = topByPid.get(m.pid)
    if (existing) {
      existing.rss = Math.max(existing.rss, m.rss_max_kb)
    } else {
      topByPid.set(m.pid, {
        user: m.user, pid: m.pid,
        cpu: m.cpu_pct_max ?? 0, rss: m.rss_max_kb,
        state: m.state ?? 'S', wchan: m.wchan ?? '',
        first_seen: m.first_seen,
        command: m.command,
      })
    }
  }
  const tops = Array.from(topByPid.values()).sort((a, b) => b.cpu - a.cpu)
  for (const t of tops) {
    lines.push(`| \`${t.user}\` | ${t.pid} | ${t.cpu.toFixed(1)}% | ${formatKB(t.rss)} | \`${t.state}\` | \`${t.wchan || '-'}\` | ${t.first_seen} | \`${shortCmd(t.command, 60)}\` |`)
  }
  lines.push('')

  // 五、USER 维度
  lines.push('## 五、USER 维度')
  lines.push('')
  lines.push('按 USER 聚合：')
  lines.push('')
  lines.push('| USER | 进程数（去重 PID） |')
  lines.push('| --- | ---: |')
  for (const u of ov.by_user) {
    lines.push(`| \`${u.user}\` | ${u.process_count} |`)
  }
  lines.push('')

  // 六、进程分类识别（COMMAND 字段，4 个子节）
  lines.push('## 六、进程分类识别（COMMAND 字段）')
  lines.push('')
  // 7.1 Oracle 后台
  lines.push('### 7.1 Oracle 后台进程')
  lines.push('')
  const o = a.oracle
  lines.push(`- **PX 峰值并发**：${o.px_peak}`)
  lines.push(`- **Job 峰值并发**：${o.job_peak}`)
  lines.push('')
  lines.push('| 后台类型 | 最大并发 | 累计不同 PID | 含义 |')
  lines.push('| --- | ---: | ---: | --- |')
  const ORACLE_DESC: Record<string, string> = {
    pmon: 'Process Monitor', lgwr: 'Log Writer',
    dbw: 'Database Writer', ckpt: 'Checkpoint',
    mman: 'Memory Manager', mmon: 'Manageability Monitor',
    smon: 'System Monitor', reco: 'Recoverer',
    qmn: 'Queue Monitor', vktm: 'Virtual Keeper of Time',
    lmon: 'Lock Monitor (RAC)', lmd: 'Lock Manager Daemon (RAC)',
    lck: 'Lock Process (RAC)', rms: 'RAC Management',
    rvwr: 'Recovery Writer', arc: 'Archiver',
    tt: 'Temp Table', dia: 'Diagnostic',
    m: 'MMON Slave', s: 'Shared Server', n: 'Connection Broker',
    px: 'Parallel Execution', pr: 'Parallel Recovery',
    job: 'Job Slave',
  }
  const bgEntries = Object.entries(o.background_counts)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
  for (const [kind, maxCnt] of bgEntries) {
    lines.push(`| \`${kind}\` | ${maxCnt} | ${o.distinct_pids[kind] ?? 0} | ${ORACLE_DESC[kind] ?? ''} |`)
  }
  lines.push('')

  // 7.2 Grid Infrastructure
  lines.push('### 7.2 Grid Infrastructure 进程')
  lines.push('')
  const g = a.grid
  const gkEntries = Object.entries(g.kind_counts).filter(([, v]) => v > 0)
  if (gkEntries.length === 0) {
    lines.push('本样本未发现 Grid 进程（可能是单实例数据库或非 RAC 环境）。')
  } else {
    lines.push('| 类型 | 最大并发 | 累计不同 PID | 重启次数 |')
    lines.push('| --- | ---: | ---: | ---: |')
    for (const [kind, maxCnt] of gkEntries) {
      const restarts = g.restart_count[kind] ?? 0
      const restartMark = restarts > 0 ? ` **${restarts}**` : ''
      lines.push(`| \`${kind}\` | ${maxCnt} | ${g.distinct_pids[kind] ?? 0} | ${restartMark} |`)
    }
  }
  lines.push('')
  if (Object.values(g.restart_count).some((v) => v > 0)) {
    lines.push('> ⚠️ 检测到 Grid 进程重启，建议检查 ohasd/crsd 日志。')
    lines.push('')
  }

  // 7.3 Linux 系统进程
  lines.push('### 7.3 Linux 系统进程（kworker / jbd2 / multipathd / systemd 等）')
  lines.push('')
  const sys = a.system
  const skEntries = Object.entries(sys.kind_peak).filter(([, v]) => v > 0)
  if (skEntries.length === 0) {
    lines.push('本样本未发现 kworker/jbd2/multipathd/systemd 等典型 Linux 系统进程。')
  } else {
    lines.push('| 类型 | 平均数 | 峰值 | 出现 cycle |')
    lines.push('| --- | ---: | ---: | ---: |')
    for (const [kind, peakCnt] of skEntries) {
      lines.push(`| \`${kind}\` | ${sys.kind_avg[kind] ?? 0} | ${peakCnt} | ${sys.kind_cycles[kind] ?? 0} / ${sys.cycle_count} |`)
    }
  }
  lines.push('')

  // 7.4 用户脚本
  lines.push('### 7.4 用户脚本（raid-check / rman / expdp / tar / gzip 等）')
  lines.push('')
  if (a.user_scripts.length === 0) {
    lines.push('本样本未发现 raid-check / rman / expdp / impdp / tar / gzip / rsync / scp / backup.sh 等用户脚本。')
  } else {
    lines.push('| 脚本 | 执行次数 | 最大 CPU% | 最大 RSS | 开始 → 结束 |')
    lines.push('| --- | ---: | ---: | ---: | --- |')
    for (const s of a.user_scripts) {
      lines.push(`| \`${s.name}\` | ${s.run_count} | ${s.max_cpu.toFixed(1)} | ${formatKB(s.max_rss_kb)} | ${s.first_seen} → ${s.last_seen} |`)
    }
  }
  lines.push('')
  lines.push('---')
  lines.push('')

  // 七、生命周期
  lines.push('## 七、生命周期（STARTED 字段）')
  lines.push('')
  lines.push('跟踪 Oracle / Grid / Script / System 四类重要进程的运行时长。')
  lines.push('')
  lines.push('总跟踪进程数：**' + a.lifecycle.length + '**')
  lines.push('')
  const byCat: Record<string, PsLifecycleEntry[]> = { oracle: [], grid: [], system: [], script: [] }
  for (const l of a.lifecycle) {
    if (byCat[l.category]) byCat[l.category].push(l)
  }
  // 汇总
  const alive_all = a.lifecycle.filter((l) => l.cycles_seen === a.cycle_count).length
  const alive_most = a.lifecycle.filter((l) => l.frequency_pct >= 80).length
  const one_off = a.lifecycle.filter((l) => l.cycles_seen === 1).length
  lines.push(`- 全周期都在（frequency = 100%）：**${alive_all}** 个`)
  lines.push(`- 长时间活跃（frequency ≥ 80%）：**${alive_most}** 个`)
  lines.push(`- 一次性 / 极短任务（仅出现 1 个 cycle）：**${one_off}** 个`)
  lines.push('')
  // 每个类别的运行时长 TOP 表
  for (const cat of ['oracle', 'grid', 'script', 'system'] as const) {
    const items = byCat[cat]
    if (items.length === 0) continue
    const catLabel = { oracle: 'Oracle', grid: 'Grid', system: 'System', script: 'Script' }[cat]
    lines.push(`### ${catLabel}（${items.length} 个，按运行时长降序）`)
    lines.push('')
    lines.push('| 程序 | PID 数 | 首次出现 | 最后出现 | 运行时长 | 频率 |')
    lines.push('| --- | ---: | --- | --- | ---: | ---: |')
    const showLimit = 30
    for (const l of items.slice(0, showLimit)) {
      const pidMark = l.pid_count > 1 ? ` **${l.pid_count}**` : ` ${l.pid_count}`
      const durStr = _fmtDur(l.duration_seconds)
      lines.push(`| \`${shortCmd(l.name, 55)}\` |${pidMark} | ${l.first_seen} | ${l.last_seen} | ${durStr} | ${l.frequency_pct.toFixed(1)}% |`)
    }
    if (items.length > showLimit) {
      lines.push(`| ... | ... | ... | ... | ... | ... |`)
      lines.push(`\n（仅显示前 ${showLimit} 条，完整列表见 HTML Dashboard）`)
    }
    lines.push('')
  }
  lines.push('---')
  lines.push('')

  // 八、结论与建议
  lines.push('## 八、结论与建议')
  lines.push('')
  const hints: string[] = []
  if (a.oracle.background_counts.pmon) hints.push(`- Oracle 后台进程并发稳定（pmon=${a.oracle.background_counts.pmon}, lgwr=${a.oracle.background_counts.lgwr}, dbw=${a.oracle.background_counts.dbw}）。`)
  if (a.oracle.px_peak > 0) hints.push(`- 采样期内检测到 PX 并行查询，峰值 ${a.oracle.px_peak} 个并发。`)
  if (a.oracle.job_peak > 0) hints.push(`- 采样期内检测到 Job 队列调度，峰值 ${a.oracle.job_peak} 个并发。`)
  if ((a.grid.restart_count.asm_pmon ?? 0) > 0) hints.push(`- **Grid asm_pmon 重启 ${a.grid.restart_count.asm_pmon} 次**，建议检查 ASM 实例状态和 alert 日志。`)
  if ((a.grid.restart_count.cha ?? 0) > 0) hints.push(`- **Grid CHA（Cluster Health Advisor）重启 ${a.grid.restart_count.cha} 次**，建议检查 ohasd 日志。`)
  for (const [kind, cnt] of Object.entries(a.grid.restart_count)) {
    if (!['asm_pmon', 'cha'].includes(kind) && cnt > 0) {
      hints.push(`- **Grid ${kind} 重启 ${cnt} 次**。`)
    }
  }
  if (a.user_scripts.length > 0) {
    const names = a.user_scripts.map((s) => s.name).join('、')
    hints.push(`- 检测到 ${a.user_scripts.length} 类用户脚本执行：${names}。`)
  }
  for (const c of a.cpu_top.slice(0, 3)) {
    if (c.cpu_pct_max >= 100) {
      hints.push(`- **CPU 高占用**：${c.user} 用户的 \`${shortCmd(c.command, 40)}\` 峰值 ${c.cpu_pct_max.toFixed(1)}%（单核即可超 100%）。`)
    }
  }
  for (const m of a.mem_top.slice(0, 3)) {
    if (m.rss_max_kb >= 2 * 1024 * 1024) {
      hints.push(`- **内存高占用**：${m.user} 用户的 \`${shortCmd(m.command, 40)}\` RSS 峰值 ${formatKB(m.rss_max_kb)}（≥2G）。`)
    }
  }
  // 状态相关
  if (a.state.zombie_pids.length > 0) {
    hints.push(`- **发现 ${a.state.zombie_pids.length} 个持续 Zombie 进程**，父进程未回收。建议：\`ps -e -o pid,ppid,stat,command | grep ' Z '\` 定位父进程并检查是否有 wait/waitpid 漏调。`)
  }
  if (a.state.long_d_pids.length > 0) {
    hints.push(`- **发现 ${a.state.long_d_pids.length} 个持续 D 状态进程**（uninterruptible sleep），可能 I/O 阻塞。\`ps -e -o pid,stat,wchan,command | grep ' D '\` 查 wchan（内核等待点），结合 iostat 看磁盘 util/await。`)
  }
  if (a.state.max_z > 0) {
    hints.push(`- 采样期内 Zombie 进程峰值 ${a.state.max_z}。`)
  }
  if (a.state.max_d > 0) {
    hints.push(`- 采样期内 D 状态进程峰值 ${a.state.max_d}（瞬时 I/O 阻塞）。`)
  }
  // WCHAN 相关
  if (a.wchan.stuck_pids.length > 0) {
    const ioPids = a.wchan.stuck_pids.filter((p: any) => p.category === 'io').length
    const lockPids = a.wchan.stuck_pids.filter((p: any) => p.category === 'lock').length
    hints.push(`- **发现 ${a.wchan.stuck_pids.length} 个进程持续在 WCHAN 等待**（连续 ≥ 5 cycle）：io ${ioPids} 个 / lock ${lockPids} 个。建议 \`ps -e -o pid,user,wchan,command | sort\` 查看 wchan 字段。`)
  }
  // WCHAN top 异常检测
  const topWchanAbnormal = a.wchan.top_wchans.filter((tw: any) => tw.category === 'io' || tw.category === 'lock')
  if (topWchanAbnormal.length > 0) {
    const examples = topWchanAbnormal.slice(0, 3).map((tw: any) => `\`${tw.wchan}\`(${tw.count})`).join('、')
    hints.push(`- 出现 IO/Lock 类 WCHAN：${examples}。${topWchanAbnormal[0].count > 5000 ? '频次很高，建议排查底层 IO / 锁竞争。' : ''}`)
  }
  if (hints.length === 0) {
    hints.push('- 采样期内未发现明显异常，建议结合 iostat / netstat / vmstat 等其他 OSW 数据做综合分析。')
  }
  for (const h of hints) lines.push(h)
  lines.push('')
  lines.push('### 后续排查建议')
  lines.push('')
  lines.push('1. 如发现 Oracle 进程重启，对比同一时间段的 alert log / trace 文件。')
  lines.push('2. 如发现用户脚本执行与系统负载峰值重叠，结合 iostat 看是否触发 I/O 瓶颈。')
  lines.push('3. 如发现 Grid 重启，结合 ohasd 日志定位是 CRS 还是 OS 级别的问题。')
  lines.push('4. 单文件仅覆盖 1 小时窗口，建议结合其他时间段的 ps 数据看趋势。')
  lines.push('')
  lines.push('---')
  lines.push('')
  lines.push(`*本报告由 OSW-View 自动生成（${nowStr()}），源数据：oswps。*`)

  return lines.join('\n')
}

export function downloadMarkdown(content: string, filename: string): void {
  // BOM 让 Windows 记事本正确识别 UTF-8
  const blob = new Blob(['\uFEFF' + content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
