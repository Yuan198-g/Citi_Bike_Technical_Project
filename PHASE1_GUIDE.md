# 第一阶段交付说明

## 使用方式

把这个补充包的文件放进你原来的 citi_bike_phase1 文件夹，与 pipeline.py 放在一起。
不需要删除 data、不需要修改原 pipeline.py、也不依赖你手工保存的 baseline.sql。
补充包中的 test_pipeline.py 已修复 Windows 数据库连接关闭问题，可以替换原测试文件。

统一入口：

```powershell
python run_phase1.py --months 202508 202509 --analysis-month 202509
python -m unittest -v
```

Python 3.10+；Windows 安装 `python -m pip install tzdata`。

运行顺序：检查月份参数 → 每月下载原 ZIP → 文件校验与解析 → 记录验证与去重 →
事务写入事实表和文件清单 → 创建指定分析月份的基线 → 自动检查 → 导出分析结果。
任何阶段出现异常，命令以失败状态退出；未通过检查时不刷新分析 CSV。
普通运行不需要手动下载、编辑源数据或执行 DBeaver SQL。
DBeaver 可用于独立检查处理后的数据库。

原来的 pipeline.py 仍可使用，但最终演示和提交以 run_phase1.py 为统一入口。
之前在 pipeline.py 中添加的 baseline.sql 读取逻辑不会被这个入口调用。

## 数据范围与口径

来源官方页面：https://citibikenyc.com/system-data
历史文件列表：https://s3.amazonaws.com/tripdata/index.html
本阶段选 JC-202508 / JC-202509 来源文件，覆盖 Jersey City / Hoboken，不代表整个纽约网络。
原 ZIP 全部 CSV 都处理，不采样。数据可能有跨月开始日期，原记录保留，不按文件名强制删掉。
下载 URL 按已知 JC 命名规则构造；没有自动适配旧版本历史文件命名。

`--months` 是入库来源月份，`--analysis-month` 是报表和基线的自然月。
原始文件按来源月存放；数据库事实表合并所有成功处理文件；报表按分析月目录组织。
目前已处理8月和9月，但9月报表只筛纽约当地9月日期，避免把两个月总量混用。

用户类型、车型、时长、小时骑行量、origin_stations 按开始日期归属。
到达小时表和 destination_stations 按结束日期归属。
因此起点与终点月度总数不保证相等；跨月骑行与缺失端点都可能造成差异。
后续覆盖起止边界时应检查相邻来源文件，不能仅从月名推断结束事件完整性。

原始时间无时区，本阶段假设为 America/New_York；该假设未由官方页面明确确认。
转 UTC 后存储，日期/小时/星期按纽约当地时间计算，星期一=0。
重复或不存在的夏令时本地时间隔离，不随意决定时间。

## 主要表：粒度、键和更新方式

| 对象 | 一行代表什么 / 键 | 关系与刷新 |
|---|---|---|
| fact_trip | 一条骑行 / ride_id | 新文件追加，已有 ride_id 不重复；站点 ID 是文本，允许 NULL |
| trip_arrival_time | 一条已接受骑行的结束当地日期小时 / ride_id | 与 fact_trip 一对一，同事务插入 |
| processed_files | 一个成功 ZIP 内容 / SHA-256 | 同事务记录来源 URL、时间和处理计数 |
| rejected_records | 一个被隔离的来源行 | 来源 SHA-256、CSV 名、行号、原因、原始 JSON；同事务写入 |
| trips_daily | 一个开始当地日期 | SQL 视图，从当前 fact_trip 计算 |
| station_departures_hourly | 一个起点站、开始日期、小时 | SQL 视图，排除缺失起点 |
| station_arrivals_hourly | 一个终点站、结束日期、小时 | 联结 trip_arrival_time 的 SQL 视图，排除缺失终点 |
| station_hourly_baseline_YYYYMM | 一个站、星期几、小时 | 每次运行事务替换指定月份的派生视图，不修改事实记录 |

这是宽事实表加派生视图的替代模型。车型、会员类型直接保存在 fact_trip 中，可用于分组筛选。
没有单独 dim_station / dim_date；本阶段不要求人工维护维表。
原始站点名称、坐标仍保存在原始 CSV；正式站点名称、位置和 capacity 会在实时阶段使用 GBFS 数据建模。
历史与 GBFS 站点映射尚未验证，不宣称 JC009 等历史 ID 可以直接匹配当前接口。

## 验证与错误处理

记录隔离：无 ride_id、不能解析或不能确定的时间、时长≤0或>24小时、存在但不合理的区域坐标。
时长上限为项目策略，不声称长骑行一定是源错误；原数据可复查。
缺站点或缺坐标不自动删除骑行；未认识的会员、车型分类保留原值。
坐标范围：纬度40–42，经度-75至-72。
文件缺少必需字段或结构无效：整个文件失败并回滚。

SHA-256 已处理的 ZIP 跳过；相同 ride_id 和相同标准化字段记重复。
ride_id 相同而标准化字段不一致：保留先处理记录，后记录隔离为冲突。
这不是自动纠正历史事实的修订机制。
缓存原文件不会每次重新下载，因此同名远端更新需要另行管理。

最终自动检查包括：SQLite 完整性、文件分类计数平衡、事实表与累计插入数、隔离数、
ride_id、时间和时长、每日与站点汇总、到达辅助表关系、基线格点数和键唯一性。
检查结果写到 validation.json；失败阻止本次分析 CSV 导出，已提交事实表不回滚。
操作人员通过终端异常、validation.json、processed_files 和 rejected_records 查看失败原因。
本版本没有独立告警服务。

文件写入事务与运行状态保存在数据库。下载最多3次尝试，失败删除临时 .part 文件。
文件处理中断：未提交事务回滚，重跑继续；成功文件不会重新入库。
基线替换在单事务中。CSV 用临时文件原子替换每个文件，但整个报告目录不是一个原子发布单元；
导出中断后重新运行恢复。validation.json / summary.json 带本次运行信息。
SQLite 本地单写入者；如 DBeaver 持有写事务，应提交/回滚后重跑。

## 需求基线定义与限制

分母为分析月所有对应星期几的日历天数，包含零骑行日期。
站点集合为该月发生过出发或到达的站点，每站7×24行。
平均出发、平均到达、平均净流出分别按对应天数计算；净流出=出发-到达。
假设该月来源覆盖完整且站点整月存在，新增/停运可能低估基线。
没有站点运营历史时，零需求与站点不运营无法区分。
每组只有4–5天，不能把平均值解释为稳定预测。
历史记录是完成的骑行，不包含无车或无空位造成的未满足需求。
净流出不含工作人员调车，也不能证明某时刻缺车。
2025年9月基线是历史演示，需要更近、更多月份才能提高当前风险提示的相关性。

## 自动输出

`data/reports/202509/`：

- summary.json / validation.json：覆盖、累计数、缺失站点、检查结果。
- trips_daily.csv / trips_hourly.csv / hourly_weekday_weekend.csv：历史趋势。
- rider_type.csv / bike_type.csv / duration_distribution.csv：用户、车型、时长。
- origin_stations.csv / destination_stations.csv：全部站点排序。
- station_departures_hourly.csv / station_arrivals_hourly.csv：站点每日小时事件量。
- station_hourly_baseline.csv / baseline_definition.sql：基线及其可复现 SQL。
- processed_files.csv / rejection_reasons.csv：来源与质量证据，数据库累计口径。

Dashboard 也可以直接查数据库，不必只依赖 CSV。

## 最终验收与证据

1. 两个月原始数分类平衡；9月116071→116033，8月108441→108399，合并224432。
2. 两个月重复运行均跳过，累计224432不增加。
3. 9月开始骑行116017；少于来源入库数是日期筛选差别，不是删除骑行。
4. 9月基线237站，39816行；每星期几4–5天。
5. 单元测试涵盖无效时间、DST、文件重复、骑行重复、冲突、新文件增量、失败回滚。
6. 自动核对通过，所有CSV可重建。

这些是目前所选输入的已观察结果，不作为其他月份的固定预期。
报告表述可用：已实现本地历史批处理流程、去重与增量入库、质量检查、历史分析和需求基线。

## 与完整项目的边界

第一阶段为历史 batch 核心与可复现交付。实时采集、站点映射、联合风险指标、Dashboard 尚未实现。
Part 5 的执行调度配置、完整双路径架构图和技术设计讨论仍需在整体项目中交付。
这个统一命令提供了可调度入口，但不等于已经配置了计划任务。
