#!/usr/bin/env python3
"""VIGIL 一键启动器 —— `run.cmd` 的 Python 侧。

职责：把「双击 run.cmd」变成「浏览器里出现日报」，并在任何前置不满足时
**明说缺什么、怎么补**，而不是起一个白屏或静默退出。

检查顺序（每一步不满足就停下来说清楚，而不是带病往下走）：
  1. `.env` 在不在、两个 key 填没填   → 缺则复制模板并打开它，退出码 3
  2. 数据在不在（`data/vigil.db`）    → 缺则告诉他先跑 `vigil daily`，退出码 4
  3. 端口占没占                       → 占了则换一个（或明说怎么换），不喷异常
  4. 前端构建在不在（`web/dist`）     → 缺则提示两种补法（不致命，服务照起）
  5. 起服务 + **等就绪后**再开浏览器

**为什么这些检查不放在 run.cmd 里**：cmd 解析中文要命（OEM 码页），而这些
判断需要可读的错误与可测的逻辑 —— 与 `serve_supervisor.py` 同一条论证。

端口：默认 8787，可用 `--port N` 或环境变量 `VIGIL_PORT` 覆盖；被占则自动
向后再找一个空闲端口（`--no-auto-port` 可关掉，改为直接报错）。

退出码：0 正常；3 需要用户填 `.env`；4 还没有数据；5 端口不可用；1 其它意外。
"""

from __future__ import annotations

import argparse
import os
import pathlib
import socket
import subprocess
import sys
import time
import webbrowser

REPO = pathlib.Path(__file__).resolve().parent.parent
ENV_FILE = REPO / ".env"
ENV_EXAMPLE = REPO / ".env.example"
VIGIL_DB = REPO / "data" / "vigil.db"
WEB_DIST_INDEX = REPO / "web" / "dist" / "index.html"

HOST = "127.0.0.1"
DEFAULT_PORT = 8787
_BAR = "=" * 64


def _say(*lines: str) -> None:
    for ln in lines:
        print(ln, flush=True)


def _read_env_file() -> dict[str, str]:
    """极简 .env 解析（只取值，不处理复杂转义——够这里用）。"""
    out: dict[str, str] = {}
    if not ENV_FILE.is_file():
        return out
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _open_path(p: pathlib.Path) -> None:
    """用系统默认程序打开一个文件/文件夹（失败不致命）。

    ⚠️ **只在交互式控制台里自动打开**（`sys.stdout.isatty()`）。双击 run.cmd 时
    这是真控制台 → 打开编辑器✓；但 stdout 被重定向到管道/文件时（CI、`| head`、
    日志收集）NO。理由是一次实测：GUI 编辑器会**继承并占住那个管道**，于是
    `python run_vigil.py | head` 整条管道迟迟不结束 —— 看起来像启动器卡死，
    其实是编辑器握着写端。无头场景下只打印路径即可，用户自己会去看。
    """
    if not sys.stdout.isatty():
        return
    try:
        if sys.platform == "win32":
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)], close_fds=True)
        else:
            subprocess.Popen(["xdg-open", str(p)], close_fds=True)
    except Exception as exc:  # noqa: BLE001 - 打开失败不该挡住主流程
        print(f"  （自动打开失败：{exc}）", flush=True)


def check_env() -> bool:
    """.env 与两个 key 是否就绪。不就绪则说明+打开模板，返回 False。"""
    d = _read_env_file()
    db_key = d.get("VIGIL_DB_KEY", "")
    llm_key = d.get("SILICONFLOW_API_KEY", "")

    missing = [name for name, val in
               (("VIGIL_DB_KEY", db_key), ("SILICONFLOW_API_KEY", llm_key)) if not val]

    if ENV_FILE.is_file() and not missing:
        _say("[1/4] .env 已就绪（两个 key 都已填写）。")
        return True

    _say("", _BAR)
    if not ENV_FILE.is_file():
        _say("[1/4] 还没建 .env —— 已从模板复制一份：", f"      {ENV_FILE}")
        ENV_FILE.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        _open_path(ENV_FILE)
    else:
        _say("[1/4] .env 里有 key 还没填：", "      " + "、".join(missing))
        _open_path(ENV_FILE)

    _say(
        "",
        "      请填入：",
        "        VIGIL_DB_KEY       = 你的 QQ 本地库解密密钥（16 字节）",
        "        SILICONFLOW_API_KEY= 去 https://cloud.siliconflow.cn/account/ak 申请",
        "",
        "      两个 key 都**不能从仓库里拿到**。VIGIL_DB_KEY 只能用",
        "      windows_ntqq_get_key.ps1 从本机 QQ 安装里提取（以调试器启动 QQ，",
        "      命中 nt_sqlite3_key_v2 断点后打印）。完整步骤见",
        "      docs/SETUP-ROUTE-C.md §五。",
        "",
        "      填好后，再次双击 run.cmd。",
        _BAR, "",
    )
    return False


def check_data() -> bool:
    """数据在不在。不在则告诉他先跑管线。"""
    if VIGIL_DB.is_file():
        _say(f"[2/4] 数据在（{VIGIL_DB}）。")
        return True
    _say(
        "", _BAR,
        "[2/4] 还没有数据 —— 找不到",
        f"      {VIGIL_DB}",
        "",
        "      这个服务只**读**它；先把群消息导进来，再回来起服务：",
        "",
        "          uv run vigil daily      # export → refine → digest 三步管线",
        "",
        "      首次运行需要：QQ 正在运行、config/groups.toml 里配好了要监听的群。",
        "      详见 README「怎么跑」与 docs/SETUP-自动化.md。",
        _BAR, "",
    )
    return False


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        # connect_ex 返回 0 表示连上了 => 有人在监听
        return s.connect_ex((host, port)) == 0


def _find_free_port(host: str, start: int, tries: int = 20) -> int | None:
    for p in range(start, start + tries):
        if not _port_in_use(host, p):
            return p
    return None


def resolve_port(want: int, allow_auto: bool) -> int | None:
    """返回可用的端口；不可用且不允许自动则返回 None。"""
    if not _port_in_use(HOST, want):
        _say(f"[3/4] 端口 {want} 空闲。")
        return want

    # 端口被占。常见情况是 VIGIL 自己已经在跑（任务计划/另一个窗口）。
    alt = _find_free_port(HOST, want + 1) if allow_auto else None
    _say(
        "", _BAR,
        f"[3/4] ⚠️ 端口 {want} 已被占用。",
        "",
        "      最可能的原因：VIGIL 服务**已经在跑**了（任务计划「VIGIL网页服务」",
        "      会在登录时自启，或你之前开的窗口还开着）。若是，直接访问：",
        f"          http://{HOST}:{want}",
        "",
    )
    if alt is not None:
        _say(f"      也可以换个端口开第二个实例 —— 已自动选 {alt}。", _BAR, "")
        return alt
    _say(
        "      想换端口，用：  run.cmd --port 8899",
        "      （或设环境变量 VIGIL_PORT）",
        _BAR, "",
    )
    return None


def warn_frontend() -> None:
    """前端没构建 —— 不致命，服务照起（会显示一行提示页），但要说清楚。"""
    if WEB_DIST_INDEX.is_file():
        _say("[4/4] 前端已构建。")
        return
    _say(
        "[4/4] ⚠️ 前端还没构建 —— 服务仍会启动，但页面只会显示一行提示。",
        "      两种补法（任选其一）：",
        "        · 用发行版附件里预构建好的 web/dist（解压到 web/ 下）",
        "        · 本机构建：cd web && npm install && npm run build",
    )


def _wait_ready(host: str, port: int, timeout: float = 15.0) -> bool:
    """等端口真的在监听（uvicorn 起来要一小会儿），就绪后再开浏览器。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_in_use(host, port):
            return True
        time.sleep(0.25)
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="VIGIL 一键启动器")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("VIGIL_PORT", DEFAULT_PORT)),
                    help=f"监听端口（默认 {DEFAULT_PORT}，被占则自动 +1 找一个）")
    ap.add_argument("--no-auto-port", action="store_true",
                    help="端口被占时直接报错，不要自动换端口")
    ap.add_argument("--no-browser", action="store_true", help="不要自动开浏览器")
    args = ap.parse_args(argv)

    _say("", _BAR, "  VIGIL · 守夜人 —— 一键启动", _BAR, "")

    if not check_env():
        return 3
    if not check_data():
        return 4

    port = resolve_port(args.port, allow_auto=not args.no_auto_port)
    if port is None:
        return 5

    warn_frontend()

    url = f"http://{HOST}:{port}"
    _say("", _BAR, f"  启动中：{url}", "  按 Ctrl-C 停止。", _BAR, "")

    from vigil.cli import main as cli_main  # 延迟导入：前面失败时不必付导入成本

    if not args.no_browser:
        # 等就绪再开——开早了用户只会看到「无法访问」。起不来就不开。
        if _wait_ready(HOST, port):
            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001 - 开浏览器失败不该挡住服务
                pass

    # 直接复用 CLI，保证与 `uv run vigil serve` 完全同一套行为。
    return cli_main(["serve", "--host", HOST, "--port", str(port)])


if __name__ == "__main__":
    raise SystemExit(main())
