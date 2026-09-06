# 个人 Skills 仓库

个人自用的 agent skills 收藏地：存放为自己编写和维护的技能（skill），供 ZCode 等支持 SKILL.md 规范的 agent 加载使用。

## 技能列表

| 技能 | 说明 |
| --- | --- |
| [taobao-spec-cropper](taobao-spec-cropper/) | 把布料色卡、网格长图或商品图裁成 800×800 PNG 规格图，保留编号、统一位置、按序命名并打包 ZIP |

各技能的详细用法见其目录内的 `README.md` 与 `SKILL.md`。

## 安装

### 方式一：npx skills（推荐）

本仓库已发布在 GitHub（`Aaazlj/skills`），在任意 agent 项目里执行即可安装（CLI 会自动检测已安装的 agent）：

```powershell
# 交互式：列出仓库中的技能，选择后安装到检测到的 agent
npx skills@latest add Aaazlj/skills

# 只看仓库里有哪些技能，不安装
npx skills@latest add Aaazlj/skills --list

# 只安装某个技能，-g 装到用户级目录（对所有项目生效，默认仅当前项目）
npx skills@latest add Aaazlj/skills --skill taobao-spec-cropper -g

# 指定目标 agent；CI 中可再加 -y 跳过确认
npx skills@latest add Aaazlj/skills --skill taobao-spec-cropper -a claude-code -a opencode -y
```

CLI 扫描仓库里的 `SKILL.md`（本仓库技能位于根目录子文件夹，靠递归搜索发现），并按各 agent 的约定安装到对应技能目录（如 `.claude/skills/`、`.agents/skills/`）。

### 方式二：手动复制

把需要的技能目录复制（或克隆整个仓库后软链）到 agent 的技能目录即可，例如：

```powershell
# 用户级技能目录（对所有项目生效）
~/.agents/skills/

# 或项目级技能目录（仅当前项目生效）
<项目>/.agents/skills/
```

例：

```powershell
Copy-Item -Recurse taobao-spec-cropper ~/.agents/skills/
```

## 技能目录结构约定

每个技能一个独立目录，一般包含：

```
<skill-name>/
├── SKILL.md          # 技能定义：名称、触发描述、执行流程
├── README.md         # 面向人的说明文档
├── agents/           # 界面展示信息（可选）
├── references/       # 详细参考文档（可选）
└── scripts/          # 随技能提供的可执行脚本（可选）
```

## 维护

- 新技能：新建目录，写好 `SKILL.md`（frontmatter 含 `name`、`description`）后在本表登记。
- 修改脚本后跑技能自带测试（如有），如 `python <skill>/scripts/test_*.py`。
