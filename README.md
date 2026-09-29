# 轨道交通信号检修管理平台

面向轨道交通信号设备日常巡检、故障处置、天窗修作业、器材检修与联锁试验的一体化信号检修管理后台。

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
| 联锁管理 | `interlock` | 联锁道岔 | 道岔编号、所属车站、道岔类型 |
| 轨道电路 | `trackcircuit` | 轨道电路 | 区段编号、所属区间、载频类型 |
| 信号机 | `signal` | 信号机 | 信号机编号、所属车站、信号机类型 |
| 转辙机 | `pointmachine` | 转辙机 | 转辙机编号、所属道岔、转辙机型号 |
| 信号电缆 | `cable` | 信号电缆 | 电缆编号、起止站点、电缆芯数 |
| 信号电源 | `powersupply` | 电源屏 | 电源屏编号、所属车站、输入电压 |
| 车载设备 | `atp` | 车载ATP | 设备编号、所属列车、设备型号 |
| 应答器 | `balise` | 应答器 | 应答器编号、所在位置、报文版本 |
| 计轴设备 | `axlecounter` | 计轴器 | 计轴器编号、所属区间、检测磁头 |
| 调度中心 | `dispatchcenter` | 调度台 | 调度台编号、管辖范围、显示设备 |
| 天窗修作业 | `maintenancewindow` | 天窗计划 | 计划编号、作业日期、作业区间 |
| 继电器检修 | `relay` | 继电器 | 继电器编号、继电器型号、所属设备 |
| 熔断器管理 | `fuse` | 熔断器 | 熔断器编号、额定电流、安装位置 |
| 防雷元件 | `lightning` | 防雷元件 | 元件编号、安装位置、防护等级 |
| 应急备品 | `emergencyresp` | 应急备品 | 备品编号、备品名称、规格型号 |
| 联锁试验 | `testrecord` | 试验记录 | 试验编号、试验日期、试验车站 |
| 信号故障 | `fault` | 故障记录 | 故障编号、发生时间、故障设备 |
| 检修工具 | `tool` | 检修工具 | 工具编号、工具名称、规格型号 |
| 技术规章 | `regulation` | 技术规章 | 规章编号、规章名称、适用专业 |
| 技能培训 | `training` | 培训记录 | 培训编号、培训主题、培训对象 |
| 资质台账 | `qualification` | 人员/证书/作业资格 | 工号、证书类别、有效期至、作业资格结论 |
| 检修排班 | `schedule` | 排班与审核 | 排班编号、作业项目、兼岗理由、审核记录 |

## 资质判定规则（资质台账与检修排班共用）

两个入口的作业资格结论、接口返回的 `days_to_expiry`（到期天数）全部来自
`backend/app/rules.py` 这一份判定，任何页面不另写口径：

- **按证书类别 + 作业项目判定**：每个作业项目配置主专业证书（如联锁检修要求信号工证、
  电源屏检修要求低压电工证），并配置允许的兼岗范围（如电源屏检修认可高压电工证）。
- **到期阈值按专业区分**：信号 30 天、通信 20 天、供电 15 天、综合 10 天；
  距到期不足阈值即「临期」，与「已过期」一样不允许保存进排班。
- **资质缺失按不合格**：无人员档案、无任何证书、日期缺失，一律拦截不放行。
- **超出兼岗范围须写明理由**：持非主证、也不在兼岗范围内的证书时，填写兼岗理由后
  以「类别不符(已说明兼岗)」结论保存；未写理由则拒绝保存。
- **重复录入以最近一次为准**：同一员工 + 同一证书编号多次录入，历史记录置为失效，
  判定与台账列表只取最近一次（按登记日期，其次 id）。
- **历史数据按新口径重标**：启动时及 `POST /api/qualification/reassess` 会重算
  证书/排班的当前结论；排班保存时的结论快照（`snapshot_*`）与审核人、审核意见、
  审核时间是历史事实，始终原样保留——证书到期后刷新页面，当前列显示「已过期」，
  审核记录仍完整可见。
- 业务“今天”默认取系统日期，可用环境变量 `QUALIFICATION_TODAY=YYYY-MM-DD` 固定
  （演示/联调用）。

后端判定测试：`cd backend && python3 -m unittest discover -s tests`。

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。
