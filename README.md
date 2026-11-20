# 数据分析实验与数据应用服务平台

面向指标口径管理、分析实验设计、OLAP查询、数据看板构建与数据API发布的数据应用平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 指标定义 | `metric_def` | 指标 | 指标编号、指标名称、计算公式 |
| 维度管理 | `dimension` | 分析维度 | 维度编号、维度名称、维度类型 |
| 数据集管理 | `dataset` | 分析数据集 | 数据集编号、数据集名称、来源类型 |
| 分析实验 | `experiment` | 实验方案 | 方案编号、实验名称、分析数据集 |
| 实验样本分配 | `experiment_sample` | 分组名单、来源观测 | 实验编号、参与者编号、实验臂、启动时地区、更正后地区 |
| OLAP查询 | `query_builder` | 查询模板 | 模板编号、模板名称、查询语句 |
| 数据看板 | `dashboard` | 看板配置 | 看板编号、看板名称、包含图表 |
| 图表配置 | `chart` | 图表 | 图表编号、图表名称、图表类型 |
| 数据API发布 | `data_service` | 数据服务 | 服务编号、服务名称、输出数据集 |
| 智能告警 | `alert` | 告警规则 | 规则编号、告警名称、监控指标 |
| 分析用户组 | `user_group` | 用户组 | 组编号、组名称、组描述 |
| 数据快照 | `snapshot` | 快照记录 | 快照编号、数据集名称、快照时间 |
| 任务调度 | `scheduler` | 调度任务 | 任务编号、任务名称、调度类型 |
| 缓存管理 | `cache` | 缓存配置 | 缓存编号、缓存目标、缓存策略 |
| 分析管道 | `pipeline` | 分析节点 | 节点编号、输入数据集、分析算子 |
| 分析模型 | `model` | 模型配置 | 模型编号、模型名称、模型类型 |
| 数据集市 | `data_mart` | 集市表 | 表编号、表名称、主题域 |
| 数据导出 | `export` | 导出任务 | 任务编号、导出对象、导出格式 |
| 数据审计 | `audit` | 审计记录 | 记录编号、操作类型、操作人 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 实验样本分配表

分析实验在方案之外维护一张实验样本分配表，接口挂在 `/api/experiment/{id}/sample`：

| 接口 | 用途 |
| --- | --- |
| `GET /sample` | 分组名单、各臂人数、未加入名单的观测 |
| `POST /sample/sync` | 从来源观测归并同一参与者，生成或刷新名单 |
| `GET /sample/aggregate?region=&arm=&region_basis=` | 按名单聚合各臂分子/分母，待归属观测单列 |
| `GET /sample/report` | 实验报告：人群口径、样本分母、地区口径与更正参与者 |
| `GET /sample/participants/{pid}/reconcile` | 重新查询历史曝光，核对实际分组与分母归属 |
| `GET/POST /sample/observations` | 查看或补录来源观测 |

规则：

- 来源观测需要参与者编号、观测时间和分组字段；同一参与者的多条观测按参与者编号归并成名单一行。
- 同一参与者在一次实验中只进入一个实验臂，以首次曝光记录的分组字段为准；已发生的曝光始终归入实际收到的实验臂，后续记录或地区更正不会重新分组。
- `启动时地区`取自首次曝光，用于复验原分层设计；`更正后地区`取自最新来源观测，用于回答当前地区的响应差异。两种口径通过 `region_basis=start|current` 切换。
- 没有曝光或没有分组字段的观测不进入名单，在聚合结果里单列，不进入任何实验臂的分子或分母。
- 查询时按分层地区和实验臂筛选，筛后的分子、分母与待归属记录都使用同一次查询的人群范围；实验臂筛选不适用于没有实验臂的待归属观测。

测试：`cd backend && pip install -r requirements-dev.txt && python3 -m pytest tests -q`。
