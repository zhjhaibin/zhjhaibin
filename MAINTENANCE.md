# 博客维护手册

这个博客由 Gmeek 生成。文章写在 GitHub Issues 里，GitHub Actions 会自动生成页面并发布到 GitHub Pages。平时不需要在本地安装任何东西。

## 发布新文章

1. 打开仓库的 **Issues** 页面。
2. 点击 **New issue**，选择“发布一篇博客”。
3. Issue 标题会成为文章标题，正文使用 Markdown 编写。
4. 保留 `Blog` 标签并提交。
5. 打开 **Actions → Build and deploy blog** 查看进度。通常几分钟后即可在博客首页看到。

## 修改或下线文章

- 修改：直接编辑对应 Issue 的标题或正文，保存后会自动重新发布。
- 下线：关闭对应 Issue，构建结束后文章会从博客中移除。
- 恢复：重新打开 Issue 并确保它有至少一个标签。

## 改博客信息或外观

- 名称、简介、头像、分页数量：编辑 `config.json`。
- 字体、留白、列表和手机样式：编辑 `static/assets/blog.css`。
- 改完后打开 **Actions → Build and deploy blog → Run workflow**，手动全量生成一次。

`docs/`、`backup/`、`blogBase.json` 和根目录的 `README.md` 都是自动生成文件。不要直接编辑，否则下次构建会覆盖改动。

## 构建失败时

1. 在 **Actions** 页面打开最近一次运行，找到红色失败步骤。
2. 如果是临时网络问题，点击 **Re-run all jobs**。
3. 如果修改了 `config.json`，先确保 JSON 语法正确，然后手动运行工作流。
4. 如果新文章没出现，确认 Issue 仍处于 Open 状态，并且有至少一个标签。

## 低频维护

- 每周一凌晨会自动全量重建，用于同步评论数和修复偶发的漏更新。
- 每 3–6 个月检查一次 [Gmeek Releases](https://github.com/Meekdai/Gmeek/releases)。当前固定使用 `v2.22`，升级时只需修改 `config.json` 中的 `GMEEK_VERSION`，再手动运行一次工作流。
- 博客内容同时保存在 Issues 和 `backup/` 中，构建后会自动更新备份。
