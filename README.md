# OSW-View

对 OSW 日志（iostat / ps / top 等）进行可视化展示的工具。

当前阶段支持 **iostat 指标采集日志**的解析与可视化。

---

## 功能特性

- **时间线图表**：多设备叠加显示，ECharts 渲染，支持滚轮缩放和滑块选择时间范围，图例点击切换单/多设备
- **统计概览**：每个设备 × 每个指标，输出 min / max / avg / sum / P50 / P95 / std
- **自识别解析**：列名指纹识别，自动适配不同版本的 iostat 输出格式
- **版本识别弹窗**：每次解析都弹出 — 命中已知版本时展示「按 *display_name* (v0001) 解析 N 个文件」+ 可展开文件清单；未识别时弹「未识别格式」对话框并归档样本
- **JSON 文件缓存**：解析结果缓存到文件（含 `version` 字段），文件未变化时不重复解析
- **CPU 指标**：avg-cpu 独立区域展示
- **总入口页**：所有 OSW 工具统一入口（HomeView），点击卡片跳转到对应分析视图
- **上传/接收目录按工具分**：上传文件按工具自动存到 `oswupdownload_file/<tool>/` 子目录，每个工具独立互不污染；上传时支持重名自动加 hash 后缀；7 天未访问自动清理
- **多版本共存**：iostat 已注册 v0001 / v0002 / v0003（v0003 是 v0002 镜像占位），detect 按版本号倒序匹配

---

## 目录结构

按**工具维度**组织：每个工具（iostat / 未来 ps/top/netstat）的所有代码集中在一处。

```
osw-view/
├── backend/                                # FastAPI 后端
│   ├── main.py                             # FastAPI 入口，4 个 endpoint（scan/upload/parse/iostat/versions）
│   ├── common.py                           # 跨工具共享：KNOWN_TOOLS / UPLOAD_DIR / 工具子目录（get/scan/cleanup）
│   ├── parser/
│   │   ├── base.py                         # 解析器基类
│   │   └── iostat/                         # iostat 工具整套
│   │       ├── __init__.py                 # IostatVersionRegistry（detect / parse / 倒序加载）
│   │       ├── fingerprint.py              # fingerprint 提取器
│   │       ├── exceptions.py               # UnknownIostatFormat
│   │       └── versions/                   # 各 iostat 格式版本
│   │           ├── v0001/                  # OSWbb 旧格式
│   │           │   ├── __init__.py
│   │           │   ├── manifest.json
│   │           │   ├── fingerprint.json
│   │           │   └── parser.py
│   │           ├── v0002/                  # WQWbb 新格式（重庆 cq）
│   │           │   └── ...
│   │           └── v0003/                  # v0002 镜像占位（active=true，detect 倒序优先）
│   │               └── ...
│   └── cache/
│       └── json_cache.py                   # 解析结果 JSON 缓存
│
├── frontend/                               # Vue 3 + Vite 前端
│   ├── src/
│   │   ├── main.ts                         # createApp + 装 router
│   │   ├── App.vue                         # 顶栏 + <RouterView/>
│   │   ├── router/
│   │   │   └── index.ts                    # 路由表：/ → HomeView，/iostat → IostatView
│   │   ├── views/                          # 工具主页面
│   │   │   ├── HomeView.vue                # 总入口：8 张 osw 工具卡片
│   │   │   ├── IostatView.vue              # iostat 主页面
│   │   │   └── iostat-components/          # iostat 专用子组件
│   │   │       ├── StatsOverview.vue
│   │   │       └── MatchedVersionDialog.vue
│   │   ├── components/                     # 跨工具通用组件
│   │   │   ├── FileSelector.vue
│   │   │   ├── TimelineChart.vue
│   │   │   ├── UnknownFormatDialog.vue     # 422 未识别弹窗
│   │   │   └── UploadResultDialog.vue      # 上传结果弹窗
│   │   └── api/                            # 工具 API 拆分
│   │       ├── common.ts                   # 通用：uploadFiles / clearCache
│   │       └── iostat.ts                   # iostat：scan / parse / iostatVersions
│   ├── index.html
│   ├── vite.config.ts                      # 端口 5174 + /api 代理到 8001
│   └── package.json
│
├── oswupdownload_file/                     # 上传/接收目录（按工具分子目录，7 天自动清理；首次访问时懒清理）
│   ├── iostat/                             # iostat 工具的上传文件（当前 5 个）
│   ├── ps/                                 # ps 工具的上传文件（未来）
│   └── top/                                # top 工具的上传文件（未来）
│
└── README.md
```

**找路径的约定**（未来加新工具时按这个模式）：
  - **后端工具整套**：`backend/parser/<tool>/`（`__init__.py` 注册表 + `fingerprint.py` + `exceptions.py` + `versions/v000N/`）
  - **后端通用**：`backend/common.py`（跨工具共享的工具函数）
  - **前端工具整套**：`frontend/src/views/<Tool>View.vue`（主页面） + `frontend/src/views/<tool>-components/`（专用子组件）
  - **前端工具 API**：`frontend/src/api/<tool>.ts`
  - **前端通用组件**：`frontend/src/components/`（如 FileSelector 可被多工具复用）

---

## 开发

### 前置依赖

- Python 3.11+
- Node.js 18+

### 后端

```bash
cd backend

# 方式 A：从 requirements.txt 安装（运行时依赖）
pip install -r requirements.txt

# 方式 B：可编辑模式安装（含 dev 依赖，便于跑 pytest）
pip install -e ".[dev]"

# 启动（端口 8001）
PYTHONPATH=.. uvicorn backend.main:app --host 0.0.0.0 --port 8001

# 跑测试
PYTHONPATH=.. pytest
```

### 前端

```bash
cd frontend
npm install

# 启动开发服务器（端口 5174）
npm run dev
```

访问 `http://<服务器IP>:5174`，输入 OSW 数据目录路径（如 `/data/osw/oswiostat/`），刷新扫描后勾选文件即可可视化。

---

## License

[MIT](./LICENSE)

---

## 后续阶段

- [ ] ps 数据可视化
- [ ] top 数据可视化
- [x] 多版本 iostat 列名差异自动适配（v0001 / v0002 通过 fingerprint JSON 严格匹配 + 自动 detect）
