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
| 检修排班 | `schedule` | 派工排班 | 排班号、员工、作业项目、作业日期、兼岗理由、审核记录 |
| 人员资质台账 | `certificate` | 员工持证 | 工号、证书类别、归口专业、有效期至、到期天数 |
| 继电器检修 | `relay` | 继电器 | 继电器编号、继电器型号、所属设备 |
| 熔断器管理 | `fuse` | 熔断器 | 熔断器编号、额定电流、安装位置 |
| 防雷元件 | `lightning` | 防雷元件 | 元件编号、安装位置、防护等级 |
| 应急备品 | `emergencyresp` | 应急备品 | 备品编号、备品名称、规格型号 |
| 联锁试验 | `testrecord` | 试验记录 | 试验编号、试验日期、试验车站 |
| 信号故障 | `fault` | 故障记录 | 故障编号、发生时间、故障设备 |
| 检修工具 | `tool` | 检修工具 | 工具编号、工具名称、规格型号 |
| 技术规章 | `regulation` | 技术规章 | 规章编号、规章名称、适用专业 |
| 技能培训 | `training` | 培训记录 | 培训编号、培训主题、培训对象 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 作业资格判定口径（资质台账 × 检修排班）

判定规则只有一份，集中在 `backend/app/qualification.py`，资质台账页面、检修排班保存
校验、`/api/schedule` 与 `/api/qualification` 返回的「到期天数」全部调用同一组函数，
保证两个入口的作业资格结论一致：

- **到期天数**：有效期截止日 − 今天，自然日整数；负数表示已过期；无法解析按缺失处理。
- **分专业临期阈值** `THRESHOLD_DAYS`：信号/区间/驼峰 30 天、电源 15 天、车载 45 天；
  距到期不足阈值判「临期」。
- **不合格（一律不允许保存进排班，理由不能放行）**：资质信息缺失、证书类别与作业项目
  不符、证书已过期、证书临期。资质缺失按不合格处理，绝不放行（fail-closed）。
- **证书类别归口** `CERT_SPECIALTY`：按证书类别确定专业，与作业项目要求类别比对。
- **兼岗范围** `SECONDARY_SCOPE`：本专业直接允许；命中允许兼岗表的跨专业作业无需理由；
  超出允许范围的兼岗，资质仍须有效，且**必须写明兼岗理由**才允许保存，并写入审核记录。
  跨专业作业按本人所属专业归口核对证书有效性。
- **重复证书**：同一员工重复录入同一证书类别时，以 `recorded_at` 最近一次为准
  （`effective_certificates` 折叠）；旧条目标记为失效、仅留痕，不参与判定。
- **历史数据**：服务启动时及 `POST /api/schedule/reassess` 会按最新口径重算历史排班的
  结论字段；`audits` 审核记录只追加、不覆盖、不删除——证书到期后刷新页面仍保留原审核记录。

主要接口：

- `GET /api/qualification/rules` 回传阈值、证书归口、作业项目、兼岗范围
- `GET /api/qualification/certificates` 资质台账（`include_duplicates=true` 可看被折叠旧证）
- `POST /api/qualification/certificates` 登记持证（重复证书按最近一次为准）
- `GET /api/qualification/employees/{id}/qualifications` 某员工全部作业项目资格矩阵
- `POST /api/schedule/check` 保存前预校验（不落库，结论与台账同源）
- `POST /api/schedule` 保存排班（不合格拦截；超范围兼岗须给 `secondary_reason`）
- `POST /api/schedule/reassess` 历史按新口径重算（审核记录不动）

回归测试：`cd backend && PYTHONPATH=. python3 tests/test_qualification_rules.py`。
