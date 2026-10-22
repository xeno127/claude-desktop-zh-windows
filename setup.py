import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import base64

import claude_zh as pack


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def system_query(command):
    code = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); " + command
    encoded = base64.b64encode(code.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
    )
    if result.returncode:
        raise RuntimeError("Windows 查询失败：" + result.stderr.strip())
    return result.stdout.strip()


def current_sid():
    return system_query("[Security.Principal.WindowsIdentity]::GetCurrent().User.Value")


def ensure_idle():
    count = system_query("@(Get-Process -Name claude -ErrorAction SilentlyContinue).Count")
    if count != "0":
        raise RuntimeError("请先从托盘完全退出 Claude，再运行 install 或 restore；不会强制结束任务")


def get_packages():
    output = system_query(
        "@(Get-AppxPackage | Where-Object {$_.Name -in @('Claude','AnthropicPBC.Claude')} | "
        "Select-Object Name,PackageFamilyName,InstallLocation,@{Name='Version';Expression={$_.Version.ToString()}}) | ConvertTo-Json -Compress"
    )
    values = json.loads(output) if output else []
    return [values] if isinstance(values, dict) else values


def resolve_app(packages, manifest, supplied=None):
    matches = [
        package for package in packages
        if package["Version"] == manifest["version"]
        and package["PackageFamilyName"] == manifest["packageFamily"]
    ]
    if supplied:
        candidate = Path(supplied).resolve()
        matches = [package for package in matches if candidate in {
            Path(package["InstallLocation"]).resolve(), (Path(package["InstallLocation"]) / "app").resolve()
        }]
    if len(matches) != 1:
        raise RuntimeError("无法唯一定位受支持的官方包：需要 Claude " + manifest["version"] +
                           " x64（" + manifest["packageFamily"] + "）。未知版本不会覆盖")
    return (Path(matches[0]["InstallLocation"]) / "app").resolve()


def config_path(supplied):
    if supplied:
        path = Path(supplied).expanduser().resolve()
    else:
        path = Path(os.environ["LOCALAPPDATA"]) / "Claude-3p/config.json"
    if not path.is_file() or path.suffix.lower() != ".json":
        raise RuntimeError("未找到第三方模式 config.json；请先启动原版完成配置。官方账号请先用自带语言设置")
    if not path.is_relative_to(Path(os.environ["USERPROFILE"]).resolve()):
        raise RuntimeError("配置必须位于当前 Windows 用户目录内，拒绝修改系统或其他用户的配置")
    pack.config_data(path)
    return path


def storage_path():
    return Path(os.environ["LOCALAPPDATA"]) / "ClaudeZhPatch"


def elevate():
    arguments = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), *sys.argv[1:],
                 "--elevated", "--expected-sid", current_sid()]
    launch_arguments = subprocess.list2cmdline(arguments[1:])
    command = (
        "$process=Start-Process -FilePath " + literal(arguments[0]) +
        " -ArgumentList " + literal(launch_arguments) +
        " -Verb RunAs -WindowStyle Normal -Wait -PassThru -ErrorAction Stop; exit $process.ExitCode"
    )
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    print("需要 UAC 管理员授权以写入官方资源；请使用当前账户，完成后关闭安装结果窗口。", flush=True)
    return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]).returncode


def execute(arguments):
    if os.name != "nt" or sys.version_info < (3, 10):
        raise RuntimeError("需要 Windows 和 Python 3.10 或更新版本")
    if arguments.expected_sid and current_sid() != arguments.expected_sid:
        raise RuntimeError("管理员账户与原用户不同，停止以免写入另一份配置；请使用同一用户的 UAC 授权")
    manifest = pack.check_pack()
    app = resolve_app(get_packages(), manifest, arguments.app)
    storage = storage_path()
    if arguments.action == "restore":
        if arguments.config:
            raise RuntimeError("restore 使用备份记录中的配置路径，不接受 --config")
        backup = Path(arguments.backup) if arguments.backup else Path(pack.read_json(storage / "last-install.json")["backup"])
        payloads = pack.restoration_payloads(app, storage, backup, manifest)
        _, state = pack.load_state(app, storage, backup, payloads, manifest["sourceFiles"])
        config_path(state["config"])
        config = None
    else:
        payloads = pack.resource_payloads(app, manifest)
        pack.validate_current(app, payloads, manifest)
        if arguments.backup:
            raise RuntimeError("--backup 仅用于 restore")
        config = config_path(arguments.config)
    if arguments.action in {"check", "verify"}:
        patched = all((app / relative).exists() and pack.sha256(app / relative) == pack.content_hash(content)
                      for relative, content in payloads.items())
        print("官方安装：" + str(app))
        print("中文资源：" + ("已正确安装" if patched else "待安装"))
        print("默认语言：" + str(pack.config_data(config).get("locale", "未设置")))
        print("Cowork 服务：" + (system_query(
            "Get-Service CoworkVMServiceStore -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Status"
        ) or "未检测到（本工具不安装该服务）"))
        if arguments.action == "verify" and (not patched or pack.config_data(config).get("locale") != "zh-CN"):
            raise RuntimeError("中文资源或默认语言尚未正确安装")
        print("只读检查完成；未写入资源、修改配置或关闭应用。")
        return 0
    ensure_idle()
    if not ctypes.windll.shell32.IsUserAnAdmin():
        if arguments.elevated:
            raise RuntimeError("未获得管理员权限")
        return elevate()
    if arguments.action == "restore":
        backup = pack.restore_resources(app, storage, backup, manifest)
        print("补丁已恢复为安装前的资源及语言字段，保留当前其他配置。")
    else:
        backup = pack.install_resources(app, config, storage, manifest)
        print("中文资源和默认语言已就绪。以后从原来的官方 Claude 入口启动即可。")
    print("官方包、EXE、ASAR、Cowork 服务和启动入口保持原样；未自动启动程序。")
    if backup:
        print("本机恢复备份（可能含凭据，不要公开）：" + str(backup))
    else:
        print("现有中文补丁已正确安装，未重复写入；本工具没有此次安装的恢复记录。")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Claude 中文资源补丁：保留官方安装与 Cowork")
    parser.add_argument("action", nargs="?", choices=["install", "check", "verify", "restore"], default="install")
    parser.add_argument("--app", help="可选，受支持官方注册包的根目录或 app 目录")
    parser.add_argument("--config", help="可选，已存在的语言配置 JSON；不修改其他字段")
    parser.add_argument("--backup", help="restore 使用的本工具 backups 子目录")
    parser.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--expected-sid", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    code = 1
    try:
        code = execute(arguments)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, KeyboardInterrupt, subprocess.SubprocessError) as error:
        print("操作未完成：" + str(error), file=sys.stderr)
        print("目录拒绝写入时请停止，不要卸载官方版或反复修改 WindowsApps 权限。参见 docs/恢复与卸载.md。", file=sys.stderr)
    if arguments.elevated:
        try:
            input("按 Enter 关闭此结果窗口…")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
