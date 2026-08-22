#!/usr/bin/env python3
"""Synchronize selected Obsidian Markdown notes to GitHub Issues.

The public repository receives only notes selected by the Enveloppe Obsidian
plugin. This script turns those notes into the Issues consumed by Gmeek while
keeping a stable relationship between a note and its Issue.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


CONTENT_DIR = PurePosixPath("content/posts")
ATTACHMENT_DIR = PurePosixPath("static/attachments")
BLOG_LABEL = "Blog"
ID_MARKER = re.compile(r"<!--\s*obsidian-id:\s*([^\r\n]+?)\s*-->")
SOURCE_MARKER = re.compile(r"<!--\s*obsidian-source:\s*([^\r\n]+?)\s*-->")
VALID_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,99}$")
IMAGE_EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}


class SyncError(RuntimeError):
    """A user-correctable validation or synchronization error."""


@dataclass
class Note:
    path: Path
    relative_path: str
    metadata: dict[str, Any]
    body: str
    blog_id: str
    title: str
    tags: list[str]
    issue_number: int | None
    issue_url: str | None = None


def _strip_inline_comment(value: str) -> str:
    quote_char: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote_char == '"':
            escaped = True
            continue
        if char in {"'", '"'}:
            if quote_char is None:
                quote_char = char
            elif quote_char == char:
                quote_char = None
            continue
        if char == "#" and quote_char is None and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.strip()


def _split_inline_list(value: str) -> list[str]:
    result: list[str] = []
    buffer: list[str] = []
    quote_char: str | None = None
    escaped = False
    for char in value:
        if escaped:
            buffer.append(char)
            escaped = False
        elif char == "\\" and quote_char == '"':
            buffer.append(char)
            escaped = True
        elif char in {"'", '"'}:
            buffer.append(char)
            if quote_char is None:
                quote_char = char
            elif quote_char == char:
                quote_char = None
        elif char == "," and quote_char is None:
            result.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(char)
    result.append("".join(buffer).strip())
    return [item for item in result if item]


def _parse_scalar(raw: str) -> Any:
    value = _strip_inline_comment(raw.strip())
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        return [_parse_scalar(item) for item in _split_inline_list(value[1:-1])]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        return value[1:-1].replace("''", "'")
    lowered = value.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"null", "none", "~"}:
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse the small, documented top-level YAML subset used by blog notes."""
    text = text.lstrip("\ufeff")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text

    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() in {"---", "..."}:
            end = index
            break
    if end is None:
        raise SyncError("frontmatter 缺少结束分隔符 ---")

    metadata: dict[str, Any] = {}
    yaml_lines = [line.rstrip("\r\n") for line in lines[1:end]]
    index = 0
    while index < len(yaml_lines):
        line = yaml_lines[index]
        index += 1
        if not line.strip() or line.lstrip().startswith("#") or line[:1].isspace():
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$", line)
        if not match:
            continue
        key, raw_value = match.group(1), match.group(2) or ""
        if raw_value:
            metadata[key] = _parse_scalar(raw_value)
            continue

        items: list[Any] = []
        cursor = index
        while cursor < len(yaml_lines):
            nested = yaml_lines[cursor]
            if nested and not nested[:1].isspace():
                break
            item = re.match(r"^\s*-\s+(.+?)\s*$", nested)
            if item:
                items.append(_parse_scalar(item.group(1)))
            cursor += 1
        metadata[key] = items if items else None
        index = cursor

    return metadata, "".join(lines[end + 1 :]).lstrip("\r\n")


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"true", "yes", "on", "1"}


def _normalise_tags(value: Any) -> list[str]:
    if value is None:
        tags: list[str] = []
    elif isinstance(value, list):
        tags = [str(item).strip().lstrip("#") for item in value]
    else:
        tags = [part.strip().lstrip("#") for part in str(value).split(",")]
    result: list[str] = []
    seen: set[str] = set()
    for tag in [BLOG_LABEL, *tags]:
        if not tag or tag.casefold() in seen:
            continue
        if len(tag) > 50:
            raise SyncError(f"标签过长（最多 50 个字符）：{tag}")
        seen.add(tag.casefold())
        result.append(tag)
    return result


def load_notes(root: Path) -> tuple[list[Note], list[str]]:
    content_root = root / CONTENT_DIR
    notes: list[Note] = []
    skipped: list[str] = []
    errors: list[str] = []
    ids: dict[str, str] = {}

    if not content_root.exists():
        raise SyncError(f"文章目录不存在：{CONTENT_DIR}")

    for path in sorted(content_root.rglob("*.md")):
        relative_path = path.relative_to(root).as_posix()
        try:
            metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            if not _as_bool(metadata.get("publish")):
                skipped.append(relative_path)
                continue
            if not _as_bool(metadata.get("share")):
                raise SyncError("publish: true 时也必须设置 share: true")

            blog_id = str(metadata.get("blog_id") or "").strip()
            if not VALID_ID.fullmatch(blog_id):
                raise SyncError("blog_id 必须是 3–100 位，只能使用英文、数字、点、下划线或连字符")
            if blog_id in ids:
                raise SyncError(f"blog_id 与 {ids[blog_id]} 重复：{blog_id}")
            ids[blog_id] = relative_path

            title = str(metadata.get("title") or path.stem).strip()
            if not title:
                raise SyncError("title 不能为空")
            if len(title) > 256:
                raise SyncError("title 不能超过 256 个字符")
            if not body.strip():
                raise SyncError("正文不能为空")

            issue_number: int | None = None
            raw_issue = metadata.get("issue")
            if raw_issue not in {None, ""}:
                try:
                    issue_number = int(raw_issue)
                except (TypeError, ValueError) as error:
                    raise SyncError("issue 必须是正整数") from error
                if issue_number < 1:
                    raise SyncError("issue 必须是正整数")

            notes.append(
                Note(
                    path=path,
                    relative_path=relative_path,
                    metadata=metadata,
                    body=body,
                    blog_id=blog_id,
                    title=title,
                    tags=_normalise_tags(metadata.get("tags")),
                    issue_number=issue_number,
                )
            )
        except (OSError, UnicodeError, SyncError) as error:
            errors.append(f"{relative_path}: {error}")

    if errors:
        raise SyncError("文章检查失败：\n- " + "\n- ".join(errors))
    return notes, skipped


def _note_lookup(notes: Iterable[Note]) -> dict[str, Note | None]:
    lookup: dict[str, Note | None] = {}
    for note in notes:
        path = PurePosixPath(note.relative_path)
        keys = {
            path.stem,
            str(path.with_suffix("")),
            str(PurePosixPath(*path.parts[2:]).with_suffix("")),
            note.title,
        }
        for key in keys:
            normalised = key.strip().replace("\\", "/").casefold()
            if not normalised:
                continue
            if normalised in lookup and lookup[normalised] is not note:
                lookup[normalised] = None
            else:
                lookup[normalised] = note
    return lookup


def _github_anchor(value: str) -> str:
    value = value.strip().casefold().replace(" ", "-")
    value = re.sub(r"[^\w\-\u4e00-\u9fff]", "", value)
    return quote(value, safe="-_%")


def _resolve_note_link(target: str, lookup: dict[str, Note | None]) -> tuple[str, str] | None:
    target_path, separator, anchor = target.partition("#")
    target_path = re.sub(r"\.md$", "", target_path.strip(), flags=re.IGNORECASE)
    candidates = [target_path, PurePosixPath(target_path).name]
    note: Note | None = None
    for candidate in candidates:
        found = lookup.get(candidate.replace("\\", "/").casefold())
        if found:
            note = found
            break
    if not note or not note.issue_url:
        return None
    url = note.issue_url
    if separator and anchor:
        url += "#" + _github_anchor(anchor)
    return url, note.title


def _attachment_url(root: Path, target: str) -> tuple[str, Path]:
    clean_target = target.split("#", 1)[0].split("?", 1)[0].strip()
    clean_target = clean_target.replace("\\", "/").lstrip("/")
    for prefix in ("../", "./"):
        while clean_target.startswith(prefix):
            clean_target = clean_target[len(prefix) :]
    if clean_target.startswith(f"{ATTACHMENT_DIR}/"):
        clean_target = clean_target[len(f"{ATTACHMENT_DIR}/") :]

    attachment_root = root / ATTACHMENT_DIR
    direct = attachment_root / clean_target
    candidates = [direct] if direct.is_file() else list(attachment_root.rglob(PurePosixPath(clean_target).name))
    candidates = [candidate for candidate in candidates if candidate.is_file()]
    if not candidates:
        raise SyncError(f"找不到附件：{target}")
    if len(candidates) > 1:
        paths = ", ".join(candidate.relative_to(root).as_posix() for candidate in candidates)
        raise SyncError(f"附件同名，无法判断要使用哪一个：{target}（{paths}）")

    relative = candidates[0].relative_to(root / "static").as_posix()
    encoded = "/".join(quote(part, safe="") for part in PurePosixPath(relative).parts)
    return f"https://zhjhaibin.github.io/zhjhaibin/{encoded}", candidates[0]


def render_markdown(note: Note, notes: list[Note], root: Path) -> tuple[str, list[str]]:
    """Convert Obsidian-only syntax to Markdown that works in Issues/Gmeek."""
    text = note.body
    warnings: list[str] = []
    lookup = _note_lookup(notes)

    text = re.sub(r"%%.*?%%", "", text, flags=re.DOTALL)
    text = ID_MARKER.sub("", text)
    text = SOURCE_MARKER.sub("", text)
    text = re.sub(r"(?<!\w)==(.+?)==", r"<mark>\1</mark>", text)
    text = re.sub(r"[ \t]+\^[A-Za-z0-9-]+[ \t]*$", "", text, flags=re.MULTILINE)

    def replace_embed(match: re.Match[str]) -> str:
        value = match.group(1).strip()
        target, separator, option = value.partition("|")
        suffix = Path(target.split("#", 1)[0]).suffix.lower()
        if suffix in IMAGE_EXTENSIONS or suffix:
            url, attachment = _attachment_url(root, target)
            label = attachment.stem
            width = option.strip().split("x", 1)[0] if separator else ""
            if width.isdigit():
                return f'<img src="{html.escape(url, quote=True)}" alt="{html.escape(label, quote=True)}" width="{width}">'
            if suffix in IMAGE_EXTENSIONS:
                return f"![{label}]({url})"
            return f"[{attachment.name}]({url})"

        resolved = _resolve_note_link(target, lookup)
        label = option.strip() if separator and option.strip() else target.split("#", 1)[0]
        if resolved:
            return f"[{label}]({resolved[0]})"
        warnings.append(f"未解析的笔记嵌入：![[{value}]]")
        return label

    text = re.sub(r"!\[\[([^\]]+)\]\]", replace_embed, text)

    def replace_wikilink(match: re.Match[str]) -> str:
        value = match.group(1).strip()
        target, separator, alias = value.partition("|")
        label = alias.strip() if separator and alias.strip() else target.split("#", 1)[0]
        resolved = _resolve_note_link(target, lookup)
        if resolved:
            return f"[{label}]({resolved[0]})"
        warnings.append(f"未解析的双链：[[{value}]]")
        return label

    text = re.sub(r"(?<!!)\[\[([^\]]+)\]\]", replace_wikilink, text)

    def replace_markdown_image(match: re.Match[str]) -> str:
        alt, target = match.group(1), match.group(2)
        if re.match(r"^(?:https?:|data:|#)", target, flags=re.IGNORECASE):
            return match.group(0)
        try:
            url, _ = _attachment_url(root, target)
        except SyncError:
            return match.group(0)
        return f"![{alt}]({url})"

    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)", replace_markdown_image, text)

    def replace_markdown_note_link(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        if not re.search(r"\.md(?:#.*)?$", target, flags=re.IGNORECASE):
            return match.group(0)
        resolved = _resolve_note_link(target, lookup)
        if resolved:
            return f"[{label}]({resolved[0]})"
        return match.group(0)

    text = re.sub(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)", replace_markdown_note_link, text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, warnings


def issue_body(note: Note, rendered: str) -> str:
    return (
        rendered.rstrip()
        + "\n\n"
        + f"<!-- obsidian-id: {note.blog_id} -->\n"
        + f"<!-- obsidian-source: {note.relative_path} -->\n"
    )


class GitHubClient:
    def __init__(self, token: str, repository: str) -> None:
        self.token = token
        self.repository = repository
        self.base_url = f"https://api.github.com/repos/{repository}"

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[Any, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "zhjhaibin-obsidian-publisher",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read()
                return (json.loads(body) if body else None), response.headers
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise SyncError(f"GitHub API {method} {path} 失败（{error.code}）：{detail}") from error

    def paginated(self, path: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        page = 1
        separator = "&" if "?" in path else "?"
        while True:
            items, _ = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            if not isinstance(items, list):
                raise SyncError(f"GitHub API 返回了意外的数据：{path}")
            result.extend(items)
            if len(items) < 100:
                break
            page += 1
        return result


def _marker_id(issue: dict[str, Any]) -> str | None:
    match = ID_MARKER.search(issue.get("body") or "")
    return match.group(1).strip() if match else None


def _label_color(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:6]


def _ensure_labels(client: GitHubClient, notes: list[Note], dry_run: bool) -> None:
    existing = {label["name"].casefold() for label in client.paginated("/labels")}
    wanted = {tag for note in notes for tag in note.tags}
    for name in sorted(wanted, key=str.casefold):
        if name.casefold() in existing:
            continue
        if dry_run:
            print(f"[dry-run] 创建标签：{name}")
        else:
            client.request("POST", "/labels", {"name": name, "color": _label_color(name)})
        existing.add(name.casefold())


def sync_notes(root: Path, notes: list[Note], client: GitHubClient, dry_run: bool = False) -> dict[str, int]:
    issues = [item for item in client.paginated("/issues?state=all") if "pull_request" not in item]
    by_number = {int(issue["number"]): issue for issue in issues}
    managed: dict[str, dict[str, Any]] = {}
    for issue in issues:
        marker = _marker_id(issue)
        if marker:
            if marker in managed:
                raise SyncError(f"多个 Issue 使用了同一个 obsidian-id：{marker}")
            managed[marker] = issue

    _ensure_labels(client, notes, dry_run)
    stats = {"created": 0, "updated": 0, "reopened": 0, "closed": 0, "unchanged": 0}
    claimed: set[int] = set()

    # First establish every Issue number so wikilinks can be rendered in one pass.
    for note in notes:
        issue = by_number.get(note.issue_number) if note.issue_number else managed.get(note.blog_id)
        if note.issue_number and issue is None:
            raise SyncError(f"{note.relative_path}: 找不到指定的 Issue #{note.issue_number}")
        if issue and _marker_id(issue) not in {None, note.blog_id}:
            raise SyncError(f"{note.relative_path}: Issue #{issue['number']} 已属于另一篇 Obsidian 文章")
        if issue and int(issue["number"]) in claimed:
            raise SyncError(f"Issue #{issue['number']} 被多篇文章重复绑定")

        if issue is None:
            payload = {"title": note.title, "body": issue_body(note, note.body.strip()), "labels": note.tags}
            if dry_run:
                fake_number = max([*by_number, 0]) + 1
                issue = {
                    "number": fake_number,
                    "html_url": f"https://github.com/{client.repository}/issues/{fake_number}",
                    "title": note.title,
                    "body": payload["body"],
                    "state": "open",
                    "labels": [{"name": tag} for tag in note.tags],
                }
                print(f"[dry-run] 新建 Issue：{note.title}")
            else:
                issue, _ = client.request("POST", "/issues", payload)
            stats["created"] += 1
            by_number[int(issue["number"])] = issue
            managed[note.blog_id] = issue

        note.issue_number = int(issue["number"])
        note.issue_url = issue["html_url"]
        claimed.add(note.issue_number)

    for note in notes:
        issue = by_number[note.issue_number or 0]
        rendered, warnings = render_markdown(note, notes, root)
        for warning in warnings:
            print(f"::warning file={note.relative_path}::{warning}")
        desired_body = issue_body(note, rendered)
        current_labels = [label["name"] for label in issue.get("labels", [])]
        payload: dict[str, Any] = {}
        if issue.get("title") != note.title:
            payload["title"] = note.title
        if (issue.get("body") or "").rstrip() != desired_body.rstrip():
            payload["body"] = desired_body
        if {label.casefold() for label in current_labels} != {label.casefold() for label in note.tags}:
            payload["labels"] = note.tags
        if issue.get("state") != "open":
            payload["state"] = "open"
            stats["reopened"] += 1

        if payload:
            if dry_run:
                print(f"[dry-run] 更新 Issue #{note.issue_number}：{note.title}")
            else:
                client.request("PATCH", f"/issues/{note.issue_number}", payload)
            stats["updated"] += 1
        else:
            stats["unchanged"] += 1

    active_ids = {note.blog_id for note in notes}
    for marker, issue in managed.items():
        if marker in active_ids or issue.get("state") == "closed":
            continue
        if dry_run:
            print(f"[dry-run] 关闭已撤下文章 Issue #{issue['number']}：{issue['title']}")
        else:
            client.request("PATCH", f"/issues/{issue['number']}", {"state": "closed"})
        stats["closed"] += 1

    return stats


def check_rendering(root: Path, notes: list[Note]) -> list[str]:
    warnings: list[str] = []
    for index, note in enumerate(notes, start=1):
        note.issue_url = f"https://github.com/zhjhaibin/zhjhaibin/issues/{note.issue_number or index}"
    for note in notes:
        try:
            _, note_warnings = render_markdown(note, notes, root)
            warnings.extend(f"{note.relative_path}: {warning}" for warning in note_warnings)
        except SyncError as error:
            raise SyncError(f"{note.relative_path}: {error}") from error
    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="将 Obsidian 文章同步为 Gmeek GitHub Issues")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true", help="只做本地格式和附件检查")
    parser.add_argument("--dry-run", action="store_true", help="读取 GitHub，但不修改 Issue")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        notes, skipped = load_notes(root)
        warnings = check_rendering(root, notes)
        print(f"检查完成：{len(notes)} 篇待发布，{len(skipped)} 篇未发布。")
        for warning in warnings:
            print(f"警告：{warning}")
        if args.check:
            return 0

        token = os.environ.get("GITHUB_TOKEN", "").strip()
        repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
        if not token or not repository:
            raise SyncError("同步需要 GITHUB_TOKEN 和 GITHUB_REPOSITORY 环境变量")
        client = GitHubClient(token, repository)
        stats = sync_notes(root, notes, client, dry_run=args.dry_run)
        print("同步完成：" + "，".join(f"{key}={value}" for key, value in stats.items()))
        return 0
    except SyncError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
