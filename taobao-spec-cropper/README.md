# taobao-spec-cropper 淘宝规格图裁剪

一个把布料色卡、网格长图或单张商品图整理成淘宝规格图的技能（skill）：自动分析网格、裁切每个规格项，输出可直接上架的 **800×800 RGB PNG**，保留原始数字编号、统一编号位置，并按 `01_白色.png`、`02_杏色.png` 的顺序命名，最后打包成 ZIP。

适用于"裁规格图""色卡分割""保留编号""统一居中"等请求。不做重新设计商品、生成纹理或修改颜色。

## 成品标准

- 严格 800×800、RGB、真正的 PNG，白底；从原图直接处理，不做 JPG 中转。
- 保留完整布片、原始数字编号和已有的颜色文字；不裁入相邻项、页头广告、说明区或空白末格。
- 原内容等比例缩放，同一批使用共同缩放倍率。
- 有编号时以编号墨迹包围框为锚点：中心 `x=400`、下边界 `y=590`，布片和编号一起平移；无编号时按实际内容居中。
- 颜色名优先沿用原图文字，否则按可见颜色取常用中文名；无法判断时用"待确认颜色"。
- 输出到新目录 `<原图名>_规格图_800_PNG`，并生成只含成品 PNG 的同名 ZIP；已存在时换新后缀，绝不覆盖。

## 目录结构

```
taobao-spec-cropper/
├── SKILL.md                 # 技能定义与执行流程（供助手阅读）
├── agents/openai.yaml       # 界面展示信息（名称、简介、默认提示词）
├── references/layout.md     # 裁切配置 JSON 格式说明
└── scripts/
    ├── crop_specs.py        # 主脚本：preview / render
    └── test_crop_specs.py   # 行为测试（使用临时生成的图，不动项目图片）
```

## 环境要求

- Python 3.10+
- `pillow`、`numpy`、`opencv-python-headless`
- 可选：EDSR ×4 超分需要已有的 `models/EDSR_x4.pb` 和带 `cv2.dnn_superres` 的 OpenCV 安装；脚本不会自动下载模型。基础流程不依赖它。

## 使用方式

### 作为技能使用

安装到技能目录后，直接对助手说"把这张色卡裁成 800×800 规格图"并附上图片即可。网格分析、裁切配置、命名与校验都由助手完成，不需要用户提供坐标。

### 命令行使用

流程是先 `preview` 校对，再 `render` 出成品：

```powershell
# 1. 预览：生成编号定位图 source-boxes.png 和成品联系表 contact-sheet.png，不产出 ZIP
python scripts/crop_specs.py preview --input '原图.jpg' --layout '本次裁切.json' --output '_work/规格图预览'

# 2. 渲染：输出成品 PNG、_qa/ 质检文件和 ZIP
python scripts/crop_specs.py render --input '原图.jpg' --layout '本次裁切.json' --output '原图_规格图_800_PNG'

# 可选：复用已有的 EDSR 模型做超分清晰化
python scripts/crop_specs.py render --input '原图.jpg' --layout '本次裁切.json' --output '原图_规格图_800_PNG' --edsr-model 'models/EDSR_x4.pb'
```

路径可含中文和空格。预览与成品目录都必须尚不存在，重新运行请换新目录。

## 裁切配置

`--layout` 指向一个 UTF-8 JSON，完整字段说明见 [references/layout.md](references/layout.md)。要点：

- 所有 `box` 为 **EXIF 转正后**的原图像素坐标 `[left, top, right, bottom]`，右/下边界不含；`source_size` 必须与实际尺寸一致。
- **规则网格**：填 `grid.x_edges` / `grid.y_edges`（允许不等距）和可选的 `row_counts`，按行优先与 `items` 对应。
- **不规则布局**：逐项填 `box`，支持中间空位、错列、跨列。
- **编号纠正**：自动找编号只是候选定位、不是 OCR。偏离时用 `number_box` 精确圈住数字（或 `number_region` 给候选区域），必须对照 `source-boxes.png` 核实。
- **整批参数** `options`：编号锚点 `number_center_x=400`、`number_bottom=590`、目标内容宽度 `content_width=660`、安全边距 `margin=32` 及两个阈值，默认值即文档所示。
- 没有编号的项设 `"alignment": "content"`，不要虚构编号框。

## 输出与质检

- `preview`：原图框位图（红框小格、蓝框保留内容、绿框编号）、800×800 模拟成品联系表、`report.json`。
- `render`：每项 PNG + `_qa/`（框位图、联系表、`report.json`）+ 交付 ZIP。报告含源坐标、实际编号包围框、共享缩放倍率和校验结果。
- 脚本会自动校验：PNG 可解码为 800×800 RGB、编号中心与底边一致（±0.5 px）、ZIP 内容完整。但数值校验不能替代看图，交付前应打开联系表检查首项、一位/两位编号交界、末行和黑白布片。

## 可选生成 SKU Excel

使用技能时可以选择“只裁图”或“同时生成 SKU Excel”，未选择时默认只裁图。也可以用已有规格图单独生成 SKU。安装 `openpyxl` 后运行：

```powershell
python scripts/generate_sku_excel.py --root '项目目录' --template '项目目录/SKU模板.xls' --sku-excel
python scripts/test_generate_sku_excel.py
```

每个商品文件夹生成 `<商品文件夹名>_SKU.xlsx`：颜色分类如 `01#白色 (半米价)`，价格直接取 `商品信息.json` 的 `price`，数量固定 100。保留小数价格及模板隐藏工作表，不覆盖已有表。详见 [SKU 输入与检查规则](references/sku-excel.md)。

## 裁图测试

```powershell
python scripts/test_crop_specs.py
```

测试使用临时目录里生成的图，不会改动项目中的任何图片。修改脚本后请先跑测试，再用实际原图做一次 preview 检查。

## 已知限制

- 超分与缩放都不能恢复原图不存在的真实细节；不重绘数字、不改变布料颜色。
- 颜色名是视觉描述，不代表准确色号或实物色。
- 淡色（如白色）布料若被自动裁窄，用更保守的 `box` 并设置 `trim: false`。
