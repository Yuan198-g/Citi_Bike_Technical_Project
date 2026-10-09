# Part 2 收尾：运营 Dashboard

## 安装位置

把 operations_dashboard.py、test_operations_dashboard.py 放在原 citi_bike_phase1 文件夹中，
与 poll_stations.py 同级。不要建立新的 data 目录或复制旧数据库。
无需安装额外依赖，Python 3.10+ 即可。

## 先看旧快照

在原项目 PowerShell 运行：

```powershell
python operations_dashboard.py
```

用浏览器打开 http://127.0.0.1:8501 。保持终端开启，Ctrl+C停止页面服务。
如果端口占用，使用 `python operations_dashboard.py --port 8502`，打开对应8502地址。

默认 Recorded snapshots：保留的旧库存也可以看，但标为历史快照，并显示Stale数量。
Current operations：总数只计数据新鲜且installed、renting、returning全部为1的站点。
如果你没有继续采集，这几个当前总数可能为0，这是正确行为，不是没加载数据。
站点列表仍保留历史值并显示Stale标记，便于诊断。
容量与库存不一致会显示Quality warning；选中站点可查看具体原因。

## 页面内容

- 最新成功采集时间，页面读取时间，浏览器显示时区。
- 当前或已记录的运营站点、可用车辆、可用空位、过期站点数量。
- 可搜索的站点库存列表，运营限制、低车/低空位、质量警告。
- 每个站的名称、两个编号、纬度经度、容量、运营状态与利用率。
- 所选站点可用车辆和空位时间曲线，以及逐轮快照表。
- 累计成功轮询、不同载荷批次、快照和隔离数量。

搜索和站点详情含位置信息，是站点地图要求允许的可搜索位置视图替代方案。
暂未嵌入地图。后续Part4可以继续增加地图、历史分析和联合风险指标。

页面显示时间由浏览器时区转换；数据库UTC值不改。
源报告时间与feed更新时间分开显示。源报告时间单位epoch秒。
Latest successful poll是采集时间，不等于station report时间。
完全重复载荷可能让采集时间前进但历史快照数不增加。
库存不变是合理观测，不能为了演示强制改变它。
数据接口每10秒查数据库，不请求GBFS；源采集每60秒独立进行，遵守TTL。
前端失去数据库读取能力时显示明确错误；当前总数不继续冒充有效读取。

## 验证页面真的会更新

第一个PowerShell保持Dashboard运行。
第二个PowerShell进入同一个项目文件夹，运行：

```powershell
python poll_stations.py --cycles 3 --interval 60
```

在页面切到Current operations，并观察：

1. 页面读取时间每约10秒变化。
2. 每轮采集后Latest successful poll时间前进。
3. 成功轮询次数增加；若源载荷改变，快照数也增加。
4. 新鲜数据进入当前总数；旧站点报告仍可能Stale，不应强制变为新鲜。
5. 同一站的快照表出现新行，曲线与库存表同步读取。

页面每次按真实数据库状态刷新，日期和库存不会因为页面刷新而被改写。
换站或输入搜索时也不改源数据。

保存验收证据：记录采集前后的Latest successful poll、成功轮询数、快照数；
保存两张带上述信息的页面截图。不能只拿Page data refresh前进来证明源更新。
停止采集超过新鲜度阈值后，保持页面运行，确认Current totals排除过期记录。

## 测试

```powershell
python -m unittest test_stations test_operations_dashboard -v
```

预期8个测试方法通过：5个采集测试、3个Dashboard数据测试。
测试使用临时人工数据，不当作真实采集证据。

开发端已验证：HTTP服务、读取字段、时间序列和质量警告、过期处理、
不存在的数据库不被自动创建、JavaScript语法，以及实际GBFS采集后HTTP响应更新。
开发环境无法取得浏览器可执行文件，因此没有声称完成浏览器视觉或定时器实测；
浏览器显示、搜索交互、曲线布局和10秒刷新仍需本机验收。
PHASE2_FINISH_VERIFIED.json是开发验证记录，不替代你本机的截图和输出。

## 可靠性与边界

数据库只读连接，刷新不会改库存或采集日志。
每个请求单独连接并显式关闭，避免Windows文件占用。
每个响应在同一读事务内形成，减少卡片、列表和历史之间的不同步。
没有新数据时页面仍刷新新鲜度，但历史库存保持原值。
页面获取失败会显示错误；下一次成功请求恢复。
服务仅绑定127.0.0.1，适合本地练习，不是公开部署。
只允许一个Dashboard实例使用同一个端口；采集进程与页面进程各一个即可。
曲线最多显示所选站最近600条记录，横轴使用实际采集时间；
线段连接观测点，不意味着间隔里发生了线性库存变化。

净库存变化不是骑行数。利用率计算规则继承采集视图：
(available bikes + disabled bikes) / reported capacity；缺失或无效分母返回N/A。
低车/低空位采用快照中保存的阈值，过期标志优先于任何运营解释。
这里的Attention只是当前/历史库存与质量标记，不是历史需求联合风险。

当采集、测试、浏览器显示与源更新证据都通过时，Part2可以完成验收。
Part3历史需求连接、Part4完整双视图Dashboard、Part5调度和架构仍需后续完成。
