<script setup lang="ts">
/**
 * NetstatView · oswnetstat 可视化页面（Grafana 风格）
 *
 * 设计目标（OSW NetStat 可视化页面设计）：
 *   - 只做可视化展示，不做分析/告警/根因推断
 *   - 顶部固定：Overview 卡片（6 个统计指标）
 *   - 标签页：Traffic / Packets / Errors / TCP / IP / Interfaces
 *   - 深色主题（参考 Grafana）
 *
 * 流程：
 *   1. 加载文件 → /api/netstat/info（timestamps + 接口列表）
 *   2. /api/netstat/snapshot          → 当前时间点接口（Interfaces 页）
 *   3. /api/netstat/rates            → 流量/包/错误速率（Traffic/Packets/Errors 页）
 *   4. /api/netstat/kernel_landscape → kernel counter 时序（TCP/IP 页）
 */
import { ref, computed, onMounted, watch } from 'vue'
import { ApiError, commonApi } from '../api/common'
import {
  netstatApi,
  type NetstatInfoResponse,
  type NetstatSnapshotResponse,
  type NetstatRatesResponse,
  type NetstatKernelLandscapeResponse,
  type NetstatVersionInfo,
  type UnknownFormatDetail,
} from '../api/netstat'
import FileSelector from '../components/FileSelector.vue'
import UnknownFormatDialog from '../components/UnknownFormatDialog.vue'
import UploadResultDialog from '../components/UploadResultDialog.vue'
import TimelineChart from '../components/TimelineChart.vue'

// ─── 文件选择 + 分析入口 ─────────────────────────────
const dirPath = ref('')
const files = ref<string[]>([])
const selectedFile = ref<string | null>(null)
const analysis = ref<NetstatInfoResponse | null>(null)
const loading = ref(false)
const error = ref('')
const unknownFormatInfo = ref<UnknownFormatDetail | null>(null)

interface UploadedItem { original: string; saved_as: string; path: string }
interface FailedItem { filename: string; reason: string }
const uploadResult = ref<{ uploaded: UploadedItem[]; failed: FailedItem[] } | null>(null)

const supportedVersions = ref<NetstatVersionInfo[]>([])
onMounted(async () => {
  try {
    const res = await netstatApi.listNetstatVersions()
    supportedVersions.value = res.versions.filter((v) => v.active !== false)
  } catch {
    // 静默
  }
})

// ─── 时间点 + snapshot ─────────────────────────────
const currentCycleIndex = ref(0)
const snapshot = ref<NetstatSnapshotResponse | null>(null)
const snapshotLoading = ref(false)
const snapshotError = ref('')

const timestamps = computed<string[]>(() => analysis.value?.timestamps ?? [])
const totalCycles = computed(() => timestamps.value.length)
const interfaceNames = computed<string[]>(() => analysis.value?.interface_names ?? [])

// Interfaces tab 用：state 筛选 + 名称模糊搜索
type StateFilter = 'ALL' | 'UP' | 'DOWN' | 'UNKNOWN'
const stateFilter = ref<StateFilter>('ALL')
const nameFilter = ref<string>('')

// 拖 slider → 触发 snapshot 重载
watch(currentCycleIndex, async (idx) => {
  if (!analysis.value || idx < 0 || idx >= totalCycles.value) return
  await loadSnapshot(idx)
})

async function loadSnapshot(idx: number) {
  if (!analysis.value || !selectedFile.value) return
  snapshotLoading.value = true
  snapshotError.value = ''
  try {
    snapshot.value = await netstatApi.snapshot(dirPath.value, selectedFile.value, idx)
  } catch (e: any) {
    snapshotError.value = e?.message ?? String(e)
    snapshot.value = null
  } finally {
    snapshotLoading.value = false
  }
}

const currentTimestamp = computed(() => timestamps.value[currentCycleIndex.value] ?? '')

// Interfaces tab：state + 名称 双重过滤
const filteredInterfaces = computed(() => {
  if (!snapshot.value) return []
  const q = nameFilter.value.trim().toLowerCase()
  return snapshot.value.interfaces.filter((i) => {
    if (stateFilter.value !== 'ALL' && i.state !== stateFilter.value) return false
    if (q && !i.name.toLowerCase().includes(q)) return false
    return true
  })
})

// Interfaces tab：点击网卡 → 整个采集时间段的收发汇总
const selectedIface = ref<string | null>(null)
const ifaceSummary = computed(() => {
  const name = selectedIface.value
  if (!name || !rates.value) return null
  const ir = rates.value.interface_rates[name]
  if (!ir) return null
  const cycles = rates.value.cycle_count
  const totalRx = ir.rx_bytes_delta.reduce((a, b) => a + b, 0)
  const totalTx = ir.tx_bytes_delta.reduce((a, b) => a + b, 0)
  // 非零 cycle 数（排除 cycle[0] = 0 的人为填充）
  const validCycles = Math.max(cycles - 1, 1)
  // 当前 state（取自最近一个 snapshot）
  const cur = snapshot.value?.interfaces.find(i => i.name === name)
  return {
    name,
    state: cur?.state ?? 'UNKNOWN',
    mtu: cur?.mtu ?? 0,
    master: cur?.master ?? '',
    totalRx,
    totalTx,
    cycles,
    avgRx: totalRx / validCycles,
    avgTx: totalTx / validCycles,
    timeRange: rates.value.time_range,
  }
})

// 单网卡时序图（汇总面板用）
function buildSingleIfaceSeries(
  ifaceName: string,
  metricKey: 'rx_bytes_delta' | 'tx_bytes_delta',
): { name: string; data: [string, number][] }[] {
  if (!rates.value) return []
  const ir = rates.value.interface_rates[ifaceName]
  if (!ir) return []
  const tsList = rates.value.timestamps
  const series = ir[metricKey] as number[]
  return [{
    name: ifaceName,
    // 跳过 cycle[0]（人为 0）+ bytes 转 MB
    data: tsList.slice(1).map((t, idx) => [t, series[idx + 1] / (1024 * 1024)] as [string, number]),
  }]
}

// ─── 总统概览 tab：每接口 12 个累计计数器时序（不差分）──────
const ifaceTrends = ref<NetstatIfaceTrendsResponse | null>(null)
const ifaceTrendsLoading = ref(false)
const ifaceTrendsError = ref('')

async function loadIfaceTrends() {
  if (!analysis.value || !selectedFile.value) return
  ifaceTrendsLoading.value = true
  ifaceTrendsError.value = ''
  try {
    ifaceTrends.value = await netstatApi.ifaceTrends(dirPath.value, selectedFile.value)
    // 数据加载完后自动选中前 10 个接口（这样 chip 才有 active 视觉反馈）
    if (ifaceTrends.value && ifaceTrends.value.interface_names.length > 0) {
      selectedOverviewIfaces.value = ifaceTrends.value.interface_names.slice(0, 10)
    }
  } catch (e: any) {
    ifaceTrendsError.value = e?.message ?? String(e)
    ifaceTrends.value = null
  } finally {
    ifaceTrendsLoading.value = false
  }
}

// 12 个累计计数器（与后端 IFACE_METRICS 一致）
const IFACE_RX_METRICS = [
  { key: 'rx_bytes', label: 'bytes', unit: '字节', valueType: 'decimal' as const, desc: '累计接收字节数' },
  { key: 'rx_packets', label: 'packets', unit: '包数', valueType: 'integer' as const, desc: '累计接收包数' },
  { key: 'rx_errors', label: 'errors', unit: '次', valueType: 'integer' as const, desc: '累计接收错误包' },
  { key: 'rx_dropped', label: 'dropped', unit: '次', valueType: 'integer' as const, desc: '累计接收丢弃包' },
  { key: 'rx_missed', label: 'missed', unit: '次', valueType: 'integer' as const, desc: '累计接收遗漏包（网卡层）' },
  { key: 'rx_mcast', label: 'mcast', unit: '次', valueType: 'integer' as const, desc: '累计组播包' },
] as const
const IFACE_TX_METRICS = [
  { key: 'tx_bytes', label: 'bytes', unit: '字节', valueType: 'decimal' as const, desc: '累计发送字节数' },
  { key: 'tx_packets', label: 'packets', unit: '包数', valueType: 'integer' as const, desc: '累计发送包数' },
  { key: 'tx_errors', label: 'errors', unit: '次', valueType: 'integer' as const, desc: '累计发送错误包' },
  { key: 'tx_dropped', label: 'dropped', unit: '次', valueType: 'integer' as const, desc: '累计发送丢弃包' },
  { key: 'tx_carrier', label: 'carrier', unit: '次', valueType: 'integer' as const, desc: '累计发送 carrier 错误' },
  { key: 'tx_collsns', label: 'collsns', unit: '次', valueType: 'integer' as const, desc: '累计发送冲突' },
] as const

// 12 个指标（按用户的 RX/TX 分组展示，chip 多选）
const IFACE_ALL_METRICS = [
  ...IFACE_RX_METRICS.map(m => ({ ...m, group: 'RX' as const })),
  ...IFACE_TX_METRICS.map(m => ({ ...m, group: 'TX' as const })),
]

// 总统概览 tab：默认全选 12 指标
const selectedOverviewMetrics = ref<string[]>(
  IFACE_ALL_METRICS.map(m => m.key),
)

// 总统概览 tab：默认前 10 个接口
const selectedOverviewIfaces = ref<string[]>([])

// 总统概览 tab：不差分，直接显示累计值
function buildIfaceMetricSeries(metricKey: string): { name: string; data: [string, number][] }[] {
  if (!ifaceTrends.value) return []
  const ifaces = overviewIfaces.value
  const out: { name: string; data: [string, number][] }[] = []
  for (const iface of ifaces) {
    const s = ifaceTrends.value.series.find((x) => x.name === `${iface}/${metricKey}`)
    if (!s) continue
    out.push({ name: iface, data: s.data })
  }
  return out
}

// 总统概览 tab：选中的接口（首次加载自动填前 10）
const overviewIfaces = computed(() => selectedOverviewIfaces.value)

// ─── 速率数据（Traffic / Packets / Errors 页用）────────
const rates = ref<NetstatRatesResponse | null>(null)
const ratesLoading = ref(false)
const ratesError = ref('')

async function loadRates() {
  if (!analysis.value || !selectedFile.value) return
  ratesLoading.value = true
  ratesError.value = ''
  try {
    rates.value = await netstatApi.rates(dirPath.value, selectedFile.value)
  } catch (e: any) {
    ratesError.value = e?.message ?? String(e)
    rates.value = null
  } finally {
    ratesLoading.value = false
  }
}

// ─── kernel counter 时序（TCP / IP 页用）────────────
const kernelData = ref<NetstatKernelLandscapeResponse | null>(null)
const kernelLoading = ref(false)
const kernelError = ref('')

const TCP_METRICS = [
  // ── TCP 基础 ──
  { key: 'TcpInSegs', label: 'TcpInSegs (入站段)', desc: '收到的 TCP 段，反映 TCP 接收流量规模' },
  { key: 'TcpOutSegs', label: 'TcpOutSegs (出站段)', desc: '发出的 TCP 段，反映 TCP 发送流量规模' },
  { key: 'TcpActiveOpens', label: 'TcpActiveOpens (主动连接)', desc: '本机主动发起的 TCP 连接（数据库访问远程）' },
  { key: 'TcpPassiveOpens', label: 'TcpPassiveOpens (被动连接)', desc: '本机接受的 TCP 连接（客户端连 Oracle）' },
  { key: 'TcpAttemptFails', label: 'TcpAttemptFails (连接失败)', desc: 'TCP 连接建立失败：目标未监听/防火墙/服务异常' },
  { key: 'TcpEstabResets', label: 'TcpEstabResets (已建重置)', desc: '已建立连接被重置：Connection reset / ORA-03135' },
  { key: 'TcpOutRsts', label: 'TcpOutRsts (出站 RST)', desc: '发出的 RST 段数' },
  { key: 'TcpInErrs', label: 'TcpInErrs (入站错误)', desc: '入站 TCP 错误' },
  // ── TCP 扩展（网络质量核心）──
  { key: 'TcpRetransSegs', label: 'TcpRetransSegs (TCP重传)', desc: 'TCP 重传数，网络质量核心指标：<1%正常, 1-3%关注, >5%异常' },
  { key: 'TcpExtTCPTimeouts', label: 'TcpExtTCPTimeouts (TCP超时)', desc: 'TCP 等待确认超时：延迟过大或丢包' },
  { key: 'TcpExtTCPSynRetrans', label: 'TcpExtTCPSynRetrans (SYN重传)', desc: '三次握手期间重传：连接建立质量' },
  { key: 'TcpExtTCPLostRetrans', label: 'TcpExtTCPLostRetrans (重传再丢)', desc: '重传后的包再次丢失：严重网络异常' },
  { key: 'TcpExtTCPOFOQueue', label: 'TcpExtTCPOFOQueue (乱序包)', desc: '乱序到达的包：网络路径不稳定，RAC/DRBD 重点' },
  { key: 'TcpExtListenOverflows', label: 'TcpExtListenOverflows (监听溢出)', desc: '服务端监听队列溢出：连接请求过多' },
  { key: 'TcpExtListenDrops', label: 'TcpExtListenDrops (监听丢弃)', desc: '连接请求被直接丢弃：系统连接压力过大' },
  { key: 'TcpExtTCPBacklogDrop', label: 'TcpExtTCPBacklogDrop (Backlog丢弃)', desc: 'TCP 等待队列中的连接被丢弃' },
  { key: 'TcpExtTCPMemoryPressures', label: 'TcpExtTCPMemoryPressures (TCP内存压力)', desc: 'TCP 协议栈内存不足，正常应保持 0' },
] as const

const IP_METRICS = [
  // ── IPv4 ──
  { key: 'IpInReceives', label: 'IpInReceives (入站包)', desc: '收到的 IPv4 包总数，反映整体流量规模' },
  { key: 'IpOutRequests', label: 'IpOutRequests (出站包)', desc: '发出的 IPv4 包总数，反映系统输出规模' },
  { key: 'IpInDelivers', label: 'IpInDelivers (交付包)', desc: '成功交付给上层协议（TCP/UDP/ICMP）的包' },
  { key: 'IpInHdrErrors', label: 'IpInHdrErrors (头错误)', desc: 'IP 头错误：网卡/链路/驱动问题' },
  { key: 'IpInAddrErrors', label: 'IpInAddrErrors (地址错误)', desc: '目标地址无效的包：错误路由/异常广播' },
  { key: 'IpInDiscards', label: 'IpInDiscards (入站丢弃)', desc: '收到但丢弃的包（系统问题非网络问题）' },
  { key: 'IpOutDiscards', label: 'IpOutDiscards (出站丢弃)', desc: '发送前丢弃：系统压力/内存不足/队列拥塞' },
  { key: 'IpOutNoRoutes', label: 'IpOutNoRoutes (无路由)', desc: '找不到目标路由：No route to host' },
  { key: 'IpReasmReqds', label: 'IpReasmReqds (分片重组请求)', desc: '需要重组的分片包数' },
  { key: 'IpReasmOKs', label: 'IpReasmOKs (分片重组成功)', desc: '成功重组的包数' },
  { key: 'IpReasmFails', label: 'IpReasmFails (分片重组失败)', desc: '重组失败：超时/丢失分片，MTU 不匹配' },
  { key: 'IpFragCreates', label: 'IpFragCreates (分片创建)', desc: '被分片的包数' },
  // ── IPv6 ──
  { key: 'Ip6InReceives', label: 'Ip6InReceives (IPv6入站)', desc: '收到的 IPv6 包总数' },
  { key: 'Ip6OutRequests', label: 'Ip6OutRequests (IPv6出站)', desc: '发出的 IPv6 包总数' },
  { key: 'Ip6InDelivers', label: 'Ip6InDelivers (IPv6交付)', desc: '成功交付给上层的 IPv6 包' },
  { key: 'Ip6InHdrErrors', label: 'Ip6InHdrErrors (IPv6头错误)', desc: 'IPv6 头错误' },
  { key: 'Ip6InDiscards', label: 'Ip6InDiscards (IPv6入站丢弃)', desc: 'IPv6 入站丢弃' },
  { key: 'Ip6OutNoRoutes', label: 'Ip6OutNoRoutes (IPv6无路由)', desc: 'IPv6 找不到路由' },
  { key: 'Ip6ReasmFails', label: 'Ip6ReasmFails (IPv6分片失败)', desc: 'IPv6 分片重组失败' },
  // ── ICMP / ICMP6 ──
  { key: 'IcmpInMsgs', label: 'IcmpInMsgs (ICMP入站)', desc: '收到的 ICMP 消息数（ping、unreachable 等）' },
  { key: 'IcmpOutMsgs', label: 'IcmpOutMsgs (ICMP出站)', desc: '发出的 ICMP 消息数' },
  { key: 'IcmpInEchos', label: 'IcmpInEchos (收到Ping请求)', desc: '其他主机向本机发 Ping 的次数' },
  { key: 'IcmpOutEchoReps', label: 'IcmpOutEchoReps (发送Ping响应)', desc: '本机回复 Ping 的次数（应与 InEchos 接近）' },
  { key: 'IcmpInDestUnreachs', label: 'IcmpInDestUnreachs (收到不可达)', desc: '收到目标不可达消息：网络中存在连接失败' },
  { key: 'IcmpOutDestUnreachs', label: 'IcmpOutDestUnreachs (发送不可达)', desc: '本机发送目标不可达：有人访问不存在的服务' },
  { key: 'IcmpInErrors', label: 'IcmpInErrors (ICMP入站错误)', desc: '收到的 ICMP 错误消息' },
  { key: 'IcmpOutErrors', label: 'IcmpOutErrors (ICMP出站错误)', desc: '发出的 ICMP 错误消息' },
  { key: 'Icmp6InMsgs', label: 'Icmp6InMsgs (ICMP6入站)', desc: '收到的 ICMPv6 消息数（含 NDP 邻居发现）' },
  { key: 'Icmp6OutMsgs', label: 'Icmp6OutMsgs (ICMP6出站)', desc: '发出的 ICMPv6 消息数' },
  { key: 'Icmp6InErrors', label: 'Icmp6InErrors (ICMP6入站错误)', desc: 'ICMPv6 入站错误' },
  { key: 'Icmp6OutErrors', label: 'Icmp6OutErrors (ICMP6出站错误)', desc: 'ICMPv6 出站错误' },
  // ── UDP / UDP6 ──
  { key: 'UdpInDatagrams', label: 'UdpInDatagrams (UDP入站)', desc: '收到的 UDP 数据报' },
  { key: 'UdpOutDatagrams', label: 'UdpOutDatagrams (UDP出站)', desc: '发出的 UDP 数据报' },
  { key: 'UdpNoPorts', label: 'UdpNoPorts (UDP无端口)', desc: '收到但无应用监听的 UDP 包：服务未启动' },
  { key: 'UdpInErrors', label: 'UdpInErrors (UDP入站错误)', desc: 'UDP 入站错误（除校验和外），正常应保持 0' },
  { key: 'UdpRcvbufErrors', label: 'UdpRcvbufErrors (UDP接收缓冲)', desc: '接收缓冲区不足导致丢包，RAC 重点' },
  { key: 'UdpSndbufErrors', label: 'UdpSndbufErrors (UDP发送缓冲)', desc: '发送缓冲区不足：系统发送压力大' },
  { key: 'Udp6InDatagrams', label: 'Udp6InDatagrams (UDP6入站)', desc: '收到的 UDP6 数据报' },
  { key: 'Udp6OutDatagrams', label: 'Udp6OutDatagrams (UDP6出站)', desc: '发出的 UDP6 数据报' },
  { key: 'Udp6NoPorts', label: 'Udp6NoPorts (UDP6无端口)', desc: 'UDP6 无应用监听' },
  { key: 'Udp6InErrors', label: 'Udp6InErrors (UDP6入站错误)', desc: 'UDP6 入站错误' },
] as const

// IP 指标按诊断目的分组（每组一张图）
const IP_GROUPS = [
  {
    title: '流量',
    desc: 'IPv4 包收发量',
    metrics: ['IpInReceives', 'IpOutRequests', 'IpInDelivers'],
  },
  {
    title: '错误/丢包',
    desc: 'IP 层错误与丢包计数',
    metrics: ['IpInHdrErrors', 'IpInAddrErrors', 'IpInDiscards', 'IpOutDiscards', 'IpOutNoRoutes'],
  },
  {
    title: '分片',
    desc: 'IP 分片与重组统计',
    metrics: ['IpReasmReqds', 'IpReasmOKs', 'IpReasmFails', 'IpFragCreates'],
  },
]

// IPv6 单独组
const IP6_GROUPS = [
  {
    title: 'IPv6 流量',
    desc: 'IPv6 包收发量',
    metrics: ['Ip6InReceives', 'Ip6OutRequests', 'Ip6InDelivers'],
  },
  {
    title: 'IPv6 错误/丢包',
    desc: 'IPv6 层错误与丢包',
    metrics: ['Ip6InHdrErrors', 'Ip6InDiscards', 'Ip6OutNoRoutes'],
  },
  {
    title: 'IPv6 分片',
    desc: 'IPv6 分片重组失败',
    metrics: ['Ip6ReasmFails'],
  },
]

// ICMP 单独 tab（IPv4 + IPv6）
const ICMP_GROUPS = [
  {
    title: 'ICMP (IPv4)',
    desc: 'ICMP 消息收发量',
    metrics: ['IcmpInMsgs', 'IcmpOutMsgs', 'IcmpInEchos', 'IcmpOutEchoReps', 'IcmpInDestUnreachs', 'IcmpOutDestUnreachs', 'IcmpInErrors', 'IcmpOutErrors'],
  },
  {
    title: 'ICMPv6',
    desc: 'ICMPv6 消息收发量',
    metrics: ['Icmp6InMsgs', 'Icmp6OutMsgs', 'Icmp6InErrors', 'Icmp6OutErrors'],
  },
]

// UDP 单独 tab（IPv4 + IPv6）
const UDP_GROUPS = [
  {
    title: 'UDP (IPv4)',
    desc: 'UDP 数据报收发量',
    metrics: ['UdpInDatagrams', 'UdpOutDatagrams', 'UdpNoPorts', 'UdpInErrors', 'UdpRcvbufErrors', 'UdpSndbufErrors'],
  },
  {
    title: 'UDP6',
    desc: 'UDP6 数据报收发量',
    metrics: ['Udp6InDatagrams', 'Udp6OutDatagrams', 'Udp6NoPorts', 'Udp6InErrors'],
  },
]

// TCP 分组（按诊断目的，不分 v4/v6 因为 TCP 是单层协议）
const TCP_GROUPS = [
  {
    title: 'TCP 基础流量',
    desc: 'TCP 段收发量',
    metrics: ['TcpInSegs', 'TcpOutSegs'],
  },
  {
    title: 'TCP 连接',
    desc: 'TCP 连接建立/失败/重置',
    metrics: ['TcpActiveOpens', 'TcpPassiveOpens', 'TcpAttemptFails', 'TcpEstabResets', 'TcpOutRsts', 'TcpInErrs'],
  },
  {
    title: 'TCP 重传',
    desc: 'TCP 重传次数（含 SYN/重传再丢）',
    metrics: ['TcpRetransSegs', 'TcpExtTCPSynRetrans', 'TcpExtTCPLostRetrans'],
  },
  {
    title: 'TCP 扩展（网络质量核心）',
    desc: '超时/乱序/监听队列/内存压力',
    metrics: ['TcpExtTCPTimeouts', 'TcpExtTCPOFOQueue', 'TcpExtListenOverflows', 'TcpExtListenDrops', 'TcpExtTCPBacklogDrop', 'TcpExtTCPMemoryPressures'],
  },
]

// DBA 网络诊断已合并到 TCP/IP/ICMP/UDP tab（4 大类分散在各协议 tab），DBA_DIAGNOSIS_GROUPS 不再使用

function groupHint(title: string): string {
  const hints: Record<string, string> = {
    '流量概览': '入站包 ≈ 交付包 + 丢弃包；斜率 = 流量大小',
    '流量': '入站包 ≈ 交付包 + 丢弃包；斜率 = 流量大小',
    '丢包与路由': '正常应为 0 或接近 0；非零说明有网络问题',
    '错误/丢包': '正常应为 0；非零需查链路或驱动（hdrErrors）或路由（noRoutes）',
    '分片': '分片失败非零 = 网络 MTU 不匹配或丢包',
    'IPv6 流量': 'IPv6 包收发量；如系统不用 IPv6 应全为 0',
    'IPv6 错误/丢包': 'IPv6 头错误/丢弃/无路由；正常应为 0',
    'IPv6 分片': 'IPv6 分片重组失败；正常应为 0',
    'ICMP (IPv4)': 'ICMP 消息量；ping 多则此图高',
    'ICMPv6': 'ICMPv6 消息量（含 NDP 邻居发现）',
    'UDP (IPv4)': 'UDP 流量；无端口非零 = 应用未监听',
    'UDP6': 'UDP6 流量；无端口非零 = 应用未监听',
    'TCP 基础流量': 'TCP 段收发量，反映 TCP 流量规模',
    'TCP 连接': '连接建立/失败/重置；attemptFails/estabResets 持续增长需关注',
    'TCP 重传': '核心网络质量指标：<1%正常, 1-3%关注, >5%异常',
    'TCP 扩展（网络质量核心）': '超时/乱序/监听溢出/内存压力；RAC/DRBD 重点关注',
  }
  return hints[title] || ''
}

async function loadKernel(metrics: string[]) {
  if (!analysis.value || !selectedFile.value || metrics.length === 0) {
    kernelData.value = null
    return
  }
  kernelLoading.value = true
  kernelError.value = ''
  try {
    kernelData.value = await netstatApi.kernelLandscape(dirPath.value, selectedFile.value, metrics)
  } catch (e: any) {
    kernelError.value = e?.message ?? String(e)
    kernelData.value = null
  } finally {
    kernelLoading.value = false
  }
}

// 一次性加载所有指标（不再做 chip 动态切换）
const activeMetrics = ref<string[]>([
  ...TCP_METRICS.map(m => m.key),
  ...IP_GROUPS.flatMap(g => g.metrics),
  ...IP6_GROUPS.flatMap(g => g.metrics),
  ...ICMP_GROUPS.flatMap(g => g.metrics),
  ...UDP_GROUPS.flatMap(g => g.metrics),
])

// ─── Overview 卡片数据 ────────────────────────
const overview = computed(() => {
  if (!rates.value) {
    return {
      totalRxBytes: 0,
      totalTxBytes: 0,
      totalRxRate: 0,
      totalTxRate: 0,
      tcpConn: 0,
      tcpRetrans: 0,
      networkDrops: 0,
      activeIfaces: 0,
    }
  }
  const r = rates.value

  // 累计字节（首末 cycle 差值）— 直接从后端拿
  const totalRxBytes = r.total_rx_bytes
  const totalTxBytes = r.total_tx_bytes

  // 最近 30s 窗口的差值（最后一个 cycle 的 delta）— 反映"刚刚"收了/发多少
  const last = r.timestamps.length - 1
  let lastRxDelta = 0, lastTxDelta = 0
  for (const name in r.interface_rates) {
    const ir = r.interface_rates[name]
    lastRxDelta += ir.rx_bytes_delta[last] || 0
    lastTxDelta += ir.tx_bytes_delta[last] || 0
  }

  // TCP Connections = TcpActiveOpens + TcpPassiveOpens（累计打开连接数）
  const kc = r.last_kernel_counters || {}
  const tcpConn = (kc['TcpActiveOpens'] || 0) + (kc['TcpPassiveOpens'] || 0)
  // TCP Retransmissions = TcpRetransSegs（累计重传段数）
  const tcpRetrans = kc['TcpRetransSegs'] || 0

  return {
    totalRxBytes,
    totalTxBytes,
    lastRxDelta,
    lastTxDelta,
    tcpConn,
    tcpRetrans,
    activeIfaces: Object.keys(r.interface_rates).length,
  }
})

// ─── 当前 tab（默认 Traffic）────────────────────────
type Tab = 'overview' | 'traffic' | 'tcp' | 'ip' | 'icmp' | 'udp' | 'interfaces'
const activeTab = ref<Tab>('overview')

const tabs: { key: Tab; label: string }[] = [
  { key: 'overview', label: '总统概览' },
  { key: 'traffic', label: 'Traffic' },
  { key: 'tcp', label: 'TCP' },
  { key: 'ip', label: 'IP' },
  { key: 'icmp', label: 'ICMP' },
  { key: 'udp', label: 'UDP' },
  { key: 'interfaces', label: 'Interfaces' },
]

// ─── 工具函数 ─────────────────────────────────────
function formatBytes(bytes: number, decimals: number = 2): string {
  // 把字节数格式化成 KB/MB/GB
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(decimals)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(decimals)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(decimals)} KB`
  return `${bytes} B`
}

function formatCount(n: number): string {
  // 大数自动用万/亿简写（与图表 Y 轴一致）
  const abs = Math.abs(n)
  if (abs >= 1e8) return `${(n / 1e8).toFixed(1)}亿`
  if (abs >= 1e4) return `${(n / 1e4).toFixed(1)}万`
  return n.toLocaleString()
}

/**
 * 把每个接口的 bytes 差值序列转成 ECharts series
 * - bytes → MB（÷ 1024²），单位标 " MB"
 * - 跳过 cycle[0]（人为填的 0）
 */
function buildBytesSeries(
  ifaceNames: string[],
  metricKey: 'rx_bytes_delta' | 'tx_bytes_delta',
): { name: string; data: [string, number][] }[] {
  if (!rates.value) return []
  const out: { name: string; data: [string, number][] }[] = []
  const tsList = rates.value.timestamps
  for (const name of ifaceNames) {
    const ir = rates.value.interface_rates[name]
    if (!ir) continue
    const series = ir[metricKey] as number[]
    out.push({
      name,
      // 跳过 cycle[0]（人为 0）+ bytes 转 MB
      data: tsList.slice(1).map((t, idx) => [t, series[idx + 1] / (1024 * 1024)] as [string, number]),
    })
  }
  return out
}

function buildKernelSeries(metricKeys: string[]): { name: string; data: [string, number][] }[] {
  if (!kernelData.value) return []
  const allMetrics = [...TCP_METRICS, ...IP_METRICS]
  return metricKeys
    .map((k) => {
      const s = kernelData.value!.series.find((s) => s.name === k)
      if (!s) return null
      const label = allMetrics.find(m => m.key === k)?.label ?? k
      return { name: label, data: s.data }
    })
    .filter((s): s is { name: string; data: [string, number][] } => Boolean(s))
}

/**
 * 把 kernel counter 的累计值转成差值（每个窗口的增量，不除以时间）
 */
function buildKernelDeltaSeries(metricKeys: string[]): { name: string; data: [string, number][] }[] {
  if (!kernelData.value) return []
  const allMetrics = [...TCP_METRICS, ...IP_METRICS]
  const seriesMap = new Map(kernelData.value.series.map((s) => [s.name, s]))
  const result: { name: string; data: [string, number][] }[] = []
  for (const key of metricKeys) {
    const s = seriesMap.get(key)
    if (!s || !s.data.length) continue
    const deltas: [string, number][] = []
    for (let i = 1; i < s.data.length; i++) {
      const ts = s.data[i][0]
      const delta = Math.max(s.data[i][1] - s.data[i - 1][1], 0)
      deltas.push([ts, delta])
    }
    const label = allMetrics.find(m => m.key === key)?.label ?? key
    result.push({ name: label, data: deltas })
  }
  return result
}

// ─── 文件 IO ─────────────────────────────────────

async function scan() {
  if (!dirPath.value.trim()) return
  loading.value = true
  error.value = ''
  unknownFormatInfo.value = null
  try {
    const res = await netstatApi.scan(dirPath.value.trim(), 'netstat')
    files.value = res.files
    selectedFile.value = null
    analysis.value = null
    snapshot.value = null
    rates.value = null
    kernelData.value = null
  } catch (e: any) {
    error.value = e?.message ?? String(e)
  } finally {
    loading.value = false
  }
}

async function scanUploadDir() {
  loading.value = true
  error.value = ''
  unknownFormatInfo.value = null
  try {
    const res = await netstatApi.scan('', 'netstat')
    dirPath.value = res.scanned_dir
    files.value = res.files
    selectedFile.value = null
    analysis.value = null
    snapshot.value = null
    rates.value = null
    kernelData.value = null
    if (res.cleaned_count > 0) {
      console.info(`[cleanup] 已清理 ${res.cleaned_count} 个超过 7 天的过期文件`)
    }
  } catch (e: any) {
    error.value = e?.message ?? String(e)
  } finally {
    loading.value = false
  }
}

async function onUpload(e: Event) {
  const target = e.target as HTMLInputElement
  if (!target.files || target.files.length === 0) return
  loading.value = true
  error.value = ''
  try {
    const res = await commonApi.uploadFiles(target.files, 'netstat')
    console.info(`[upload] 成功 ${res.uploaded_count} 个，失败 ${res.failed_count} 个`)
    if (res.uploaded_count > 0 || res.failed_count > 0) {
      uploadResult.value = { uploaded: res.uploaded, failed: res.failed }
    }
    if (res.uploaded_count > 0) {
      await scanUploadDir()
    }
  } catch (e: any) {
    error.value = e?.message ?? String(e)
  } finally {
    target.value = ''
    loading.value = false
  }
}

async function runAnalysis() {
  if (!selectedFile.value) return
  loading.value = true
  error.value = ''
  unknownFormatInfo.value = null
  try {
    analysis.value = await netstatApi.info(dirPath.value, selectedFile.value)
    currentCycleIndex.value = 0
    activeTab.value = 'overview'  // 重新分析后默认切到总统概览
    stateFilter.value = 'ALL'
    nameFilter.value = ''
    selectedOverviewIfaces.value = []
    // Traffic tab 默认前 3 个接口（保证 chip 有 active 视觉反馈）
    selectedTrafficIfaces.value = (analysis.value?.interface_names ?? []).slice(0, DEFAULT_VISIBLE_COUNT)
    ifaceTrends.value = null
    if (analysis.value) {
      await Promise.all([
        loadSnapshot(0),
        loadRates(),
        loadKernel(activeMetrics.value),
        loadIfaceTrends(),
      ])
    }
  } catch (e: any) {
    if (e instanceof ApiError && e.status === 422) {
      const detail = e.detail as UnknownFormatDetail | undefined
      if (detail && (detail as any).error === 'unknown_format') {
        unknownFormatInfo.value = detail
        loading.value = false
        return
      }
    }
    error.value = e?.message ?? String(e)
  } finally {
    loading.value = false
  }
}

function onFileToggle(f: string) {
  selectedFile.value = selectedFile.value === f ? null : f
}
function onSelectAll() {
  if (files.value.length > 0) selectedFile.value = files.value[0]
}
function onDeselectAll() {
  selectedFile.value = null
}

// ─── 网卡筛选（chip 多选，空 = 全部）────────────────
// 图表默认显示前 3 个接口；点 chip 选过则用选中的
const DEFAULT_VISIBLE_COUNT = 3
const selectedTrafficIfaces = ref<string[]>([])  // 数据加载时自动填前 3
function toggleTrafficIface(name: string) {
  const idx = selectedTrafficIfaces.value.indexOf(name)
  if (idx >= 0) selectedTrafficIfaces.value.splice(idx, 1)
  else selectedTrafficIfaces.value.push(name)
}
function resetTrafficIfaceFilter() {
  selectedTrafficIfaces.value = interfaceNames.value.slice(0, DEFAULT_VISIBLE_COUNT)
}
const trafficIfaces = computed(() => selectedTrafficIfaces.value)

// 总统概览 tab：chip 多选网卡
function toggleOverviewIface(name: string) {
  const idx = selectedOverviewIfaces.value.indexOf(name)
  if (idx >= 0) selectedOverviewIfaces.value.splice(idx, 1)
  else selectedOverviewIfaces.value.push(name)
}

// 总统概览 tab：chip 多选指标
function toggleOverviewMetric(key: string) {
  const idx = selectedOverviewMetrics.value.indexOf(key)
  if (idx >= 0) selectedOverviewMetrics.value.splice(idx, 1)
  else selectedOverviewMetrics.value.push(key)
}

// 根据 metric key 查 label（带 RX/TX 前缀）
function ifaceMetricLabel(key: string): string {
  const m = IFACE_ALL_METRICS.find(x => x.key === key)
  return m ? `${m.group} ${m.label}` : key
}

// 根据 metric key 查 desc
function ifaceMetricDesc(key: string): string {
  const m = IFACE_ALL_METRICS.find(x => x.key === key)
  return m?.desc ?? ''
}

// 根据 metric key 查 unit（Y 轴单位）
function ifaceMetricUnit(key: string): string {
  const m = IFACE_ALL_METRICS.find(x => x.key === key)
  return m?.unit ?? ''
}

// 根据 metric key 查 valueType（Y 轴整数/小数模式）
function ifaceMetricValueType(key: string): 'integer' | 'decimal' {
  const m = IFACE_ALL_METRICS.find(x => x.key === key)
  return (m as any)?.valueType ?? 'integer'
}

// ─── TCP / IP metric chip（已废弃：TCP/IP/ICMP/UDP tab 不再做 chip 切换，全量展示）────────────────────
</script>

<template>
  <div class="netstat-view">
    <!-- 顶部 header + 工具栏 -->
    <header class="header">
      <div v-if="supportedVersions.length" class="version-hint">
        <span class="version-hint-label">已支持 {{ supportedVersions.length }} 个 netstat 格式版本：</span>
        <span
          v-for="v in supportedVersions"
          :key="v.version"
          class="version-tag"
          :title="`${v.display_name}\n${v.notes || ''}`"
        >{{ v.version }}</span>
      </div>
    </header>

    <section class="section path-section">
      <div class="path-row">
        <input
          v-model="dirPath"
          type="text"
          class="path-input"
          placeholder="输入 OSW netstat 数据目录路径（留空扫描上传目录 oswupdownload_file/netstat/）"
          @keyup.enter="scan"
        />
        <button class="btn" :disabled="loading" @click="scan">刷新</button>
        <button class="btn" :disabled="loading" @click="scanUploadDir">扫描上传目录</button>
        <label
          class="btn btn-success"
          :class="{ disabled: loading }"
          title="上传 .dat / .dat.gz 文件到后端"
        >
          上传文件
          <input
            type="file"
            multiple
            accept=".dat,.dat.gz"
            style="display: none"
            :disabled="loading"
            @change="onUpload"
          />
        </label>
        <button
          class="btn btn-primary"
          :disabled="loading || !selectedFile"
          @click="runAnalysis"
        >
          {{ analysis ? '重新分析' : '分析' }}
        </button>
      </div>
      <div v-if="loading" class="loading">分析中（首次 ~1s，缓存命中瞬时）...</div>
      <div v-if="error" class="error">{{ error }}</div>
      <div v-if="dirPath" class="current-dir">当前目录：<code>{{ dirPath }}</code></div>
    </section>

    <section v-if="files.length" class="section">
      <h2>文件列表（已选 {{ selectedFile ? 1 : 0 }} / 共 {{ files.length }}）</h2>
      <FileSelector
        :files="files"
        :selected="selectedFile ? [selectedFile] : []"
        @toggle="onFileToggle"
        @select-all="onSelectAll"
        @deselect-all="onDeselectAll"
      />
    </section>

    <template v-if="analysis && totalCycles > 0">
      <!-- 顶部 Overview 卡片（固定） -->
      <section class="section overview-section">
        <h2>Overview</h2>
        <div class="card-grid overview-cards">
          <div class="stat-card">
            <div class="stat-label">总接收流量</div>
            <div class="stat-value">{{ formatCount(overview.totalRxBytes / 1024 / 1024) }} <span class="unit">MB</span></div>
            <div class="stat-sub">最近 30s 窗口: {{ formatBytes(overview.lastRxDelta) }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">总发送流量</div>
            <div class="stat-value">{{ formatCount(overview.totalTxBytes / 1024 / 1024) }} <span class="unit">MB</span></div>
            <div class="stat-sub">最近 30s 窗口: {{ formatBytes(overview.lastTxDelta) }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">TCP Connections</div>
            <div class="stat-value">{{ formatCount(overview.tcpConn) }}</div>
            <div class="stat-sub">TcpActiveOpens + TcpPassiveOpens 累计</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">TCP Retransmissions</div>
            <div class="stat-value">{{ formatCount(overview.tcpRetrans) }}</div>
            <div class="stat-sub">TcpRetransSegs 累计</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Active Interfaces</div>
            <div class="stat-value">{{ overview.activeIfaces }}</div>
            <div class="stat-sub">共 {{ interfaceNames.length }} 个接口</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">采样周期</div>
            <div class="stat-value">{{ totalCycles }}</div>
            <div class="stat-sub">{{ analysis.time_range.start }} → {{ analysis.time_range.end }}</div>
          </div>
        </div>
      </section>

      <!-- 标签导航 -->
      <nav class="tab-bar">
        <button
          v-for="t in tabs"
          :key="t.key"
          class="tab-btn"
          :class="{ active: activeTab === t.key }"
          @click="activeTab = t.key"
        >{{ t.label }}</button>
      </nav>

      <!-- Traffic -->
      <section v-if="activeTab === 'traffic'" class="section">
        <h2>Traffic — 每个采样窗口的 RX/TX 收发量 (MB)</h2>
        <p class="section-desc">
          横坐标 = 时间，纵坐标 = 每个 ~30s 窗口内该接口实际收发的字节数。
          <strong>计算依据：数据源 = Linux 内核 <code>/proc/net/dev</code> 累计计数器</strong>。
          相邻 cycle 计数器差值（counter[i] - counter[i-1]）= 该窗口内实际收发的字节数，再 ÷ 1024² 转 MB。
        </p>
        <div class="filter-block">
          <span class="metric-picker-label">
            <template v-if="selectedTrafficIfaces.length > 0">
              已选 {{ selectedTrafficIfaces.length }} / 共 {{ interfaceNames.length }} 个：
            </template>
            <template v-else>
              默认前 {{ DEFAULT_VISIBLE_COUNT }} / 共 {{ interfaceNames.length }} 个：
            </template>
          </span>
          <div class="metric-chips">
            <button
              v-for="name in interfaceNames"
              :key="name"
              class="metric-chip"
              :class="{ active: selectedTrafficIfaces.includes(name) }"
              @click="toggleTrafficIface(name)"
            >{{ name }}</button>
            <button
              v-if="selectedTrafficIfaces.length !== interfaceNames.length"
              class="metric-chip clear-chip"
              @click="resetTrafficIfaceFilter"
              title="恢复默认（前 3 个）"
            >默认</button>
            <button
              v-if="selectedTrafficIfaces.length > 0"
              class="metric-chip clear-chip"
              @click="selectedTrafficIfaces = []"
              title="清空选择"
            >清空</button>
          </div>
        </div>
        <div v-if="ratesLoading" class="loading">加载中...</div>
        <div v-if="ratesError" class="error">{{ ratesError }}</div>
        <div v-if="rates && trafficIfaces.length" class="charts-grid">
          <div class="chart-cell">
            <div class="chart-annotation">
              <span class="annotation-title">RX Bytes / 采样窗口</span>
              <span class="annotation-desc">每 ~30s 窗口的累计字节数差值</span>
              <code class="annotation-formula">Δ = counter[i] - counter[i-1]（÷ 1024² 转 MB）</code>
            </div>
            <TimelineChart
              title="RX Bytes / 采样窗口"
              :series="buildBytesSeries(trafficIfaces, 'rx_bytes_delta')"
              unit="MB"
              value-type="decimal"
              :height="380"
            />
          </div>
          <div class="chart-cell">
            <div class="chart-annotation">
              <span class="annotation-title">TX Bytes / 采样窗口</span>
              <span class="annotation-desc">每 ~30s 窗口的累计字节数差值</span>
              <code class="annotation-formula">Δ = counter[i] - counter[i-1]（÷ 1024² 转 MB）</code>
            </div>
            <TimelineChart
              title="TX Bytes / 采样窗口"
              :series="buildBytesSeries(trafficIfaces, 'tx_bytes_delta')"
              unit="MB"
              value-type="decimal"
              :height="380"
            />
          </div>
        </div>
      </section>

      <!-- Packets / Errors tabs 已删除（per_sec 字段被清理，只保留 bytes 差值） -->

      <!-- 总统概览 -->
      <section v-if="activeTab === 'overview'" class="section">
        <h2>总统概览 — 每网卡每指标的趋势</h2>
        <p class="section-desc">
          横坐标 = 时间，纵坐标 = 累计计数器的实时值（不差分）。
          上面选网卡，下面选指标。每张图 1 个指标 + 每选中的接口 1 条线。
        </p>
        <div v-if="ifaceTrendsLoading" class="loading">加载中...</div>
        <div v-if="ifaceTrendsError" class="error">{{ ifaceTrendsError }}</div>

        <!-- 上排：网卡选择 -->
        <div v-if="ifaceTrends" class="filter-block">
          <span class="metric-picker-label">网卡（已默认前 10 个）：</span>
          <div class="metric-chips">
            <button
              v-for="name in ifaceTrends.interface_names"
              :key="name"
              class="metric-chip"
              :class="{ active: selectedOverviewIfaces.includes(name) }"
              @click="toggleOverviewIface(name)"
            >{{ name }}</button>
            <button
              v-if="selectedOverviewIfaces.length !== ifaceTrends.interface_names.length"
              class="metric-chip clear-chip"
              @click="selectedOverviewIfaces = ifaceTrends.interface_names.slice(0, 10)"
              title="恢复默认（前 10 个）"
            >默认</button>
            <button
              v-if="selectedOverviewIfaces.length > 0"
              class="metric-chip clear-chip"
              @click="selectedOverviewIfaces = []"
              title="清空选择"
            >清空</button>
          </div>
        </div>

        <!-- 下排：指标选择 -->
        <div v-if="ifaceTrends" class="filter-block">
          <span class="metric-picker-label">指标：</span>
          <div class="metric-chips">
            <button
              v-for="m in IFACE_ALL_METRICS"
              :key="m.key"
              class="metric-chip"
              :class="[
                { active: selectedOverviewMetrics.includes(m.key) },
                `group-${m.group.toLowerCase()}`,
              ]"
              @click="toggleOverviewMetric(m.key)"
            >
              <span class="metric-chip-prefix">{{ m.group }}</span>{{ m.label }}
            </button>
            <button
              v-if="selectedOverviewMetrics.length < IFACE_ALL_METRICS.length"
              class="metric-chip clear-chip"
              @click="selectedOverviewMetrics = IFACE_ALL_METRICS.map(m => m.key)"
              title="全选"
            >全选</button>
            <button
              v-if="selectedOverviewMetrics.length > 0"
              class="metric-chip clear-chip"
              @click="selectedOverviewMetrics = []"
              title="清空"
            >清空</button>
          </div>
        </div>

        <!-- 图表：每选中的指标 1 张大图，每选中的接口 1 条线 -->
        <div v-if="ifaceTrends && selectedOverviewMetrics.length > 0" class="charts-grid">
          <div v-for="m in selectedOverviewMetrics" :key="m" class="chart-cell big-chart">
            <div class="chart-annotation">
              <span class="annotation-title">{{ ifaceMetricLabel(m) }}</span>
              <span class="annotation-desc">{{ ifaceMetricDesc(m) }}</span>
              <code class="annotation-formula">Y = counter 实时值（累计）</code>
            </div>
            <TimelineChart
              :title="ifaceMetricLabel(m) + ' — 累计趋势'"
              :series="buildIfaceMetricSeries(m)"
              :unit="ifaceMetricUnit(m)"
              :value-type="ifaceMetricValueType(m)"
              :height="320"
            />
          </div>
        </div>
        <div v-else-if="ifaceTrends" class="empty-hint">请选择至少一个指标</div>
      </section>

      <!-- TCP -->
      <section v-if="activeTab === 'tcp'" class="section">
        <h2>TCP — 协议层统计</h2>
        <p class="section-desc">TCP 重传率经验：&lt;1% 正常 / 1-3% 关注 / &gt;5% 异常。</p>
        <div v-if="kernelLoading" class="loading">加载中...</div>
        <div v-if="kernelError" class="error">{{ kernelError }}</div>
        <div v-if="kernelData" class="charts-grid">
          <div v-for="group in TCP_GROUPS" :key="group.title" class="chart-cell big-chart">
            <div class="chart-annotation">
              <span class="annotation-title">{{ group.title }}</span>
              <span class="annotation-desc">{{ group.desc }}</span>
              <code class="annotation-formula">差值 = counter[i] - counter[i-1]</code>
            </div>
            <TimelineChart
              :title="group.title + ' — 差值（每窗口）'"
              :series="buildKernelDeltaSeries(group.metrics)"
              value-type="integer"
              :height="340"
            />
          </div>
        </div>
      </section>

      <!-- IP -->
      <section v-if="activeTab === 'ip'" class="section">
        <h2>IP — 路由与分片</h2>
        <p class="section-desc">头错误/丢包/无路由/分片失败正常应为 0 或接近 0。</p>
        <div v-if="kernelLoading" class="loading">加载中...</div>
        <div v-if="kernelError" class="error">{{ kernelError }}</div>
        <div v-if="kernelData" class="charts-grid">
          <div v-for="group in [...IP_GROUPS, ...IP6_GROUPS]" :key="group.title" class="chart-cell big-chart">
            <div class="chart-annotation">
              <span class="annotation-title">{{ group.title }}</span>
              <span class="annotation-desc">{{ group.desc }}</span>
              <code class="annotation-formula">差值 = counter[i] - counter[i-1]</code>
            </div>
            <TimelineChart
              :title="group.title + ' — 差值（每窗口）'"
              :series="buildKernelDeltaSeries(group.metrics)"
              value-type="integer"
              :height="340"
            />
          </div>
        </div>
      </section>

      <!-- ICMP -->
      <section v-if="activeTab === 'icmp'" class="section">
        <h2>ICMP — 控制消息协议</h2>
        <p class="section-desc">ICMP 主要用途：ping、网络不可达通知、traceroute。</p>
        <div v-if="kernelData" class="charts-grid">
          <div v-for="group in ICMP_GROUPS" :key="group.title" class="chart-cell big-chart">
            <div class="chart-annotation">
              <span class="annotation-title">{{ group.title }}</span>
              <span class="annotation-desc">{{ group.desc }}</span>
              <code class="annotation-formula">差值 = counter[i] - counter[i-1]</code>
            </div>
            <TimelineChart
              :title="group.title + ' — 差值（每窗口）'"
              :series="buildKernelDeltaSeries(group.metrics)"
              value-type="integer"
              :height="340"
            />
          </div>
        </div>
      </section>

      <!-- UDP -->
      <section v-if="activeTab === 'udp'" class="section">
        <h2>UDP — 用户数据报协议</h2>
        <p class="section-desc">UDP 用于 DNS、视频流、VoIP 等对延迟敏感但不要求可靠传输的场景。</p>
        <div v-if="kernelData" class="charts-grid">
          <div v-for="group in UDP_GROUPS" :key="group.title" class="chart-cell big-chart">
            <div class="chart-annotation">
              <span class="annotation-title">{{ group.title }}</span>
              <span class="annotation-desc">{{ group.desc }}</span>
              <code class="annotation-formula">差值 = counter[i] - counter[i-1]</code>
            </div>
            <TimelineChart
              :title="group.title + ' — 差值（每窗口）'"
              :series="buildKernelDeltaSeries(group.metrics)"
              value-type="integer"
              :height="340"
            />
          </div>
        </div>
      </section>

      <!-- Interfaces -->
      <section v-if="activeTab === 'interfaces'" class="section">
        <h2>Interfaces — 网卡任意时间点详情</h2>

        <!-- 时间轴控件 -->
        <div class="time-axis">
          <input
            v-model.number="currentCycleIndex"
            type="range"
            :min="0"
            :max="totalCycles > 0 ? totalCycles - 1 : 0"
            step="1"
            class="snapshot-progress-slider"
          />
          <code class="pid-time-display">{{ currentTimestamp || '—' }}</code>
          <span class="cycle-pos">第 {{ currentCycleIndex + 1 }} / {{ totalCycles }} 个</span>
        </div>

        <!-- state + name 筛选 -->
        <div class="filter-block">
          <span class="metric-picker-label">state 筛选：</span>
          <select v-model="stateFilter" class="state-select">
            <option v-for="s in (['ALL', 'UP', 'DOWN', 'UNKNOWN'] as StateFilter[])" :key="s" :value="s">{{ s }}</option>
          </select>
          <span class="metric-picker-label" style="margin-left: 16px;">名称搜索：</span>
          <input
            v-model="nameFilter"
            type="text"
            class="name-search-input"
            placeholder="如 bond / ens / ib"
          />
        </div>

        <div v-if="snapshotLoading" class="loading">加载中...</div>
        <div v-if="snapshotError" class="error">{{ snapshotError }}</div>
        <div v-if="snapshot" class="table-wrap">
          <!-- 网卡汇总面板（点击行后显示） -->
          <div v-if="ifaceSummary" class="iface-summary">
            <div class="iface-summary-header">
              <code class="iface-tag">{{ ifaceSummary.name }}</code>
              <code class="state-tag" :class="`state-net-${ifaceSummary.state}`">{{ ifaceSummary.state }}</code>
              <span class="iface-summary-label">MTU {{ ifaceSummary.mtu }}</span>
              <span v-if="ifaceSummary.master" class="iface-summary-label">master: {{ ifaceSummary.master }}</span>
              <button class="iface-summary-close" @click="selectedIface = null" title="关闭">✕</button>
            </div>
            <div class="iface-summary-grid">
              <div class="iface-summary-item">
                <div class="iface-summary-sub">总接收</div>
                <div class="iface-summary-value">{{ formatBytes(ifaceSummary.totalRx) }}</div>
              </div>
              <div class="iface-summary-item">
                <div class="iface-summary-sub">总发送</div>
                <div class="iface-summary-value">{{ formatBytes(ifaceSummary.totalTx) }}</div>
              </div>
              <div class="iface-summary-item">
                <div class="iface-summary-sub">平均 RX/窗口</div>
                <div class="iface-summary-value">{{ formatBytes(ifaceSummary.avgRx) }}</div>
              </div>
              <div class="iface-summary-item">
                <div class="iface-summary-sub">平均 TX/窗口</div>
                <div class="iface-summary-value">{{ formatBytes(ifaceSummary.avgTx) }}</div>
              </div>
              <div class="iface-summary-item">
                <div class="iface-summary-sub">采样窗口数</div>
                <div class="iface-summary-value">{{ ifaceSummary.cycles - 1 }}</div>
              </div>
              <div class="iface-summary-item">
                <div class="iface-summary-sub">时间范围</div>
                <div class="iface-summary-value" style="font-size:13px;">{{ ifaceSummary.timeRange.start }} → {{ ifaceSummary.timeRange.end }}</div>
              </div>
            </div>
            <!-- 该网卡的时序图 -->
            <div class="charts-grid" style="margin-top:12px;">
              <div class="chart-cell">
                <TimelineChart
                  :title="ifaceSummary.name + ' — RX Bytes / 采样窗口'"
                  :series="buildSingleIfaceSeries(ifaceSummary.name, 'rx_bytes_delta')"
                  unit="MB"
                  value-type="decimal"
                  :height="280"
                />
              </div>
              <div class="chart-cell">
                <TimelineChart
                  :title="ifaceSummary.name + ' — TX Bytes / 采样窗口'"
                  :series="buildSingleIfaceSeries(ifaceSummary.name, 'tx_bytes_delta')"
                  unit="MB"
                  value-type="decimal"
                  :height="280"
                />
              </div>
            </div>
          </div>

          <p class="table-meta">
            显示 {{ filteredInterfaces.length }} / {{ snapshot.interfaces.length }} 个接口
            <span v-if="stateFilter !== 'ALL'">· state={{ stateFilter }}</span>
            <span v-if="nameFilter.trim()">· 名称含 "{{ nameFilter.trim() }}"</span>
          </p>
          <table class="data-table">
            <thead>
              <tr>
                <th>NAME</th>
                <th>STATE</th>
                <th>MTU</th>
                <th>MASTER</th>
                <th>RX 字节</th>
                <th>TX 字节</th>
                <th>RX pkts</th>
                <th>TX pkts</th>
                <th>RX err</th>
                <th>TX err</th>
                <th>RX drop</th>
                <th>TX drop</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="i in filteredInterfaces" :key="i.name"
                  :class="{ 'row-selected': selectedIface === i.name }"
                  @click="selectedIface = selectedIface === i.name ? null : i.name">
                <td><code class="iface-tag">{{ i.name }}</code></td>
                <td><code class="state-tag" :class="`state-net-${i.state}`">{{ i.state }}</code></td>
                <td class="num-cell">{{ i.mtu }}</td>
                <td>{{ i.master || '—' }}</td>
                <td class="num-cell">{{ formatCount(i.rx_bytes) }}</td>
                <td class="num-cell">{{ formatCount(i.tx_bytes) }}</td>
                <td class="num-cell">{{ formatCount(i.rx_packets) }}</td>
                <td class="num-cell">{{ formatCount(i.tx_packets) }}</td>
                <td class="num-cell" :class="{ 'cell-warn': i.rx_errors > 0 }">{{ i.rx_errors }}</td>
                <td class="num-cell" :class="{ 'cell-warn': i.tx_errors > 0 }">{{ i.tx_errors }}</td>
                <td class="num-cell" :class="{ 'cell-warn': i.rx_dropped > 0 }">{{ i.rx_dropped }}</td>
                <td class="num-cell" :class="{ 'cell-warn': i.tx_dropped > 0 }">{{ i.tx_dropped }}</td>
              </tr>
              <tr v-if="filteredInterfaces.length === 0">
                <td colspan="12" class="empty-row">没有匹配的接口</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <UnknownFormatDialog
      v-if="unknownFormatInfo"
      :banner="unknownFormatInfo.banner"
      :header-columns="unknownFormatInfo.section_marker ? [unknownFormatInfo.section_marker] : null"
      :pending-path="unknownFormatInfo.pending_path"
      @close="unknownFormatInfo = null"
    />
    <UploadResultDialog
      v-if="uploadResult"
      :uploaded="uploadResult.uploaded"
      :failed="uploadResult.failed"
      @close="uploadResult = null"
    />
  </div>
</template>

<style scoped>
/* ─── OSW-View 浅色主题（与 iostat / ps / top 保持一致） ────── */
.netstat-view {
  max-width: 1600px;
  margin: 0 auto;
  padding: 16px 24px 40px;
  color: #1f2937;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.header { margin-bottom: 12px; }
.version-hint { font-size: 12px; color: #6b7280; }
.version-hint-label { margin-right: 4px; }
.version-tag {
  display: inline-block;
  background: #e0f2fe;
  color: #075985;
  padding: 2px 8px;
  border-radius: 3px;
  margin-right: 4px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  cursor: help;
  border: 1px solid #bae6fd;
}

.section { margin-top: 24px; }
.section h2 {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid #e5e7eb;
}
.section h3 { font-size: 14px; font-weight: 600; color: #1e3a8a; margin: 16px 0 8px 0; }
.section-desc { font-size: 12px; color: #6b7280; margin-bottom: 12px; line-height: 1.5; }

.path-section { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 16px; }
.path-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.path-input {
  flex: 1;
  min-width: 280px;
  padding: 6px 10px;
  background: #fff;
  border: 1px solid #d0d0d0;
  color: #1f2937;
  border-radius: 4px;
  font-size: 13px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
.path-input::placeholder { color: #9ca3af; }
.btn {
  padding: 6px 14px;
  background: #fff;
  border: 1px solid #d0d0d0;
  color: #374151;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  white-space: nowrap;
  transition: all 0.1s;
}
.btn:hover:not(:disabled) { background: #f3f4f6; border-color: #9ca3af; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: #2563eb; color: #fff; border-color: #2563eb; }
.btn-primary:hover:not(:disabled) { background: #1d4ed8; border-color: #1d4ed8; }
.btn-success { background: #16a34a; color: #fff; border-color: #16a34a; }
.btn-success:hover:not(.disabled) { background: #15803d; border-color: #15803d; }
.btn-success.disabled { opacity: 0.5; cursor: not-allowed; }

.loading { margin-top: 8px; color: #2563eb; font-size: 13px; }
.error { margin-top: 8px; color: #dc2626; font-size: 13px; }
.current-dir {
  margin-top: 8px;
  font-size: 12px;
  color: #6b7280;
}
.current-dir code {
  background: #f5f5f5;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  color: #1e3a8a;
}

/* ─── Overview 卡片网格 ─────────────────── */
.overview-section { margin-top: 16px; }
.overview-section h2 { border-bottom-color: #2563eb; }
.card-grid {
  display: grid;
  gap: 12px;
}
.overview-cards {
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}
.stat-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 14px 16px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.stat-label {
  font-size: 11px;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 500;
}
.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #1f2937;
  margin-top: 4px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  line-height: 1.2;
}
.stat-value .unit { font-size: 14px; color: #9ca3af; font-weight: 400; }
.stat-sub {
  font-size: 11px;
  color: #9ca3af;
  margin-top: 4px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
.stat-sub code { color: #1e3a8a; }

/* ─── Tab 导航 ───────────────────────────── */
.tab-bar {
  display: flex;
  gap: 2px;
  margin-top: 20px;
  border-bottom: 1px solid #e5e7eb;
  padding: 0;
}
.tab-btn {
  background: transparent;
  border: none;
  color: #6b7280;
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
  margin-bottom: -1px;
}
.tab-btn:hover { color: #1f2937; background: #f9fafb; }
.tab-btn.active {
  color: #2563eb;
  border-bottom-color: #2563eb;
  background: #eff6ff;
}

/* ─── 筛选 chips ────────────────────────── */
.filter-block { margin-bottom: 12px; }
.metric-picker-label {
  font-size: 12px;
  color: #6b7280;
  font-weight: 500;
  white-space: nowrap;
  margin-right: 6px;
}
.metric-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.metric-chip {
  display: inline-block;
  padding: 4px 12px;
  background: #fff;
  border: 1px solid #d0d0d0;
  color: #374151;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  transition: all 0.1s;
}
.metric-chip:hover {
  border-color: #2563eb;
  color: #1e3a8a;
  background: #eff6ff;
}
.metric-chip.active {
  background: #2563eb;
  color: #fff;
  border-color: #3b82f6;
  font-weight: 600;
}
.metric-chip.clear-chip {
  background: #fee2e2;
  border-color: #fca5a5;
  color: #b91c1c;
}
.metric-chip.clear-chip:hover { background: #fecaca; }
.metric-chip.group-rx.active { background: #1e3a8a; border-color: #3b82f6; }
.metric-chip.group-tx.active { background: #0f766e; border-color: #14b8a6; }
.metric-chip-prefix {
  font-size: 10px;
  font-weight: 700;
  margin-right: 4px;
  padding: 0 4px;
  background: #f3f4f6;
  color: #6b7280;
  border-radius: 2px;
}
.metric-chip.active .metric-chip-prefix {
  background: rgba(255, 255, 255, 0.25);
  color: #fff;
}

/* ─── 图表网格 ──────────────────────────── */
.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(480px, 1fr));
  gap: 12px;
  margin-top: 8px;
}
.chart-cell {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 6px 8px 10px 8px;
}
.chart-cell.big-chart {
  grid-column: 1 / -1;
}

/* ─── 表格 ──────────────────────────────── */
.data-table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  overflow: hidden;
  font-size: 12px;
}
.data-table th, .data-table td {
  text-align: left;
  padding: 6px 10px;
  border-bottom: 1px solid #f3f4f6;
  color: #1f2937;
}
.data-table th {
  background: #f9fafb;
  font-weight: 600;
  color: #1e3a8a;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}
.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background: #f9fafb; }
.iface-tag {
  background: #eff6ff;
  color: #1e3a8a;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
.state-tag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-weight: 600;
}
.state-net-UP { background: #dcfce7; color: #14532d; }
.state-net-DOWN { background: #fee2e2; color: #991b1b; }
.state-net-UNKNOWN { background: #f3f4f6; color: #374151; }
.num-cell { text-align: right; font-family: 'SF Mono', Menlo, Consolas, monospace; }
.cell-warn { color: #b91c1c; font-weight: 600; }

/* ─── Interfaces tab：时间轴 + state 筛选 ─── */
.time-axis {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.snapshot-progress-slider {
  flex: 1;
  min-width: 220px;
  height: 4px;
  margin: 0 4px;
  appearance: none;
  -webkit-appearance: none;
  background: #d1d5db;  /* 纯灰线，不分左右颜色 */
  border-radius: 2px;
  cursor: pointer;
  outline: none;
}
.snapshot-progress-slider::-webkit-slider-thumb {
  appearance: none;
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  background: #2563eb;
  border: none;
  border-radius: 50%;
  cursor: grab;
  margin-top: -5px;  /* 居中于 4px 高的轨道 */
}
.snapshot-progress-slider::-webkit-slider-thumb:active { cursor: grabbing; }
.snapshot-progress-slider::-moz-range-thumb {
  width: 14px; height: 14px;
  background: #2563eb;
  border: none;
  border-radius: 50%;
  cursor: grab;
}
.snapshot-progress-slider::-moz-range-track {
  background: #d1d5db;
  height: 4px;
  border-radius: 2px;
}
.pid-time-display {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 13px;
  background: #fff;
  padding: 3px 8px;
  border: 1px solid #93c5fd;
  border-radius: 3px;
  color: #1e3a8a;
  white-space: nowrap;
}
.cycle-pos {
  font-size: 12px;
  color: #6b7280;
  white-space: nowrap;
}
.name-search-input {
  width: 180px;
  padding: 4px 8px;
  border: 1px solid #d0d0d0;
  border-radius: 3px;
  font-size: 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  background: #fff;
}
.state-select {
  padding: 4px 8px;
  border: 1px solid #d0d0d0;
  border-radius: 3px;
  font-size: 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  background: #fff;
  color: #1f2937;
  cursor: pointer;
}
.table-meta {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 8px;
}
.empty-row {
  text-align: center;
  color: #9ca3af;
  padding: 24px 0;
  font-style: italic;
}
.data-table tr.row-selected td { background: #eff6ff; }
.data-table tr.row-selected td:hover { background: #dbeafe; }
.data-table tbody tr { cursor: pointer; }

/* ─── IP tab：分组标注 ─── */
.chart-annotation {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 4px;
}
.annotation-title {
  font-size: 13px;
  font-weight: 600;
  color: #1e3a8a;
}
.annotation-hint {
  font-size: 11px;
  color: #9ca3af;
}
.annotation-desc {
  font-size: 12px;
  color: #4b5563;
  font-weight: 500;
}
.annotation-formula {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  color: #1e3a8a;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  padding: 1px 6px;
  border-radius: 3px;
  white-space: nowrap;
}

/* ─── 网卡汇总面板 ─── */
.iface-summary {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 12px;
}
.iface-summary-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #e5e7eb;
}
.iface-summary-label {
  font-size: 12px;
  color: #6b7280;
}
.iface-summary-close {
  margin-left: auto;
  background: none;
  border: none;
  font-size: 16px;
  color: #9ca3af;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 3px;
}
.iface-summary-close:hover {
  background: #f3f4f6;
  color: #374151;
}
.iface-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}
.iface-summary-item {
  background: #f9fafb;
  border-radius: 6px;
  padding: 10px 12px;
}
.iface-summary-sub {
  font-size: 11px;
  color: #6b7280;
  margin-bottom: 4px;
}
.iface-summary-value {
  font-size: 18px;
  font-weight: 700;
  color: #1f2937;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
.table-wrap { max-height: 600px; overflow: auto; }
</style>
