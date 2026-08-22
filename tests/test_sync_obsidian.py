import tempfile
import unittest
from pathlib import Path

from scripts.sync_obsidian import (
    Note,
    SyncError,
    load_notes,
    parse_frontmatter,
    render_markdown,
    sync_notes,
)


class FrontmatterTests(unittest.TestCase):
    def test_parses_supported_properties(self):
        metadata, body = parse_frontmatter(
            """---
share: true
publish: true
blog_id: post-123
title: "测试文章"
tags:
  - Blog
  - 阅读
issue: 12
---
正文
"""
        )
        self.assertTrue(metadata["share"])
        self.assertTrue(metadata["publish"])
        self.assertEqual(metadata["tags"], ["Blog", "阅读"])
        self.assertEqual(metadata["issue"], 12)
        self.assertEqual(body, "正文\n")

    def test_draft_is_skipped_and_duplicate_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            posts = root / "content/posts"
            posts.mkdir(parents=True)
            (posts / "draft.md").write_text("---\npublish: false\n---\n草稿", encoding="utf-8")
            (posts / "one.md").write_text(
                "---\nshare: true\npublish: true\nblog_id: same-id\n---\n一", encoding="utf-8"
            )
            (posts / "two.md").write_text(
                "---\nshare: true\npublish: true\nblog_id: same-id\n---\n二", encoding="utf-8"
            )
            with self.assertRaises(SyncError):
                load_notes(root)


class MarkdownTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "static/attachments").mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def note(self, name: str, body: str, issue: int) -> Note:
        return Note(
            path=self.root / f"content/posts/{name}.md",
            relative_path=f"content/posts/{name}.md",
            metadata={},
            body=body,
            blog_id=f"post-{issue}",
            title=name,
            tags=["Blog"],
            issue_number=issue,
            issue_url=f"https://github.com/example/blog/issues/{issue}",
        )

    def test_converts_wikilinks_comments_highlights_and_block_ids(self):
        target = self.note("目标", "内容", 2)
        source = self.note("来源", "%%私密注释%%\n[[目标|去看看]] ==重点== ^block", 1)
        rendered, warnings = render_markdown(source, [source, target], self.root)
        self.assertEqual(warnings, [])
        self.assertNotIn("私密注释", rendered)
        self.assertIn("[去看看](https://github.com/example/blog/issues/2)", rendered)
        self.assertIn("<mark>重点</mark>", rendered)
        self.assertNotIn("^block", rendered)

    def test_converts_image_embed_and_checks_file(self):
        image = self.root / "static/attachments/示例 图.png"
        image.write_bytes(b"image")
        source = self.note("来源", "![[示例 图.png|320]]", 1)
        rendered, _ = render_markdown(source, [source], self.root)
        self.assertIn("width=\"320\"", rendered)
        self.assertIn("%E7%A4%BA%E4%BE%8B%20%E5%9B%BE.png", rendered)

    def test_missing_attachment_fails(self):
        source = self.note("来源", "![[missing.png]]", 1)
        with self.assertRaises(SyncError):
            render_markdown(source, [source], self.root)


class FakeGitHubClient:
    repository = "example/blog"

    def __init__(self, issues):
        self.issues = issues
        self.labels = [{"name": "Blog"}]
        self.calls = []

    def paginated(self, path):
        return self.labels if path.startswith("/labels") else self.issues

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "POST" and path == "/labels":
            label = {"name": payload["name"]}
            self.labels.append(label)
            return label, {}
        if method == "POST" and path == "/issues":
            number = max([issue["number"] for issue in self.issues] + [0]) + 1
            issue = {
                "number": number,
                "html_url": f"https://github.com/example/blog/issues/{number}",
                "title": payload["title"],
                "body": payload["body"],
                "state": "open",
                "labels": [{"name": name} for name in payload["labels"]],
            }
            self.issues.append(issue)
            return issue, {}
        if method == "PATCH" and path.startswith("/issues/"):
            number = int(path.rsplit("/", 1)[1])
            issue = next(issue for issue in self.issues if issue["number"] == number)
            issue.update(payload)
            if "labels" in payload:
                issue["labels"] = [{"name": name} for name in payload["labels"]]
            return issue, {}
        raise AssertionError((method, path, payload))


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "content/posts").mkdir(parents=True)
        (self.root / "static/attachments").mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_adopts_existing_issue_without_creating_duplicate(self):
        path = self.root / "content/posts/现有文章.md"
        path.write_text(
            "---\nshare: true\npublish: true\nblog_id: existing-1\ntitle: 现有文章\nissue: 1\n---\n正文",
            encoding="utf-8",
        )
        notes, _ = load_notes(self.root)
        client = FakeGitHubClient(
            [
                {
                    "number": 1,
                    "html_url": "https://github.com/example/blog/issues/1",
                    "title": "现有文章",
                    "body": "旧正文",
                    "state": "open",
                    "labels": [{"name": "Blog"}],
                }
            ]
        )
        sync_notes(self.root, notes, client)
        self.assertFalse(any(method == "POST" and path == "/issues" for method, path, _ in client.calls))
        self.assertIn("<!-- obsidian-id: existing-1 -->", client.issues[0]["body"])

    def test_closes_only_missing_managed_issue(self):
        client = FakeGitHubClient(
            [
                {
                    "number": 8,
                    "html_url": "https://github.com/example/blog/issues/8",
                    "title": "手工文章",
                    "body": "没有标记",
                    "state": "open",
                    "labels": [{"name": "Blog"}],
                },
                {
                    "number": 9,
                    "html_url": "https://github.com/example/blog/issues/9",
                    "title": "已撤下文章",
                    "body": "正文\n<!-- obsidian-id: removed-9 -->",
                    "state": "open",
                    "labels": [{"name": "Blog"}],
                },
            ]
        )
        stats = sync_notes(self.root, [], client)
        self.assertEqual(stats["closed"], 1)
        self.assertEqual(client.issues[0]["state"], "open")
        self.assertEqual(client.issues[1]["state"], "closed")


if __name__ == "__main__":
    unittest.main()
