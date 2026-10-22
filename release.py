import hashlib
from pathlib import Path
import re
import zipfile

import claude_zh as pack


ROOT = Path(__file__).resolve().parent
VERSION = "0.2.0"
FILES = [
    "setup.cmd", "setup.py", "claude_zh.py", "release.py",
    "README.md", "CONTRIBUTING.md", "NOTICE.md", "LICENSE", ".gitignore", ".gitattributes",
    "docs/安装与使用.md", "docs/恢复与卸载.md", "docs/GitHub发布指南.md", "docs/更新记录.md",
    "tests/test_setup.py", "tests/test_release.py",
    "language-pack/manifest.json", "language-pack/validation.json",
    "language-pack/ion-dist/i18n/zh-CN.json", "language-pack/zh-CN.json",
    "language-pack/ion-dist/i18n/dynamic/zh-CN.json",
]


def release(output=None):
    pack.check_pack()
    validation = pack.read_json(ROOT / "language-pack/validation.json")
    if any(entry["errors"] for entry in validation["catalogs"]):
        raise RuntimeError("语言结构校验报告有错误，停止发布")
    output = Path(output).resolve() if output else ROOT / "dist"
    pack.regular(output)
    exported = output / "github-source"
    pack.regular(exported)
    if exported.exists():
        unexpected = {path.relative_to(exported).as_posix() for path in exported.rglob("*") if path.is_file()} - set(FILES)
        if unexpected:
            raise RuntimeError("导出目录含白名单之外的文件，请使用空的 dist 目录")
    contents = {}
    for relative in FILES:
        path = pack.safe_target(ROOT, relative)
        content = path.read_bytes()
        text = content.decode("utf-8-sig")
        if re.search(r"(?i)[a-z]:[\\/]+Users[\\/]+", text):
            raise RuntimeError("发现个人用户路径，不发布：" + relative)
        if relative.endswith(".cmd"):
            content = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
        contents[relative] = content
    output.mkdir(parents=True, exist_ok=True)
    destination = output / ("claude-desktop-zh-windows-v" + VERSION + ".zip")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, content in contents.items():
            archive.writestr("claude-desktop-zh-windows/" + relative, content)
    with zipfile.ZipFile(destination) as archive:
        expected = {"claude-desktop-zh-windows/" + relative for relative in FILES}
        if archive.testzip() or set(archive.namelist()) != expected:
            raise RuntimeError("ZIP 完整性或文件清单验证失败")
        for relative, content in contents.items():
            if archive.read("claude-desktop-zh-windows/" + relative) != content:
                raise RuntimeError("ZIP 内容校验失败")
    for relative, content in contents.items():
        target = pack.safe_target(exported, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".zip.sha256").write_text(digest + "  " + destination.name + "\n", "utf-8")
    print("已导出 " + str(len(FILES)) + " 个白名单文件，无应用、用户配置、日志或备份。")
    print("源码目录：" + str(exported))
    print("发布附件：" + str(destination))
    return destination


if __name__ == "__main__":
    release()
