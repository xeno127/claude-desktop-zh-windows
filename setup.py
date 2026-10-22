import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import claude_zh as pack


PACKAGE_FAMILY = "AnthropicPBC.Claude_fnn82j28hfe8t"
PACKAGE_VERSION = "AnthropicPBC.Claude_3.1623.1.0_x64__fnn82j28hfe8t"


def local_path(relative):
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("未找到 LOCALAPPDATA；请在 Windows 当前用户会话中运行")
    return Path(local) / relative


def system_query(command):
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); " + command],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if result.returncode:
        raise RuntimeError("Windows 操作失败：" + result.stderr.strip())
    return result.stdout.strip()


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def get_package():
    output = system_query("@(Get-AppxPackage -Name AnthropicPBC.Claude | Select-Object PackageFullName,PackageFamilyName,InstallLocation) | ConvertTo-Json -Compress")
    packages = json.loads(output) if output else []
    if isinstance(packages, dict):
        packages = [packages]
    if len(packages) > 1:
        raise RuntimeError("检测到多个商店包，请先手动处理后再安装")
    if packages and packages[0]["PackageFullName"] != PACKAGE_VERSION:
        raise RuntimeError("商店版本不受支持；目前仅支持 3.1623.1.0 x64，未修改安装")
    return packages[0] if packages else None


def assert_regular(path):
    if path.is_symlink() or getattr(path.stat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise RuntimeError(f"发现重解析路径，停止以免备份不完整：{path}")


def inventories(root):
    assert_regular(root)
    files = []
    for directory, folders, names in os.walk(root, followlinks=False, onerror=raise_walk_error):
        for name in folders + names:
            path = Path(directory) / name
            assert_regular(path)
            if path.is_file():
                files.append(path)
    return files


def raise_walk_error(error):
    raise error


def data_roots(config):
    local = local_path("")
    roaming = Path(os.environ["APPDATA"])
    candidates = {
        "local-Claude-3p": local / "Claude-3p",
        "local-Claude-Data": local / "Claude-Data",
        "local-Claude": local / "Claude",
        "roaming-Claude": roaming / "Claude",
        "roaming-Claude-3p": roaming / "Claude-3p",
        "store-user-data": local / "Packages" / PACKAGE_FAMILY,
    }
    roots = {name: path for name, path in candidates.items() if path.is_dir()}
    if not any(config.is_relative_to(path.resolve()) for path in roots.values()):
        roots["custom-config"] = config.parent
    return roots


def backup_root(source, destination):
    files = inventories(source)
    records = {}
    destination.mkdir(parents=True, exist_ok=False)
    for path in files:
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        digest = pack.sha256(path)
        if pack.sha256(target) != digest:
            raise RuntimeError(f"备份校验失败：{relative}")
        records[str(relative)] = digest
    if set(files) != set(inventories(source)):
        raise RuntimeError("备份期间数据文件集合发生变化，请完全退出 Claude 后重试")
    return records


def verify_backups(backup, state):
    for name, entry in state["roots"].items():
        for relative, digest in entry["files"].items():
            if pack.sha256(backup / "data" / name / relative) != digest:
                raise RuntimeError(f"备份损坏，已停止：{name}/{relative}")


def verify_live_data(state):
    for entry in state["roots"].values():
        root = Path(entry["path"])
        current = {str(path.relative_to(root)): pack.sha256(path) for path in inventories(root)}
        if current != entry["files"]:
            raise RuntimeError("备份后数据发生变化，已停止，尚未卸载商店版。请完全退出相关程序再重试。")


def recover_missing_data(backup, state):
    verify_backups(backup, state)
    for name, entry in state["roots"].items():
        if name == "store-user-data":
            continue
        root = Path(entry["path"])
        for relative in entry["files"]:
            path = root / relative
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup / "data" / name / relative, path)


def write_locale(config, backup):
    data = pack.read_json(config)
    path = backup / "locale-backup.json"
    if not path.exists():
        pack.write_json(path, {"configPath": str(config), "hadLocale": "locale" in data, "locale": data.get("locale")})
    data["locale"] = "zh-CN"
    pack.write_json(config, data)


def shortcut_command(target, backup):
    return f"""
$programs = [Environment]::GetFolderPath('Programs')
$backup = {literal(backup / 'shortcuts')}
$executable = {literal(target / 'claude.exe')}
[void][IO.Directory]::CreateDirectory($programs)
[void][IO.Directory]::CreateDirectory($backup)
$shell = New-Object -ComObject WScript.Shell
$path = Join-Path $programs 'Claude.lnk'
$saved = Join-Path $backup 'Claude.lnk'
if ((Test-Path -LiteralPath $path) -and -not (Test-Path -LiteralPath $saved)) {{
    Copy-Item -LiteralPath $path -Destination $saved
}}
$shortcut = $shell.CreateShortcut($path)
$shortcut.TargetPath = $executable
$shortcut.Arguments = '--lang=zh-CN'
$shortcut.WorkingDirectory = Split-Path -LiteralPath $executable
$shortcut.IconLocation = $executable + ',0'
$shortcut.Description = 'Claude'
$shortcut.Save()
$verified = $shell.CreateShortcut($path)
if ($verified.TargetPath -ne $executable -or $verified.Arguments -ne '--lang=zh-CN') {{ throw '快捷方式校验失败' }}
$extra = Join-Path $programs 'Claude 中文版.lnk'
if (Test-Path -LiteralPath $extra) {{
    $item = $shell.CreateShortcut($extra)
    if ($item.TargetPath -eq $executable) {{
        $savedExtra = Join-Path $backup 'Claude 中文版.lnk'
        if (-not (Test-Path -LiteralPath $savedExtra)) {{ Copy-Item -LiteralPath $extra -Destination $savedExtra }}
        Remove-Item -LiteralPath $extra
    }}
}}
Write-Output $path
"""


def install_shortcut(target, backup):
    print(system_query(shortcut_command(target, backup)), flush=True)


def remove_package(package):
    system_query("Remove-AppxPackage -Package " + literal(package["PackageFullName"]) + " -ErrorAction Stop")
    if get_package() is not None:
        raise RuntimeError("商店包尚未移除；备份及中文程序已保留，请查看恢复说明")


def finish(backup, state, manifest):
    target = Path(state["target"])
    config = Path(state["config"])
    pack.verify(target, manifest)
    recover_missing_data(backup, state)
    write_locale(config, backup)
    install_shortcut(target, backup)
    state["phase"] = "complete"
    pack.write_json(backup / "migration.json", state)
    pack.write_json(local_path("ClaudeZhPatch/last-install.json"), {"backup": str(backup), "target": str(target)})
    print(f"安装完成。以后直接从开始菜单打开 Claude。\n程序：{target}\n数据备份：{backup}\n未自动启动程序。", flush=True)


def install(arguments):
    manifest = pack.check_pack()
    target = local_path("Programs/Claude").resolve()
    package = get_package()
    config = pack.config_path(arguments.config)
    if not arguments.config and config.parent.name != "Claude-3p":
        raise RuntimeError("默认安装只适配第三方网关模式；官方账号模式尚未验证。不会迁移这份配置。")
    if target.exists():
        pack.verify(target, manifest)
        app = None
    else:
        app = pack.find_app(arguments.app or (str(Path(package["InstallLocation"]) / "app") if package else None))
        pack.check_source(app, manifest)
    roots = data_roots(config)
    for root in roots.values():
        if local_path("ClaudeZhPatch").resolve().is_relative_to(root.resolve()) or target.is_relative_to(root.resolve()):
            raise RuntimeError("配置父目录覆盖了程序或备份目录。请将自定义配置放在独立目录，避免递归备份。")
    file_count = 0
    required_space = 1024 * 1024 * 1024
    for root in roots.values():
        files = inventories(root)
        file_count += len(files)
        required_space += sum(path.stat().st_size for path in files)
    if shutil.disk_usage(local_path("")).free < required_space:
        raise RuntimeError("系统盘可用空间不足：需要应用副本和完整数据备份的空间")
    print(f"安装目录：{target}\n配置：{config}\n将备份 {file_count} 个数据文件。", flush=True)
    if arguments.check:
        print("检查通过。未备份、卸载、改配置、写快捷方式或启动应用。", flush=True)
        return
    pack.check_no_processes()
    pending = local_path("ClaudeZhPatch/pending.json")
    if pending.exists():
        pending_state = pack.read_json(Path(pack.read_json(pending)["backup"]) / "migration.json")
        if pending_state["phase"] in {"prepared", "store-removed"} and package is None:
            raise RuntimeError("发现卸载后的未完成迁移，请先运行 setup.cmd resume，恢复缺失文件并完成设置")
    if package:
        print("将移除当前用户的商店版，取消商店自动更新，并移除该包的 Cowork 服务。\n官方账号模式、Cowork 和副本自动更新尚未验证。\n先备份并校验数据，再卸载；不会修改 WindowsApps 权限。", flush=True)
        if input("确认替换请输入 REPLACE（其他输入取消）：").strip() != "REPLACE":
            print("已取消，未修改安装。")
            return
    pack.check_no_processes()
    backup = local_path("ClaudeZhPatch/backups") / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, exist_ok=False)
    state = {"phase": "backing-up", "target": str(target), "config": str(config), "package": package, "roots": {}}
    pack.write_json(backup / "migration.json", state)
    for name, root in roots.items():
        state["roots"][name] = {"path": str(root), "files": backup_root(root, backup / "data" / name)}
        pack.write_json(backup / "migration.json", state)
        print(f"已备份并校验：{name}", flush=True)
    verify_backups(backup, state)
    if app is not None:
        pack.create_copy(app, target, manifest)
    pack.verify(target, manifest)
    pack.check_no_processes()
    if get_package() != package:
        raise RuntimeError("商店包状态发生变化，停止安装；备份及程序副本已保留")
    verify_live_data(state)
    state["phase"] = "prepared"
    pack.write_json(backup / "migration.json", state)
    pack.write_json(local_path("ClaudeZhPatch/pending.json"), {"backup": str(backup)})
    if package:
        remove_package(package)
    state["phase"] = "store-removed"
    pack.write_json(backup / "migration.json", state)
    finish(backup, state, manifest)


def resume():
    pending = local_path("ClaudeZhPatch/pending.json")
    if not pending.exists():
        raise RuntimeError("没有待继续的迁移记录")
    backup = Path(pack.read_json(pending)["backup"])
    state = pack.read_json(backup / "migration.json")
    if state["phase"] not in {"prepared", "store-removed"}:
        raise RuntimeError("记录已完成或尚未准备好；请按恢复说明处理")
    if Path(state["target"]).resolve() != local_path("Programs/Claude").resolve():
        raise RuntimeError("记录中的安装目录不匹配，已停止")
    pack.check_no_processes()
    if get_package() is not None:
        raise RuntimeError("商店版仍存在；请重新运行安装，由你确认后才会卸载")
    finish(backup, state, pack.check_pack())


def restore_language():
    pack.check_no_processes()
    info = pack.read_json(local_path("ClaudeZhPatch/last-install.json"))
    state = pack.read_json(Path(info["backup"]) / "locale-backup.json")
    config = Path(state["configPath"])
    data = pack.read_json(config)
    if state["hadLocale"]:
        data["locale"] = state["locale"]
    else:
        data.pop("locale", None)
    pack.write_json(config, data)
    print("原语言字段已恢复；密钥和其他新设置保持不变。恢复商店版请继续按 docs/恢复与卸载.md 操作。")


def main():
    if os.name != "nt" or sys.version_info < (3, 10):
        raise RuntimeError("需要 Windows 和 Python 3.10 或更高版本")
    parser = argparse.ArgumentParser(description="Claude 默认中文安装：先备份，再经确认替换商店包，保留一个 Claude 入口")
    parser.add_argument("action", nargs="?", choices=["install", "check", "resume", "restore-language"], default="install")
    parser.add_argument("--app", help="可选，原版 app 目录（仅支持当前语言包的版本）")
    parser.add_argument("--config", help="可选，已有 config.json 路径")
    arguments = parser.parse_args()
    arguments.check = arguments.action == "check"
    if arguments.action == "resume":
        resume()
    elif arguments.action == "restore-language":
        restore_language()
    else:
        install(arguments)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, EOFError, KeyboardInterrupt, subprocess.SubprocessError) as error:
        print("安装未完成：", error, file=sys.stderr)
        print("程序不会自动删除数据或重复卸载。请保留窗口，查看 docs/恢复与卸载.md。", file=sys.stderr)
        raise SystemExit(1)
