# 产品分支与接口约定

每个分支对应一个独立 worktree，默认数据库在该目录的 `data/product/product.db`。
产品服务只监听本机，不打开串口。真机继续由一个 `runtime.service` 进程独占。

| 分支 | 工作目录后缀 | 产品端口 | 文件所有权 |
| --- | --- | --- | --- |
| feat/product-base-GPT | product-base-GPT | 8100 | product/、dashboard/product/、共享接口 |
| feat/walking-records-GPT | walking-records-GPT | 8101 | product_features/records/、对应测试 |
| feat/activity-modes-GPT | activity-modes-GPT | 8102 | product_features/modes/、对应测试 |
| feat/personal-memory-GPT | personal-memory-GPT | 8103 | product_features/memory/、对应测试 |
| feat/growth-badges-GPT | growth-badges-GPT | 8104 | product_features/growth/、对应测试 |
| feat/glasses-guide-GPT | glasses-guide-GPT | 8105 | product_features/guide/、对应测试 |
| integration/product-GPT | product-GPT | 8110 | 合并、接入 runtime 的边界、联调 |
| feat/glasses-demo-GPT | glasses-demo-GPT | 8111（启动时显式指定） | 眼镜连续拍照、EvoMap 演示判断与本机页面 |
| feat/auto-reconnect-GPT | auto-reconnect-GPT | 保持现有配置 | 串口重连（现有独立分支） |

功能分支从产品基础提交分出，不相互合并。通过约定的数据格式通信；集成分支合并各功能分支和已提交的重连改动。main 保留现有稳定版本。

## 开发

`uv run python -m product.server` 自动按当前分支选用上表端口，也可用 `--port` 覆盖。没有数据时显示空状态。
`--recordings-dir /绝对路径/data` 可读取已有记录，只读，不改原始数据。
`--device-ws ws://127.0.0.1:8765` 可订阅现有服务的数据，默认只读。
只有专门用于真机联调的工作区才添加 `--control`，使能页面操作按钮；启动产品服务本身不会下发任何设备命令。
同一时刻仅一个控制服务持有真实串口；不得同时启动多个 runtime 服务争抢硬件。

## 插件边界

功能文件放到 `product_features/<feature>/`。`register(app)` 注册 `/api/<feature>/...` 路由并返回 title、description、order。
页面入口 `view.js` 导出 `mount(root, {api, config, device, ui})`，返回可选清理函数。
每个功能管理自己的页面和监听器，共用导航不随功能分支修改。原有监视器完全独立。
前端展示外部字符串必须用 textContent，不拼入 HTML。

## 运动记录 v1

`GET /api/sessions` -> `{sessions: [...]}`，新工作区返回空数组。
每项包含 `id`（源文件内容摘要）、`started_at`（UTC 秒）、`source_file`、`body`、`profile`、`eligible`、`context`、`metrics`。
`eligible` 仅在明确标识 real + wearing + 完整记录时成立。桌面标定、仿真、来源不明都不计入成长。
`metrics` 包括 duration_s、frames、left/right_rom_deg、rom_symmetry、left/right_command_work_j、movement_s；缺少或无法成立的指标用 null，不用 0 冒充测量。
力矩是指令值，计算得到的是指令做功估计，不是肌力、人体能耗或省力百分比。
同路线、模式和参数未明确匹配时，不据此推断体能或康复提升。

## 真机边界

所有产品控制经既有命令入口，保留限幅、斜坡、静默期和急停。
产品默认不会根据长期记忆、徽章或视觉结果自动施力。`feat/glasses-demo-GPT` 增加独立的桌面支架演示例外：控制服务与产品服务均显式启用，用户在页面手动开启本轮抬腿提示后，只有新照片的高置信左/右结果才可触发一次限幅、到期归零的反侧抬腿；不适用于穿戴或真实引路。
设备状态增加 body/profile 标识后，产品才允许对明确 real 的就绪服务操作；旧协议仍能查看数据。
实时曲线只消费新收到的数据帧。历史记录在档案页面显示，不混成当前实时数据。
