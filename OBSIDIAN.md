# 用 Obsidian 发布这个博客

这套方案保留现有 Gmeek 博客，只把写作入口换成 Obsidian：

```text
私人 Obsidian Vault
  └─ Enveloppe 只上传 share: true 的笔记
      └─ content/posts/*.md + static/attachments/*
          └─ GitHub Action 同步为 Issues
              └─ Gmeek 生成并发布 GitHub Pages
```

> [!IMPORTANT]
> 不要把整个私人 Vault 当成这个公开仓库来同步，也不要用 Obsidian Git 把整个 Vault 推到这里。这个仓库是公开的；Enveloppe 的作用正是只挑选允许公开的笔记。

## 一次性设置

### 1. 在 Obsidian 安装 Enveloppe

打开 **设置 → 第三方插件 → 浏览**，搜索并安装 **Enveloppe**，然后启用。

官方项目和说明：[Enveloppe](https://github.com/Enveloppe/obsidian-enveloppe)。它是“选择性发布器”，不是 Vault 备份工具。

### 2. 连接 GitHub

在 Enveloppe 设置的 GitHub 区域填写：

| 设置 | 值 |
| --- | --- |
| GitHub username | `zhjhaibin` |
| Repository name | `zhjhaibin` |
| Branch | `main` |
| Automatically merge PR | 开启 |

点击插件提供的 Token 链接创建 GitHub Token，再粘贴回 Obsidian。只在自己的电脑中保存 Token，不要把它写进笔记或提交到仓库。创建后先运行命令 **Test the connection to the configured repository**。

如果使用 GitHub Fine-grained token，建议只授权 `zhjhaibin/zhjhaibin` 这个仓库，并给予 Contents 读写、Pull requests 读写权限。若插件版本无法用 Fine-grained token，通过插件内置链接创建兼容 Token。

### 3. 设置文章和附件目录

在 Enveloppe 设置中使用下面这些值；不同版本的中文翻译可能略有差异，可按英文设置名查找。

| 区域 | 设置 | 值 |
| --- | --- | --- |
| Upload | Folder behavior | `Fixed folder` |
| Upload | Default/receipt folder | `content/posts` |
| Upload | Use frontmatter title | 关闭 |
| Upload | Auto clean | 开启 |
| Upload | Include attachments when cleaning | 开启 |
| Embeds | Send/transfer attachments | 开启 |
| Embeds | Use Obsidian attachment folder | 关闭 |
| Embeds | Default attachment folder | `static/attachments` |
| Embeds | Send embedded notes | 关闭 |
| Links | Convert internal links | 关闭，由本仓库脚本统一转换 |
| Plugin | Share key | `share` |

开启 Auto clean 后，取消分享或删除的文章会从 `content/posts` 移除；自动化只会关闭带有 Obsidian 标记的对应 Issue，不会动手工创建的普通 Issue。

### 4. 安装文章模板

把仓库中的 [`content/templates/博客文章模板.md`](content/templates/博客文章模板.md) 复制到你的私人 Vault 模板目录，然后在 **设置 → 核心插件 → 模板** 中指定该目录。

模板最重要的属性是：

```yaml
share: false
publish: false
blog_id: "{{date:YYYYMMDDHHmmss}}"
title: ""
tags:
  - Blog
```

`blog_id` 是文章与 Issue 的永久对应关系。发布后可以改文件名和标题，但不要修改 `blog_id`。`issue` 只用于绑定迁移前已存在的 Issue，新文章不用填写。

## 日常发布：三步

1. 在 Obsidian 用“博客文章模板”新建文章并正常写作。
2. 准备公开时，填写 `title`，把 `share` 和 `publish` 都改成 `true`。
3. 打开命令面板，运行 **Enveloppe: Upload single current active note**。

Enveloppe 会创建并自动合并一个 PR。合并后，GitHub 自动完成以下工作：检查文章和附件、创建或更新对应 Issue、重建 Gmeek、发布 Pages。可在仓库 **Actions → Publish Obsidian notes** 查看进度。

批量更新时可以运行 **Refresh published and upload new notes**；发布状态混乱时运行 **Refresh all published notes**。不要连续快速点击，等待上一轮完成再发下一轮，能减少分支冲突。

## 修改、下线和恢复

- 修改：在 Obsidian 编辑原文，再运行单篇上传命令。
- 改标题或文件名：可以，`blog_id` 不变即可继续更新同一个 Issue。
- 下线：把 `share` 和 `publish` 改为 `false`，然后运行 **Purge depublished and deleted files** 或批量刷新；对应 Issue 会被关闭，文章会从博客移除。
- 恢复：改回两个 `true` 并重新上传；原 Issue 会重新打开。
- 紧急发布：Obsidian 不在身边时，仍可直接在 GitHub 新建带 `Blog` 标签的 Issue。

> [!WARNING]
> 对于带 `obsidian-id` 隐藏标记的 Issue，Obsidian 是唯一正文来源。直接在 GitHub 修改它，下一次 Obsidian 同步会覆盖该修改。

## 支持的 Obsidian 写法

| Obsidian 内容 | 发布结果 |
| --- | --- |
| `[[另一篇文章]]` | 转为对应 GitHub Issue 链接 |
| `[[文章名\|显示文字]]` | 保留显示文字并转换链接 |
| `![[图片.png]]` | 上传到博客附件目录并转成公开图片 |
| `![[图片.png\|320]]` | 转成宽度为 320 的图片 |
| `==高亮==` | 转成 HTML 高亮 |
| `%% 私密注释 %%` | 发布时删除 |
| `> [!NOTE]` 等 Callout | 原样保留，按 Gmeek/GitHub 支持程度显示 |
| Mermaid、Dataview、Canvas | 不保证在 Gmeek 中正常显示，发布前预览 |

双链目标若尚未发布，会退化为普通文字，并在 Actions 中显示警告，避免把私人笔记路径暴露出去。附件找不到或存在同名歧义时，发布会直接停止，避免上线破图。

## 已迁移的文章

现有 Issue #1 和 #2 已分别绑定到 `content/posts/First page.md` 与 `content/posts/草台班子和SB.md`。第一次运行同步后会给它们加入隐藏标记，以后可以直接从 Obsidian 维护，不会重复创建文章。

## 本地检查（可选）

如果在电脑上克隆了本仓库，可以在仓库目录运行：

```bash
python3 scripts/sync_obsidian.py --check
python3 -m unittest discover -s tests -v
```

第一条只检查文章属性、双链和附件，不会连接或修改 GitHub。
