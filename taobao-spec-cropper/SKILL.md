---
name: taobao-spec-cropper
description: 将用户提供的布料色卡、网格长图或单个商品图片裁成独立的 1:1、800×800 PNG 规格图，并可按商品信息生成 SKU Excel。适用于“裁规格图”“色卡分割”“保留编号”“统一居中”“生成 SKU”等请求；保留原图编号、统一编号锚点，按 01_颜色.png 起顺序命名。不用于重新设计商品、生成纹理或修改颜色。
---

# 淘宝 800×800 PNG 规格图

将原图里的每个规格项整理成可直接使用的正方形 PNG。用户只需给图片；网格分析、裁切配置、命名与校验由你完成，不要求用户提供坐标。

## 默认成品标准

- **严格 800×800、RGB、真正的 PNG**，白底；从原始图片直接处理，不拿已压缩的中间 JPG 再转存。
- 保留完整布片、原始数字编号以及同一项已有的颜色文字；不要裁入相邻项、页头广告、说明区或空白末格，也不输出详情页色卡里没有布片的空白占位圆。没有编号的图片不补造编号。
- 原内容等比例缩放。同一批使用共同缩放倍率，不逐张拉伸或分别放大编号。
- 有编号时，以**编号墨迹包围框**为锚点：中心 `x=400`、下边界 `y=590`；`y=590` 指包围框的下边界，不是最后一个着色像素。编号不是“编号＋下方颜色文字”的整体，也不是原网格的中心。允许因奇偶像素宽度产生 ±0.5 px 横向误差。
- 布片和编号一起平移，保留二者相对位置。无编号时按实际内容居中。不同版式确需更改编号高度时，统一更改整批锚点。
- 按从左到右、从上到下的顺序从 1 命名：**必须是 `01_白色.png` 这种 `序号_中文颜色名.png` 形式，绝不允许用 `01_No.01.png` 这类原图编号做文件名**。原图已有颜色名称时优先沿用，否则按可见颜色取常用中文名；这只是视觉描述，不代表准确色号或实物色。无法判断时用“待确认颜色”并说明。详情页圆形色卡即使原图只印了 `No.01` 编号，也必须按可见颜色命名（`01_白色.png`），`crop_detail_grid.py` 的 `--names` 为必填参数，不传会直接报错。
- 默认输出到商品文件夹的 `规格图/` 目录，**默认不生成 ZIP、不生成 `_qa` 质检目录**；需要时用 `crop_specs.py render` 的 `--zip` / `--qa` 显式开启。已存在时换新后缀；未经用户明确要求不覆盖原图、旧成品或旧 ZIP。

## 处理流程

1. 定位用户这次提供的原图并实际查看，确认方向、有效像素尺寸、项数、行列、空位及编号位置。按 EXIF 转正后的图建立坐标。只有图片不可访问或内容确实无法判断时才向用户询问，不把项目里的其他图片当成新附件。
2. 创建本次裁切的 JSON 配置，格式见 [references/layout.md](references/layout.md)。规则网格可填写行列边界，不规则布局逐项填写 `box`。按实际间隙和轮廓取边界，不机械均分整张长图。不要把历史样例的 35 项、3 列、坐标或颜色清单套到新图。
   - 若是详情页长图里嵌入的 4 列圆形色卡（每项下方 `No.01` 这类编号），优先使用 [scripts/crop_detail_grid.py](scripts/crop_detail_grid.py)。它会检测圆形色卡中心，自动跳过没有布片的空白占位圆（要保留时传 `--keep-empty`），按行优先生成 800×800 PNG，默认输出到 `详情图/` 的上一级 `规格图/`，且不生成 ZIP 或 `_qa`。必要时传 `--rows`、`--cols` 固定行列，避免页头/背面示意图干扰。**`--names '白色,米白色,…'` 为必填**：先看图确定每个有效色卡的颜色名再传入，数量与有效色卡不一致会报错。
3. 用随技能提供的 `scripts/crop_specs.py preview` 生成编号定位图和成品联系表，实际打开 `source-boxes.png`、`contact-sheet.png`。自动找编号只是候选定位，不是 OCR；校对一位数、两位数和额外文字行。偏离时用 `number_box` 明确圈住数字，不能用估计位置假装检测成功。白色布料若被自动裁窄，使用更保守的 `box` 并设置 `trim: false`。
4. 预览确认后运行 `render`。用户关心清晰度时，可复用当前项目已有的 `models/EDSR_x4.pb`，且必须检查 `cv2.dnn_superres` 可用并先试一张。模型不可用或效果不自然时使用默认 Lanczos 并说明；不要为普通裁剪自动下载大模型或调用生成式重绘。超分与 PNG 都不能保证恢复原图不存在的真实细节，不重绘数字、不改变布料颜色。
5. 查看实际成品：数量与顺序正确、每张可解码为 800×800 RGB PNG、编号中心和底边一致、布片/文字无截断、相邻项无混入、文件名为 `01_颜色.png` 形式。需要留档质检产物时用 `render --qa` 生成 `_qa/` 再看 `report.json`；数值校验不替代看图，至少打开第一张、一位/两位编号交界、末行和白/黑布片等异常项。不能只检查画布尺寸后宣称已经居中。
6. 交付成品文件夹的绝对路径链接，简述张数、800×800 PNG、编号对齐情况。颜色名有不确定项或放大了低清原图时如实说明。

## 运行

使用 Python 3.10 或更新版本，先检查能否导入 `PIL`、`numpy`、`cv2`。如缺依赖，优先使用项目已有环境，或在项目本地虚拟环境安装 `pillow numpy opencv-python-headless`；不要为普通裁切替换已有的 OpenCV/Contrib 安装。EDSR 额外需要已有的 `cv2.dnn_superres`，基础流程不依赖它。

以下 PowerShell 示例从项目根目录运行；从其他目录调用时，将脚本路径替换为本技能的实际绝对路径。原图和配置路径均可含中文、空格。

```powershell
python '.agents/skills/taobao-spec-cropper/scripts/crop_specs.py' preview --input '原图.jpg' --layout '本次裁切.json' --output '_work/规格图预览'
python '.agents/skills/taobao-spec-cropper/scripts/crop_specs.py' render --input '原图.jpg' --layout '本次裁切.json' --output '规格图'
python '.agents/skills/taobao-spec-cropper/scripts/crop_specs.py' render --input '原图.jpg' --layout '本次裁切.json' --output '规格图' --zip --qa
python '.agents/skills/taobao-spec-cropper/scripts/crop_detail_grid.py' --input '商品/详情图/详情图01.jpg' --cols 4 --names '白色,米白色,浅米色,浅杏色'
```

`render` 默认只交付 PNG（无 ZIP、无 `_qa`）；`--zip`、`--qa` 仅在用户明确要求时追加。

沿用已有 EDSR 清晰化时，在 `render` 命令追加 `--edsr-model 'models/EDSR_x4.pb'`。每项处理前会输出进度；模型异常直接报告错误，不静默冒充超分成功。

## 可选：生成 SKU Excel

开始时确认本次选择“只裁规格图”还是“裁规格图并生成 SKU Excel”。已有明确选择时直接沿用；未说明时提供一次可选询问并继续裁图，未选择生成则默认不生成 Excel。也支持直接从已有规格图生成 SKU，无需重新裁图。生成时读取 [references/sku-excel.md](references/sku-excel.md)，使用 [scripts/generate_sku_excel.py](scripts/generate_sku_excel.py)，并传入项目根目录、模板和 `--sku-excel`：

```powershell
python 'scripts/generate_sku_excel.py' --root '项目根目录' --template 'SKU模板.xls' --sku-excel
python 'scripts/generate_sku_excel.py' --root '系列目录' --product-dir '商品目录' --template 'SKU模板.xls' --sku-excel --spec-dir-name '规格图'
```

脚本处理根目录下每个包含 `商品信息.json` 的商品文件夹（可用 `--exclude` 排除），从其 `规格图` 或 `*_规格图_800_PNG` 目录读取按序 PNG 文件名；**默认输出到规格图目录内的 `sku.xls`**（内容为 XLSX 工作簿）。要改回商品目录下的 `<商品文件夹>_SKU.xlsx`，传 `--output-in-product-dir --output-name '名称.xlsx'`。遵守本次用户指定的商品范围，不把历史排除项永久套用到新任务。表头固定为“颜色分类、价格、数量”，**颜色分类格式必须是 `01#白色 (半米价)` 这种 `序号#中文颜色名 (半米价)` 形式**（颜色名直接取规格图文件名，所以规格图必须先按颜色名命名），价格直接取 JSON 的 `price`，不除以二，数量固定为 `100`。保留模板的工作表结构和隐藏工作表；已有同名输出时停止，不覆盖旧文件。需要 `openpyxl`，只裁图时不需要它。

修改辅助脚本后运行 `python '.agents/skills/taobao-spec-cropper/scripts/test_crop_specs.py'`，再对实际原图做一次预览检查。
