import hashlib
from pathlib import Path
import re
import zipfile

import claude_zh as pack


ROOT = Path(__file__).resolve().parent
FILES = [
    "setup.cmd", "setup.py", "claude_zh.py", "release.py",
    "README.md", "CONTRIBUTING.md", "NOTICE.md", "LICENSE", ".gitignore", ".gitattributes",
    "docs/安装与使用.md", "docs/恢复与卸载.md", "docs/GitHub发布指南.md",
    "tests/test_setup.py",
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
    exported = output / "github-source"
    if exported.exists():
        unexpected = {path.relative_to(exported).as_posix() for path in exported.rglob("*") if path.is_file()} - set(FILES)
        if unexpected:
            raise RuntimeError("纯源码导出目录包含清单外内容，停止以免混入私密数据或覆盖仓库")
    destination = output / "claude-desktop-zh-windows-3.1623.1.zip"
    contents = {}
    for relative in FILES:
        path = ROOT / relative
        if path.is_symlink():
            raise RuntimeError(f"发布文件不能是链接：{relative}")
        content = path.read_bytes()
        text = content.decode("utf-8-sig")
        if re.search(r"(?i)[a-z]:[\\/]+Users[\\/]+", text):
            raise RuntimeError(f"发现个人用户路径，不发布：{relative}")
        if relative.endswith(".cmd"):
            content = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
        contents[relative] = content
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, content in contents.items():
            archive.writestr("claude-desktop-zh-windows/" + relative, content)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None or len(archive.namelist()) != len(FILES):
            raise RuntimeError("发布 ZIP 完整性校验失败")
    for relative, content in contents.items():
        target = exported / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".zip.sha256").write_text(digest + "  " + destination.name + "\n", "utf-8")
    print(f"已打包 {len(FILES)} 个文件；不含应用、备份、配置或日志。\n{destination}\n纯源码：{exported}\nSHA256：{digest}")
    return destination


if __name__ == "__main__":
    release()
