# 博客维护手册

这个博客现在有两个写作入口：

1. **推荐：Obsidian。** 私人 Vault 中写作，Enveloppe 只上传允许公开的笔记，自动同步到 Issue 并调用 Gmeek 发布。完整设置见 [OBSIDIAN.md](OBSIDIAN.md)。
2. **备用：GitHub Issues。** 不方便使用 Obsidian 时，仍可直接在 Issues 页面选择“发布一篇博客”。

## 从 Obsidian 发布

1. 用博客模板新建笔记并写作。
2. 发布前填写 `title`，把 `share`、`publish` 都设为 `true`。
3. 运行 **Enveloppe: Upload single current active note**。
4. 在 **Actions → Publish Obsidian notes** 查看进度。

修改时重新上传同一篇笔记；下线时把两个开关改回 `false`，再运行 Enveloppe 的清理命令。不要修改已经发布文章的 `blog_id`。

带有 `obsidian-id` 隐藏标记的 Issue 由 Obsidian 管理，直接编辑会在下次同步时被覆盖。手工创建且没有该标记的 Issue 不受影响。

## 直接用 Issue 发布

1. 打开仓库的 **Issues** 页面。
2. 点击 **New issue**，选择“发布一篇博客”。
3. Issue 标题会成为文章标题，正文使用 Markdown 编写。
4. 保留 `Blog` 标签并提交。
5. 打开 **Actions → Build and deploy blog** 查看进度。

手工 Issue 的修改、关闭和重新打开会自动触发博客更新。

## 改博客信息或外观

- 名称、简介、头像、分页数量：编辑 `config.json`。
- 字体、留白、列表和手机样式：编辑 `static/assets/blog.css`。
- 改完后打开 **Actions → Build and deploy blog → Run workflow**，手动全量生成一次。

`docs/`、`backup/`、`blogBase.json` 和根目录的 `README.md` 都是自动生成文件。不要直接编辑，否则下次构建会覆盖改动。

## 构建失败时

1. Obsidian 发布失败时，先打开 **Actions → Publish Obsidian notes**，找到红色失败步骤。错误会指出具体文章、附件或属性。
2. 如果是临时网络问题，点击 **Re-run all jobs**。
3. 如果提示附件找不到，确认附件已经被 Enveloppe 上传到 `static/attachments/`。
4. 如果提示 `blog_id`，确认它存在、格式正确且没有与其他文章重复。
5. 如果修改了 `config.json`，先确保 JSON 语法正确，然后手动运行 **Build and deploy blog**。
6. 如果手工 Issue 没出现，确认它仍处于 Open 状态，并且有至少一个标签。

## 低频维护

- 每周一凌晨会自动全量重建，用于同步评论数和修复偶发的漏更新。
- 每 3–6 个月检查一次 [Gmeek Releases](https://github.com/Meekdai/Gmeek/releases)。当前固定使用 `v2.22`，升级时只需修改 `config.json` 中的 `GMEEK_VERSION`，再手动运行一次工作流。
- Obsidian 文章以私人 Vault 为原稿，公开副本在 `content/posts/`，发布副本在 Issues，Gmeek 备份在 `backup/`。
- 每隔几个月检查一次 Enveloppe 更新；升级后先发一篇短测试文章，确认目录和附件设置没有变化。
