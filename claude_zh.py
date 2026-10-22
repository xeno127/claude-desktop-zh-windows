from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import stat
import uuid


ROOT = Path(__file__).resolve().parent
PACK = ROOT / "language-pack"
LANGUAGES = '["en-US","de-DE","fr-FR","ko-KR","ja-JP","es-419","es-ES","it-IT","hi-IN","pt-BR","id-ID"]'
LABEL = ';(()=>{const proto=Intl.DisplayNames?.prototype;if(!proto||proto.__claudeZhLabelPatch)return;const original=proto.of;proto.of=function(locale){return String(locale)==="zh-CN"?"简体中文":original.call(this,locale)};Object.defineProperty(proto,"__claudeZhLabelPatch",{value:true})})();\n'


def read_json(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    temporary.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_hash(content):
    return hashlib.sha256(content).hexdigest()


def safe_relative(value):
    path = Path(value)
    if path.is_absolute() or path.drive or ".." in path.parts or "\\" in value:
        raise RuntimeError("资源清单含不安全路径")
    return path


def regular(path):
    path = Path(path)
    if path.exists() and (path.is_symlink() or getattr(path.stat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise RuntimeError("拒绝操作链接或重解析路径：" + str(path))


def safe_target(root, relative):
    target = root / safe_relative(relative)
    current = target
    while current != root:
        regular(current)
        current = current.parent
    regular(root)
    return target


def check_pack(directory=PACK):
    manifest = read_json(directory / "manifest.json")
    for entry in manifest["catalogs"].values():
        path = directory / safe_relative(entry["path"])
        if sha256(path) != entry["sha256"] or len(read_json(path)) != entry["entries"]:
            raise RuntimeError("语言文件校验失败：" + entry["path"])
    return manifest


def patched_bundle(source):
    if source.count(LANGUAGES) != 2:
        raise RuntimeError("语言菜单结构变化，停止安装")
    return source.replace(LANGUAGES, LANGUAGES[:-1] + ',"zh-CN"]') + "\n" + LABEL


def resource_payloads(app, manifest, directory=PACK, bundle_raw=None):
    for relative, expected in manifest["sourceFiles"].items():
        if relative == manifest["bundlePath"]:
            continue
        path = safe_target(app, relative)
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError("版本或源文件不符：" + relative)
    bundle = manifest["bundlePath"]
    raw = safe_target(app, bundle).read_bytes() if bundle_raw is None else bundle_raw
    if content_hash(raw) != manifest["sourceFiles"][bundle]:
        suffix = ("\n" + LABEL).encode("utf-8")
        if not raw.endswith(suffix):
            raise RuntimeError("语言菜单源文件变化，停止覆盖")
        raw = raw[:-len(suffix)].replace(
            (LANGUAGES[:-1] + ',"zh-CN"]').encode(), LANGUAGES.encode()
        )
        if content_hash(raw) != manifest["sourceFiles"][bundle]:
            raise RuntimeError("语言菜单存在其他修改，停止覆盖")
    payloads = {}
    for entry in manifest["catalogs"].values():
        source = directory / safe_relative(entry["path"])
        if sha256(source) != entry["sha256"]:
            raise RuntimeError("语言文件校验失败")
        english = read_json(safe_target(app, "resources/" + entry["sourcePath"]))
        chinese = read_json(source)
        if english.keys() != chinese.keys():
            raise RuntimeError("翻译键集合与当前版本不一致")
        payloads["resources/" + entry["path"]] = source.read_bytes()
    payloads["resources/zh-Hans.json"] = payloads["resources/zh-CN.json"]
    payloads[bundle] = patched_bundle(raw.decode("utf-8")).encode("utf-8")
    for relative, content in payloads.items():
        safe_target(app, relative)
        expected = manifest.get("installedFiles", {}).get(relative)
        if expected and content_hash(content) != expected:
            raise RuntimeError("生成的补丁哈希与清单不符：" + relative)
    return payloads


def validate_current(app, payloads, manifest):
    for relative, content in payloads.items():
        target = safe_target(app, relative)
        if not target.exists():
            if relative == manifest["bundlePath"]:
                raise RuntimeError("缺少语言菜单源文件")
            continue
        allowed = {content_hash(content), manifest["sourceFiles"].get(relative)}
        if sha256(target) not in allowed:
            raise RuntimeError("资源存在其他修改，停止覆盖：" + relative)


def probe_writes(app, payloads):
    for relative in payloads:
        target = safe_target(app, relative)
        if target.exists():
            with target.open("r+b"):
                pass
    for parent in {safe_target(app, relative).parent for relative in payloads}:
        probe = parent / (".claude-zh-probe-" + uuid.uuid4().hex)
        try:
            with probe.open("xb") as target:
                target.write(b"probe")
        finally:
            if probe.exists():
                probe.unlink()


def write_resource(path, content):
    if content is None:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(content)


def config_data(config):
    regular(config)
    regular(config.parent)
    data = read_json(config)
    if not isinstance(data, dict):
        raise RuntimeError("语言配置必须是 JSON 对象")
    return data


def backup_path(storage, backup):
    storage = storage.resolve()
    backup = Path(backup).resolve()
    if backup.parent != storage / "backups":
        raise RuntimeError("备份路径必须位于本工具的 backups 目录")
    regular(storage)
    regular(storage / "backups")
    regular(backup)
    return backup


def load_state(app, storage, backup, payloads, source_files):
    backup = backup_path(storage, backup)
    regular(backup / "state.json")
    state = read_json(backup / "state.json")
    if Path(state["app"]).resolve() != app.resolve() or set(state["files"]) != set(payloads):
        raise RuntimeError("备份应用路径或资源清单不匹配")
    for relative, record in state["files"].items():
        safe_relative(relative)
        if record["installed"] != content_hash(payloads[relative]):
            raise RuntimeError("备份资源清单与当前补丁不匹配")
        allowed_originals = {None, record["installed"], source_files.get(relative)}
        if relative in source_files:
            allowed_originals.discard(None)
        if record["original"] not in allowed_originals:
            raise RuntimeError("原资源备份哈希不属于受支持清单")
        if record["original"] is not None:
            saved = safe_target(backup / "files", relative)
            if not saved.is_file() or sha256(saved) != record["original"]:
                raise RuntimeError("原资源备份损坏：" + relative)
    saved_config = backup / "config-before.json"
    regular(saved_config)
    if sha256(saved_config) != state["configHash"]:
        raise RuntimeError("配置备份损坏")
    return backup, state


def change_files(app, config, payloads, updated_config):
    previous = {relative: (app / relative).read_bytes() if (app / relative).exists() else None for relative in payloads}
    previous_config = config.read_bytes()
    changed = []
    try:
        for relative, content in payloads.items():
            changed.append(relative)
            write_resource(app / relative, content)
            if content is None:
                if (app / relative).exists():
                    raise RuntimeError("资源删除验证失败")
            elif sha256(app / relative) != content_hash(content):
                raise RuntimeError("资源写入验证失败")
        write_json(config, updated_config)
        if config_data(config) != updated_config:
            raise RuntimeError("语言配置写入验证失败")
    except BaseException as error:
        failures = []
        for relative in reversed(changed):
            try:
                write_resource(app / relative, previous[relative])
            except OSError:
                failures.append(relative)
        try:
            config.write_bytes(previous_config)
        except OSError:
            failures.append("config.json")
        if failures:
            raise RuntimeError("回滚未全部完成，请保留备份并运行 restore；失败项：" + ", ".join(failures)) from error
        raise


def install_resources(app, config, storage, manifest, directory=PACK):
    payloads = resource_payloads(app, manifest, directory)
    validate_current(app, payloads, manifest)
    original_config = config_data(config)
    pointer = storage / "last-install.json"
    backup = None
    state = None
    if pointer.exists():
        regular(pointer)
        info = read_json(pointer)
        if info.get("app") and Path(info["app"]).resolve() == app.resolve():
            backup, state = load_state(app, storage, info["backup"], payloads, manifest["sourceFiles"])
            if state["phase"] == "prepared":
                raise RuntimeError("有中断的安装，请先运行 restore")
            if state["phase"] == "restored":
                backup = state = None
            elif Path(state["config"]).resolve() != config.resolve():
                raise RuntimeError("本次配置路径与原备份不一致")
    complete = all((app / relative).exists() and sha256(app / relative) == content_hash(content) for relative, content in payloads.items())
    if complete and original_config.get("locale") == "zh-CN":
        return backup
    if complete and backup is None:
        raise RuntimeError("检测到其他方式安装的补丁；缺少本工具备份，请用原安装工具恢复后再安装")
    regular(storage)
    regular(storage / "backups")
    probe_writes(app, payloads)
    if backup is None:
        backup = storage / "backups" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        backup.mkdir(parents=True)
        if pointer.exists():
            shutil.copyfile(pointer, backup / "previous-install-record.json")
        state = {"schema": 2, "phase": "prepared", "app": str(app.resolve()), "version": manifest["version"],
                 "config": str(config.resolve()), "configHash": sha256(config), "files": {}}
        shutil.copyfile(config, backup / "config-before.json")
        for relative, content in payloads.items():
            target = app / relative
            original = sha256(target) if target.exists() else None
            state["files"][relative] = {"original": original, "installed": content_hash(content)}
            if original is not None:
                saved = backup / "files" / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(target, saved)
        write_json(backup / "state.json", state)
        load_state(app, storage, backup, payloads, manifest["sourceFiles"])
    if config_data(config) != original_config:
        raise RuntimeError("备份期间配置发生变化，请先退出 Claude")
    resource_payloads(app, manifest, directory)
    validate_current(app, payloads, manifest)
    state["phase"] = "prepared"
    write_json(backup / "state.json", state)
    write_json(pointer, {"app": str(app.resolve()), "backup": str(backup.resolve())})
    updated = dict(original_config)
    updated["locale"] = "zh-CN"
    try:
        change_files(app, config, payloads, updated)
    except BaseException:
        state["phase"] = "prepared"
        write_json(backup / "state.json", state)
        raise
    resource_payloads(app, manifest, directory)
    state["phase"] = "complete"
    write_json(backup / "state.json", state)
    return backup


def restoration_payloads(app, storage, backup, manifest, directory=PACK):
    backup = backup_path(storage, backup)
    saved_bundle = safe_target(backup / "files", manifest["bundlePath"])
    allowed = {manifest["sourceFiles"][manifest["bundlePath"]],
               manifest.get("installedFiles", {}).get(manifest["bundlePath"])}
    if sha256(saved_bundle) not in allowed:
        raise RuntimeError("语言菜单备份损坏，停止恢复")
    return resource_payloads(app, manifest, directory, saved_bundle.read_bytes())


def restore_resources(app, storage, backup, manifest, directory=PACK):
    payloads = restoration_payloads(app, storage, backup, manifest, directory)
    backup, state = load_state(app, storage, backup, payloads, manifest["sourceFiles"])
    if state["phase"] not in {"complete", "prepared", "restored"}:
        raise RuntimeError("未知备份状态")
    config = Path(state["config"])
    current = config_data(config)
    original = config_data(backup / "config-before.json")
    restored = dict(current)
    if "locale" in original:
        restored["locale"] = original["locale"]
    else:
        restored.pop("locale", None)
    resources = {}
    for relative, record in state["files"].items():
        target = safe_target(app, relative)
        actual = sha256(target) if target.exists() else None
        if state["phase"] != "prepared" and actual not in {record["original"], record["installed"]}:
            raise RuntimeError("资源发生变化或冲突，停止恢复：" + relative)
        resources[relative] = (backup / "files" / relative).read_bytes() if record["original"] is not None else None
    probe_writes(app, payloads)
    change_files(app, config, resources, restored)
    state["phase"] = "restored"
    write_json(backup / "state.json", state)
    return backup
