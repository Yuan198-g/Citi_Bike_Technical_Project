# 阶段2：实时站点采集，第一步

## 放置与运行

将 poll_stations.py、test_stations.py、live_queries.sql 放到原 citi_bike_phase1 文件夹中，与 pipeline.py 同级。
无需新依赖。原来的历史数据库不需要改动。

```powershell
python poll_stations.py --cycles 3 --interval 60
python -m unittest test_stations -v
```

第一次采集后等待至少60秒，再采集第二次，再等待后采集第三次，总时长至少约2分钟。
命令在网络请求过程中可能暂时没有输出。不要因为没立刻输出就启动第二个采集进程。
TTL>60时程序自动提高间隔。没有并行采集或额外高频访问。

持续采集直到 Ctrl+C：

```powershell
python poll_stations.py --cycles 0 --interval 60
```

默认300秒源新鲜度阈值；车辆≤3为低车，空位≤3为低空位，支持 --stale-after / --low-bikes / --low-docks。
超过源TTL前不开始下一轮。每轮顺序抓取信息和状态，不声称两者是同一时刻的原子快照。
源URL来自官方2.3 discovery中的en feeds；每次程序启动重新发现，期间每轮获取两份数据。

## 采集的是什么

GBFS是站点状态快照，不是每一次骑行事件。
同一个站点从14辆变成11辆，表示可用车辆净减少3辆，不能说3次出发。
还车、调车和可用/不可用状态转换都影响这个数。

来源：https://citibikenyc.com/system-data
官方当前入口：https://gbfs.citibikenyc.com/gbfs/2.3/gbfs.json
参考规范：https://github.com/MobilityData/gbfs/blob/v2.3/gbfs.md
GBFS使用版本2.3；不套用3.0的字段或时间格式。版本改变时停止并检查。
本次观察信息与状态TTL均60秒；没有从页面确认独立请求限额，故限制为TTL允许的低频轮询。
HTTP429尊重整数秒Retry-After；其他请求失败最多3次并指数退避。

范围：information.short_name 以JC或HB开头的当前站点。
这是明确的编号前缀选择规则，不声称源系统全部站点都属于此范围。
状态中无法找到信息的站点：隔离并记录“范围未知”，不猜测其位置。
官方当前接口的 station_id 与历史 JC009 不同。short_name 保留历史风格编号，后续需要验证映射。
当前采集数量与去年历史数量不一定相等；站点增减、编号变化及来源口径需要阶段3进一步检查。

## 输出在哪里

- data/operations.sqlite：实时数据库，与历史 citibike.sqlite 分开，减少相互影响。
- data/raw_live/discovery.json / feed_manifest.json：官方自动发现响应、版本、URL与发现时间。
- data/raw_live/YYYY-MM-DD/<hash>.json：两份原始响应字符串和第一次获取时间。
- data/reports/live/collection_summary.json：最近成功轮询时的统计，带observed_at。

collection_summary.json 是当时的报告，不会在程序停止后自动变为实时数据。
新鲜度实时判断应查 station_latest；这个视图使用当前UTC时钟，停止轮询后也会变 stale。
程序启动失败直接非零退出；单轮失败记录live_polls，有限次采集结束有失败时非零退出。
失败轮询不清空之前成功的库存，也不会改写为零。

DBeaver：新建SQLite连接，打开原项目 data/operations.sqlite，运行live_queries.sql。
不要在历史citibike.sqlite中查询station_latest，它不在那份数据库里。

## 表和视图

| 对象 | 粒度与用途 |
|---|---|
| live_polls | 一行一次采集尝试，含成功/重复/失败、时间、间隔、错误 |
| live_batches | 一行一个不同的信息+状态原始载荷组合，SHA-256主键 |
| station_snapshots | 一行一个载荷组合、站点；联合主键防止重复 |
| live_quarantine | 无效或缺失记录及原始内容、原因 |
| station_latest | 每站最新可信源时间的状态，当前年龄、过期标志和低库存标志 |
| station_inventory_changes | 各站连续快照的可用车辆净变化及前一个快照 |

完整重复载荷只增加轮询日志，不增加批次和站点历史。
源feed last_updated改变时，即使库存没变，也属于新快照；因此快照吞吐量不代表库存变化量。
同样源报告时间的重复站点不会产生新的有效delta。
数据全部以live标记，单元测试人工数据位于临时目录，与实采证据分开。
当前未提供用户可执行 replay 命令；原始数据保留支持后续重放开发。

## 字段映射

| 规范原字段 | 规范化字段 |
|---|---|
| station_id | station_id（源ID，字符串） |
| short_name / name | short_name / name |
| 获取完成时间 | observed_at（UTC ISO时间） |
| station_status.last_updated | source_feed_time（UTC epoch秒） |
| stations.last_reported | source_reported_at（UTC epoch秒） |
| station_information.last_updated | information_feed_time |
| num_bikes_available / num_docks_available | bikes_available / docks_available |
| capacity | capacity |
| num_bikes_disabled / num_docks_disabled | bikes_disabled / docks_disabled，可为NULL |
| is_installed / is_renting / is_returning | 同名0/1字段 |
| lat / lon / region_id | latitude / longitude / region_id |

原始响应字符串保留所有未规范化字段，未改变字段名称。

## 验证、指标和恢复

非负整数车数/空位/容量/不可用数量；标志是0/1；坐标纬度40–42、经度-75至-72。
站点报告时间缺失或比采集时间未来超过60秒：隔离。
源信息和状态列表重复station_id：整批失败回滚，不随意选一条。
版本、必需结构不匹配：整批失败。所有区域站均无效时拒绝更新最新状态。
缺失metadata或status单独记录；当前载荷缺失站点时旧状态保留但标记过期。
容量与车/空位/不可用数不一致：保留并标warn，不假设每个数相加必等capacity。
capacity未知或零时utilization=NULL，不除以零；原值仍保留。

is_operational = installed AND renting AND returning。
low_bike仅在允许租车的已安装站计算；low_dock仅在允许还车的已安装站计算。
使用这些标志做运营汇总必须同时筛is_stale=0。
利用率定义：(available bikes + disabled bikes) / capacity。
分母包括不可用泊位；缺失disabled bikes或占用数>capacity时返回NULL。
容量警告仍需人工解释，不能把利用率当成准确物理占用测量。

is_stale：状态feed或station report比当前时钟老于300秒、未来超过60秒、
当前有效批次未包含该站，或源时间回退。
源时间回退不会用旧报告覆盖较新记录，并显示source_regressed=1、is_stale=1。
metadata时间独立保存；此版没有独立metadata-age过期策略，容量变更的双feed不同步保留为警告。

delta仅在前后都运营、源station时间前进、报告间隔≤新鲜度阈值、
且前后采集时feed和station报告新鲜时计算；否则NULL。
长时间停采后的变化不伪装成一分钟变化。delta为净可用库存变化，非骑行数。

采集批次、站点历史和成功poll记录在同一数据库事务中。
中断后未提交记录回滚；原始文件可能保留，重启再次获取并安全处理。
原始响应文件不是数据库事务的一部分；不把孤立原始文件算作成功采集。
派生视图每次启动重建，历史记录保留。
日志不会自动清理；长时间运行要制定留存策略。仅支持一个本地采集进程。

## 本阶段验收

- 3次以上成功实采，保存时间范围、有效快照数和过期数量。
- 第二次运行在同一数据库继续追加；重复载荷不膨胀。
- 在DBeaver看同一站多条库存历史；库存不变也是有效观察。
- python -m unittest test_stations -v：5项测试，覆盖重复、重启、库存delta、过期、
  运营限制、无效记录、缺站、容量异常、源时间回退、事务回滚。

这是阶段2的采集与处理步骤。Dashboard的实时刷新、位置搜索/地图和完整展示证据
尚未完成；历史需求结合库存属于阶段3，自动调度和完整架构属于后续整体收尾。
