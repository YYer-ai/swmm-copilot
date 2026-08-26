# swmm-copilot（内涝快评）

自然语言驱动的城市内涝快速评估工具链：圈定区域 → 自动取数 → SWMM 模拟 → 内涝风险图 + 中文评估报告。

> 定位为**快速评估**（规划级/初筛级），非工程级详细设计。

## 当前状态（v0.1 预览）

- ✅ **暴雨强度公式库**：5 城市 49 片区（广州 6 区、深圳 4 流域、重庆 38 区县、北京/南宁/海口经典版），全部标注官方来源，与官方公布雨量表交叉验证（复算误差 < 0.5%）
- ✅ **设计暴雨生成**：任意重现期（1~100 年）暴雨强度求值 + 芝加哥雨型（总量守恒）
- ✅ **M1 最小链路**（`examples/demo_pipeline.py`）：bbox → DEM（Copernicus GLO-30，首次在线缓存、之后**完全离线**）→ 填洼/D8/汇流累积 → 网格概化 SWMM 建模（多排放口、管径按汇流量 3/8 次幂、井底埋深递推）→ pyswmm 模拟 → 节点溢流折算积水深 → matplotlib 本地渲染风险图。除公式库外无在线依赖，`--offline` 强制离线
- 🚧 M1 完整版：ESA WorldCover 自动不透水率、OSM 建筑密度修正、行政区名圈定
- 🚧 M3 LLM Agent 化 / M4 中文评估报告（规划中，见路线图）

> 模型为**快速评估级**（规划/初筛），管网为概化生成（非真实管网数据），积水深为节点溢流折算（非二维漫流），正式工程请以实测与详细设计为准。

## 快速开始

```powershell
python -m pip install pyyaml
python tests/test_design_storm.py      # 自检（含官方雨量表交叉验证）
python examples/demo_storm.py          # 生成设计暴雨雨型
```

代码调用：

```python
from swmm_copilot import load_db, rain_depth, chicago_hyetograph

db = load_db()
zone = db["深圳市"]["中部流域和水系"]
print(rain_depth(zone, P=50, t=120))                 # 120min 设计总雨量 mm
hy = chicago_hyetograph(zone, P=50, duration=120, dt=5, r=0.4)  # 芝加哥雨型
```

## 数据来源与公式形式

| 城市 | 来源 | 性质 |
|---|---|---|
| 广州 | 市水务局《暴雨强度公式编制与设计暴雨雨型研究技术报告（简本）》 | 官方 PDF，2021 修编 |
| 深圳 | 市气象局等三部门《深圳市分流域暴雨强度公式及查算图表》 | 官方 PDF，2024 版 |
| 重庆 | [Chicago_rain_pattern](https://github.com/maoyu92/Chicago_rain_pattern) 汇编 | 开源汇编（源头为官方公布文件） |
| 北京/南宁/海口 | 《我国 317 座城市暴雨强度公式》汇编 | 经典版，正式使用请核对当地新版 |

公式库为纯 YAML（`data/rainfall/`），收录三种官方形式：总公式 `q=A(1+ClgP)/(t+b)^n`、
重现期区间参数公式（A/b/n 随 P 变化）、单一重现期公式（校验用）。

**欢迎 PR 补充城市**：请参照 `data/rainfall/shenzhen.yaml` 的格式，附公式来源链接；
若来源含官方雨量表/单一公式，请一并填入 `validation` 字段（用于自动验证）。

## 路线图

- [x] M1 数据管道（最小版）：bbox → DEM（Copernicus GLO-30）缓存离线；填洼/D8/汇流累积
- [ ] M1 完整版：土地覆盖（ESA WorldCover）自动不透水率 + OSM 建筑 + 行政区圈定
- [x] M2 模拟编排（最小版）：网格概化 → `.inp` → pyswmm → 积水深折算 + matplotlib 风险图
- [ ] M3 LLM Agent 化：自然语言交互、工具编排、多轮追问
- [ ] M4 输出：GeoTIFF 风险图 + 在线底图交互图 + 中文评估报告

## 依赖

Python ≥ 3.10。当前模块仅依赖 `pyyaml`；GIS/模拟链路（M1/M2）将增加 rasterio、pysheds、pyswmm、swmmio。

## 许可

MIT（见 [LICENSE](LICENSE)）。公式数据来自政府公开文件与公开汇编，按原出处标注来源；工程使用请以当地最新公布文件为准。
