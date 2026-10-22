import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parent
PACK = ROOT / "language-pack"
DEFAULT_TARGET = ROOT / "runtime" / "Claude-3.1623.1"
LANGUAGES = '["en-US","de-DE","fr-FR","ko-KR","ja-JP","es-419","es-ES","it-IT","hi-IN","pt-BR","id-ID"]'
LABEL = ';(()=>{const proto=Intl.DisplayNames?.prototype;if(!proto||proto.__claudeZhLabelPatch)return;const original=proto.of;proto.of=function(locale){return String(locale)==="zh-CN"?"简体中文":original.call(this,locale)};Object.defineProperty(proto,"__claudeZhLabelPatch",{value:true})})();\n'


def read_json(path):
    return json.loads(path.read_text("utf-8-sig"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    temporary.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_pack():
    manifest = read_json(PACK / "manifest.json")
    for entry in manifest["catalogs"].values():
        path = PACK / entry["path"]
        if sha256(path) != entry["sha256"]:
            raise RuntimeError(f"语言文件校验失败: {entry['path']}")
        if len(read_json(path)) != entry["entries"]:
            raise RuntimeError(f"语言文件条目数量不符: {entry['path']}")
    return manifest


def powershell(command):
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
    if result.returncode:
        raise RuntimeError("系统查询失败，请使用 --app 显式指定安装位置")
    return result.stdout.strip()


def find_app(supplied):
    if supplied:
        candidate = Path(supplied).expanduser().resolve()
    else:
        output = powershell("[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); @(Get-AppxPackage -Name AnthropicPBC.Claude | Select-Object -ExpandProperty InstallLocation) | ConvertTo-Json -Compress; exit 0")
        locations = json.loads(output) if output else []
        if isinstance(locations, str):
            locations = [locations]
        if len(locations) != 1:
            raise RuntimeError("无法唯一定位商店版 Claude，请使用 --app 指定含 claude.exe 的目录")
        candidate = Path(locations[0]).resolve()
    if not (candidate / "claude.exe").is_file() and (candidate / "app/claude.exe").is_file():
        candidate /= "app"
    if not (candidate / "claude.exe").is_file() or not (candidate / "resources/app.asar").is_file():
        raise RuntimeError(f"不是完整的 Claude 安装目录: {candidate}")
    return candidate


def check_source(app, manifest):
    for relative, expected in manifest["sourceFiles"].items():
        path = app / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"源文件不符合受支持的 3.1623.1.0 版本: {relative}。不要覆盖其他版本。")
    for entry in manifest["catalogs"].values():
        english = read_json(app / "resources" / entry["sourcePath"])
        chinese = read_json(PACK / entry["path"])
        if english.keys() != chinese.keys():
            raise RuntimeError(f"当前英文键集合与语言包不符: {entry['sourcePath']}")


def patched_bundle(source):
    if source.count(LANGUAGES) != 2:
        raise RuntimeError("语言白名单结构变化，停止安装")
    return source.replace(LANGUAGES, LANGUAGES[:-1] + ',"zh-CN"]') + "\n" + LABEL


def verify(target, manifest):
    for relative, expected in manifest["installedFiles"].items():
        path = target / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"副本文件校验失败: {relative}")
    print("验证通过：5 个补丁文件正确，claude.exe 和 app.asar 与原版一致。", flush=True)


def install(arguments):
    check_no_processes()
    config = config_path(arguments.config)
    manifest = check_pack()
    app = find_app(arguments.app)
    check_source(app, manifest)
    target = arguments.target.resolve()
    create_copy(app, target, manifest)
    configure_start_menu(target, config, manifest)
    print("安装完成。以后从开始菜单或 Windows 搜索打开 Claude 中文版，无需 CMD。", flush=True)


def create_copy(app, target, manifest):
    if target.exists():
        raise RuntimeError(f"目标已存在，未覆盖任何文件: {target}")
    if target.is_relative_to(app) or app.is_relative_to(target):
        raise RuntimeError("副本目录不能与原安装目录重叠")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / (".claude-zh-installing-" + uuid.uuid4().hex)
    print(f"从本机复制 Claude 到: {target}\n原安装目录保持不变。", flush=True)
    try:
        shutil.copytree(app, staging, copy_function=shutil.copyfile)
        for entry in manifest["catalogs"].values():
            destination = staging / "resources" / entry["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PACK / entry["path"], destination)
        shutil.copyfile(staging / "resources/zh-CN.json", staging / "resources/zh-Hans.json")
        bundle = staging / manifest["bundlePath"]
        bundle.write_text(patched_bundle(bundle.read_text("utf-8")), "utf-8")
        verify(staging, manifest)
        staging.rename(target)
    except Exception:
        print(f"安装未完成。原版未修改；如存在中间副本，可检查后删除: {staging}", file=sys.stderr)
        raise


def config_path(supplied):
    if supplied:
        return Path(supplied).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    roaming = os.environ.get("APPDATA")
    candidates = []
    if local:
        candidates.append(Path(local) / "Claude-3p/config.json")
    if roaming:
        candidates.extend([Path(roaming) / "Claude/config.json", Path(roaming) / "Claude-3p/config.json"])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("未找到用户语言配置。请先启动原版一次，或用 --config 指定 config.json。")


def restore_locale(arguments):
    check_no_processes()
    path = config_path(arguments.config)
    state_path = ROOT / "runtime/locale-backup.json"
    if not state_path.exists():
        raise RuntimeError("没有由本启动器生成的语言设置备份")
    state = read_json(state_path)
    if str(path.resolve()).casefold() != state["configPath"].casefold():
        raise RuntimeError("当前配置与备份中的路径不一致")
    config = read_json(path)
    if state["hadLocale"]:
        config["locale"] = state["locale"]
    else:
        config.pop("locale", None)
    write_json(path, config)
    print("已恢复原语言设置，其他设置保持不变。")


def check_no_processes():
    count = powershell("$processes=@(Get-Process -Name claude -ErrorAction SilentlyContinue); Write-Output $processes.Count; exit 0")
    if not count.isdigit():
        raise RuntimeError("无法确认 Claude 是否已退出")
    if int(count):
        raise RuntimeError("请先从托盘完全退出所有 Claude，再运行启动器。")


def save_chinese_locale(config):
    data = read_json(config)
    state_path = ROOT / "runtime/locale-backup.json"
    if not state_path.exists():
        write_json(state_path, {"configPath": str(config.resolve()), "hadLocale": "locale" in data, "locale": data.get("locale")})
    elif read_json(state_path)["configPath"].casefold() != str(config.resolve()).casefold():
        raise RuntimeError("语言备份对应另一份配置，请先还原设置，避免覆盖备份")
    if data.get("locale") != "zh-CN":
        data["locale"] = "zh-CN"
        write_json(config, data)


def configure_start_menu(target, config, manifest):
    verify(target, manifest)
    check_no_processes()
    save_chinese_locale(config)
    executable_literal = "'" + str(target / "claude.exe").replace("'", "''") + "'"
    backup_literal = "'" + str(ROOT / "runtime/start-menu-backup").replace("'", "''") + "'"
    command = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$executable = {executable_literal}
$backup = {backup_literal}
$programs = [Environment]::GetFolderPath('Programs')
[void][IO.Directory]::CreateDirectory($programs)
[void][IO.Directory]::CreateDirectory($backup)
$shortcutShell = New-Object -ComObject WScript.Shell
foreach ($name in @('Claude', 'Claude 中文版')) {{
    $path = Join-Path $programs ($name + '.lnk')
    $original = Join-Path $backup ($name + '.lnk')
    if ((Test-Path -LiteralPath $path) -and -not (Test-Path -LiteralPath $original)) {{
        Copy-Item -LiteralPath $path -Destination $original
    }}
    $shortcut = $shortcutShell.CreateShortcut($path)
    $shortcut.TargetPath = $executable
    $shortcut.Arguments = '--lang=zh-CN'
    $shortcut.WorkingDirectory = Split-Path -LiteralPath $executable
    $shortcut.IconLocation = $executable + ',0'
    $shortcut.Description = 'Claude 简体中文'
    $shortcut.Save()
    $verified = $shortcutShell.CreateShortcut($path)
    if ($verified.TargetPath -ne $executable -or $verified.Arguments -ne '--lang=zh-CN') {{
        throw '开始菜单快捷方式校验失败'
    }}
    Write-Output $path
}}
"""
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
    if result.returncode:
        raise RuntimeError("开始菜单设置失败：" + result.stderr.strip())
    print("已保存默认中文，并设置直接启动程序的开始菜单入口：\n" + result.stdout.strip(), flush=True)


def launch(arguments):
    manifest = check_pack()
    target = arguments.target.resolve()
    verify(target, manifest)
    config = config_path(arguments.config)
    print(f"副本路径: {target}\n语言配置: {config}", flush=True)
    if arguments.check:
        print("只读检查完成；未启动 Claude，未修改配置。")
        return
    check_no_processes()
    save_chinese_locale(config)
    log_path = ROOT / "runtime" / ("launch-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(target / "claude.exe"), "--lang=zh-CN"], cwd=target, stdout=log, stderr=log)
        print(f"已启动副本，进程 ID: {process.pid}\n本机日志: {log_path}", flush=True)
        try:
            code = process.wait(timeout=6)
            print(f"启动进程已结束，退出码: {code}。如未出现窗口，请检查日志。")
        except subprocess.TimeoutExpired:
            print("Claude 正在运行。首次启动请确认设置中的语言为简体中文。")


def main():
    parser = argparse.ArgumentParser(description="Claude Desktop 3.1623.1.0 简体中文补丁；仅在副本中安装")
    commands = parser.add_subparsers(dest="action", required=True)
    installer = commands.add_parser("install", help="只读复制本机应用并安装语言包，无需管理员")
    installer.add_argument("--app", help="原安装位置，可为商店包目录或含 claude.exe 的 app 目录")
    installer.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    installer.add_argument("--config", help="可选，指定已有用户 config.json")
    start_menu = commands.add_parser("start-menu", help="设为默认中文，并创建直接启动程序的开始菜单入口")
    start_menu.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    start_menu.add_argument("--config", help="可选，指定已有用户 config.json")
    launcher = commands.add_parser("launch", help="备份语言设置后启动中文副本")
    launcher.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    launcher.add_argument("--config", help="可选，指定已有用户 config.json")
    launcher.add_argument("--check", action="store_true", help="只读检查，不启动应用或修改设置")
    verifier = commands.add_parser("verify", help="只读检查已生成副本")
    verifier.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    restorer = commands.add_parser("restore-locale", help="恢复启动前的语言字段，保留其他配置")
    restorer.add_argument("--config")
    arguments = parser.parse_args()
    if arguments.action == "install":
        install(arguments)
    elif arguments.action == "launch":
        launch(arguments)
    elif arguments.action == "verify":
        verify(arguments.target.resolve(), check_pack())
    elif arguments.action == "start-menu":
        configure_start_menu(arguments.target.resolve(), config_path(arguments.config), check_pack())
    else:
        restore_locale(arguments)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print("错误:", error, file=sys.stderr)
        raise SystemExit(1)
