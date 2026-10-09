# Citi Bike — 第一阶段：历史数据流程

## 先运行

安装 Python 3.10 或更新版本。在 Windows 上安装时区数据库：

```bash
python -m pip install tzdata
```

解压后，用 VS Code 打开 `citi_bike_phase1` 文件夹，在终端运行：

```bash
python pipeline.py --month 202509
```

程序自动下载 Jersey City / Hoboken 的月度 ZIP，处理其中所有 CSV，不采样。
第一次会下载数据。第二次运行同一命令，应该显示 `already_processed`，总数不变。
换月份，例如 `--month 202510`，会追加新文件，旧文件不重建。
下载失败会最多尝试三次；404 时请核对官方文件列表，不要把失败当成空月份。

## 文件分别做什么

- `pipeline.py`：下载、清洗、验证、入库、更新汇总视图。
- `queries.sql`：练习查询每天、小时、站点、会员、车型和异常记录。
- `test_pipeline.py`：用人工样例验证去重、冲突、增量、失败回滚和夏令时。
- `VERIFICATION.json`：作者实际运行官方历史文件得到的验证证据。

运行后生成：

- `data/raw/YYYYMM/`：原始 ZIP，按来源月份组织，保留所有原始字段。
- `data/citibike.sqlite`：处理后的数据库。
- `data/reports/`：每个来源文件的处理计数 JSON，以及每日骑行数 CSV。

这个下载包只包含代码与验证证据，不包含原始数据和数据库；它们会在本机运行后生成。

## 查看运行结果

先打开 `data/reports/trips_daily.csv`。再用 VS Code 的 SQLite 查看工具或 DB Browser for SQLite 打开数据库，执行 `queries.sql`。
例如：

```sql
SELECT local_date, trips FROM trips_daily ORDER BY local_date;
SELECT local_hour, COUNT(*) AS trips
FROM fact_trip GROUP BY local_hour ORDER BY local_hour;
```

理解这两条查询后，再读 `pipeline.py` 的三个主要函数：
`download()` 获取并保留数据；`normalize()` 验证一条骑行；`ingest()` 处理整个文件并入库。

## 数据规则与模型

来源：https://citibikenyc.com/system-data
文件：https://s3.amazonaws.com/tripdata/JC-202509-citibike-tripdata.csv.zip
范围：JC 来源文件覆盖的 Jersey City / Hoboken 骑行，不声称代表纽约整个网络。
不按地理坐标裁剪，坐标只做区域合理性验证。不按文件月份删除跨月骑行。
真实有效记录的开始日期范围为 2025-08-31 至 2025-09-30。
后续实时指标必须选择对应地区，并单独验证站点编号映射。

- `fact_trip`：一行一条骑行，主键 `ride_id`；站点编号始终保留为字符串。
- `trip_arrival_time`：一行一个已接受 ride_id，保存结束时的当地日期和小时；与 fact_trip 一对一。
- `processed_files`：一行一个 ZIP 内容 SHA-256，保留来源 URL、处理时间和分类计数。
- `rejected_records`：一行一个被隔离的来源记录，保留文件摘要、CSV 名、行号、原因和原始 JSON。
- `trips_daily`：一行一个当地日期。
- `station_departures_hourly` / `station_arrivals_hourly`：一行一个站点、当地日期、小时。

聚合使用 SQL 视图，始终查询当前事实表；增加月份只处理新文件，查询时计算汇总。
SQLite 是本地单写入者方案，不是大规模数据仓库；扩大到纽约多个月时应重新评估 DuckDB 等工具。

时间处理：本版明确假设无时区的原始时间属于 `America/New_York`，不是 UTC。
官方页面未明确规定这些时间的时区，因此这是实现假设，需要在最终技术报告中注明并进一步核实。
保存 UTC 时间，统计纽约当地日期、小时和星期；星期一=0，星期日=6。
夏令时重复或不存在的时间被隔离，不随意选择一个解释。
Windows 通常需要 tzdata 包。

质量规则：

- ride_id 必须存在；文件缺少必需列时整个文件失败。
- 时长必须大于0、不超过24小时。这是本项目的明确筛选规则，不声称所有超时骑行都错误。
- 可用坐标必须在纬度40–42、经度-75至-72范围内；缺失坐标允许保留。
- 缺失站点编号变成 NULL，骑行仍可用于总量分析；站点汇总排除缺失端点。
- 未知会员/车型类别保留原值，不自动删除。
- 文件 SHA-256 已处理时跳过；相同 ride_id 和相同标准化字段只计一次。
- 同 ride_id 但标准化字段不同：保留先入库的记录，后续冲突记录隔离。原始非模型字段仍保存在 ZIP 中。
- 一整个 ZIP 的入库与处理清单写入在同一事务中，失败回滚，重启可重试。
- 已缓存原文件不会每次重新下载；此版不自动检测远端同名文件更新。若需处理修订版本，应先另存原文件并提供新版文件；本版不实现事实记录修订。
- 报告 CSV/JSON 属于派生输出；数据库事务是权威状态。报告写入失败不回滚已提交数据。

计数满足：原始数 = 新增数 + 无效数 + 相同重复数 + 冲突数。

## 实际验证

真实历史文件：116071 条原始，116033 条接受，38 条时长不符合规则；0 条重复、0 条冲突。
有效记录中 450 条缺少终点编号。重复运行后事实表仍为116033行，每日汇总总数也是116033。

在本文件夹运行测试：

```bash
python -m unittest -v
```

测试使用人工样例，与真实历史数据验证分开。

## 尚未完成的阶段

本版只完成历史数据核心流程。实时轮询、站点 crosswalk、需求基线、Dashboard、自动调度和完整架构说明将在后续阶段完成。
