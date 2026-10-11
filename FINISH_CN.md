# 最后验收

1. 将本包代码放入你选定的项目目录。它必须已有 data/citibike.sqlite、data/operations.sqlite 和历史原始 ZIP。包内不含数据库。根目录与 citi_bike_phase1 不要混用；先看现有 dashboard 底部的数据库路径，选它实际使用的目录。包里的 Python 文件是此前版本的统一整理，覆盖同名代码前保留你自己修改过的版本。
2. 在该目录运行：

```powershell
python workflow.py check
```

预期：20 项测试通过，最后显示 FINAL CHECKS PASSED。会生成 data/reports/final_acceptance.json。已有数据过期不会导致验收失败，只要它正确显示为过期。

3. 日常使用仍是：

```powershell
python platform_dashboard.py --baseline-month 202509
```

另一个终端按需要运行：

```powershell
python poll_stations.py --cycles 3 --interval 60
```

4. 调度功能已经提供，不必为提交一直开着电脑。要演示时运行 python workflow.py schedule；它根据 workflow.json 每天执行批处理，必须保持终端开启。默认月份固定，修改配置才能添加月份。它不是自动安装的 Windows 服务，也不会启动实时采集。
5. 提交代码、README.md、TECHNICAL_DESIGN.md、workflow.json、requirements.txt 和验收报告；另附你自己保存的页面截图。原始数据/数据库较大，不默认上传 GitHub；README 有自动下载运行方法。若要求可离线复现，再另外提交实际数据和 raw_live，明确采集时间，不要声称过期数据实时。

全部通过后，五个阶段的核心交付可以收尾。不要继续添加功能，也不要把规则指标写成已经验证准确的预测模型。
