"""编排层测试。用假 LLM 与内存库，绝不联网、绝不碰真实数据。"""

from __future__ import annotations

import sqlite3

import pytest

from vigil import refine, store
from vigil.llm import LLMResult
from vigil.store import STATUS_DISCARDED, STATUS_OK


class FakeLLM:
    """记录调用、按脚本返回。用于验证编排逻辑而非模型质量。"""

    def __init__(self, script=None):
        self.calls = []
        self.script = script or (lambda messages: {"items": []})

    def __call__(self, cfg, *, system, user, sleep=None):
        self.calls.append({"system": system, "user": user})
        return LLMResult(
            payload=self.script(user), input_tokens=100, output_tokens=20
        )


@pytest.fixture
def seeded(memdb):
    memdb.executescript(
        """
        CREATE TABLE messages (
            msg_id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL,
            ts INTEGER NOT NULL, sender_uid TEXT, content TEXT NOT NULL
        );
        CREATE TABLE sender_names (
            group_id INTEGER NOT NULL, uid TEXT NOT NULL, group_nick TEXT,
            qq_nick TEXT, uin INTEGER, in_group INTEGER,
            PRIMARY KEY (group_id, uid)
        );
        """
    )
    memdb.executemany(
        "INSERT INTO messages VALUES (?,?,?,?,?)",
        [
            (1, 100, 1000, "u_a", "明天下午有讲座，地点西太湖报告厅"),
            (2, 100, 1001, "u_b", "已完成"),
            (3, 100, 1002, "u_a", "数学作业截止到9月7号"),
        ],
    )
    memdb.executemany(
        "INSERT INTO sender_names VALUES (?,?,?,?,?,?)",
        [(100, "u_a", "班长小王", "小王", 111, 0), (100, "u_b", "李四", "李四", 222, 0)],
    )
    memdb.commit()
    store.ensure_schema(memdb)
    return memdb


class StubConfig:
    """refine 只用到 tier_of 与群名，不需要真实配置文件。"""

    def tier_of(self, gid: int) -> str:
        return "high"

    def group_name(self, gid: int) -> str:
        return "测试群"


def test_build_system_prompt_contains_categories():
    from vigil.categories import load_categories

    prompt = refine.build_system_prompt(load_categories())
    assert "notice" in prompt and "secondhand" in prompt
    assert "items" in prompt, "必须要求 items 外层包裹（探针实测）"


def test_build_user_prompt_injects_today():
    """不给今天，模型会把「9月7号」猜成 2023（探针实测）。"""
    from vigil.redact import Redactor
    from vigil.store import PendingMessage

    msgs = [
        PendingMessage(
            msg_id=1, group_id=100, ts=1000, sender_uid="u_a",
            sender="班长小王", content="作业截止9月7号",
        )
    ]
    text = refine.build_user_prompt(msgs, Redactor(), today="2026-09-13")
    assert "2026-09-13" in text
    # 行格式：`- 代号 姓名: 内容`，不带任何编号
    assert "- U1 班长小王: 作业截止9月7号" in text


def test_build_user_prompt_redacts_numbers():
    from vigil.redact import Redactor
    from vigil.store import PendingMessage

    msgs = [
        PendingMessage(
            msg_id=1, group_id=100, ts=1000, sender_uid="u_a",
            sender="2600090309张韩18368500707", content="打我电话13812345678",
        )
    ]
    text = refine.build_user_prompt(msgs, Redactor(), today="2026-09-13")
    assert "18368500707" not in text
    assert "13812345678" not in text
    assert "张韩" in text, "姓名要保留——它是判断发送者身份的信号"


def test_build_user_prompt_distinguishes_anonymous_senders():
    """⚠️ 匿名发送者必须**逐条区分**。

    本条的存在本身就是审查的产物：Task 7 审查实测「**删掉这个特判，128 条
    测试全绿**」——实现是对的，但零守护。这是「空守卫」在同一里程碑里的
    第四次重现，所以补上。

    为什么重要：W1 波级审查实测全库 1,218 条匿名消息里 **1,196 条是实质正文**，
    含班主任助理张皓宇、卞雨琦各 11 条。若全归一个代号，模型会把互不相识的
    人当成同一个人，并把这个错误认知写进 title/detail。
    """
    from vigil.redact import Redactor
    from vigil.store import PendingMessage

    msgs = [
        PendingMessage(
            msg_id=1, group_id=100, ts=1000, sender_uid="",
            sender="", content="转发通知：明天停课",
        ),
        PendingMessage(
            msg_id=2, group_id=200, ts=1001, sender_uid="",
            sender="", content="转发通知：明天停课",
        ),
    ]
    text = refine.build_user_prompt(msgs, Redactor(), today="2026-09-13")
    assert "匿名1" in text, "第一条匿名消息要有自己的标记"
    assert "匿名2" in text, "第二条必须是**不同**的标记"
    assert text.count("匿名") == 2


def test_build_user_prompt_keeps_named_senders_stable():
    """有 uid 的仍走稳定代号——同一人两次发言必须看得出是同一人。

    与上一条互补：匿名者**逐条区分**，有身份者**稳定复用**。两条一起才
    完整描述 `build_user_prompt` 的发信人标记规则。
    """
    from vigil.redact import Redactor
    from vigil.store import PendingMessage

    msgs = [
        PendingMessage(msg_id=1, group_id=100, ts=1000, sender_uid="u_a",
                       sender="班长小王", content="第一句"),
        PendingMessage(msg_id=2, group_id=100, ts=1001, sender_uid="u_a",
                       sender="班长小王", content="第二句"),
    ]
    text = refine.build_user_prompt(msgs, Redactor(), today="2026-09-13")
    assert text.count("U1") == 2, "同一人的两条消息应共用一个代号"


def test_prompt_carries_no_numbers_at_all():
    """⚠️ 提示词里**不能出现任何编号**——msg_id 和序号都试过了，都不行。

    Task 8 冒烟实测逼出的结论：
      * **msg_id**（19 位雪花号，同批只差末 3 位）→ 命中 **0/2**
      * **批内序号** → A/B 测试命中 1/1，但**真实管线里仍然错**：
        4 条消息的批次，真来源在第 3 位，模型读对了内容却返回 `idx=1`

    所以改成**不问模型编号**：消息不带编号，来源靠 `quote` 逐字摘录本地匹配。
    这条测试守「不给模型任何可抄的编号」这个前提。
    """
    from vigil.redact import Redactor
    from vigil.store import PendingMessage

    msgs = [
        PendingMessage(msg_id=7685024133064673881, group_id=100, ts=1000,
                       sender_uid="u_a", sender="甲", content="第一条"),
        PendingMessage(msg_id=7685024133064673978, group_id=100, ts=1001,
                       sender_uid="", sender="", content="第二条"),
        PendingMessage(msg_id=7685024133064673918, group_id=100, ts=1002,
                       sender_uid="u_b", sender="乙", content="第三条"),
    ]
    text = refine.build_user_prompt(msgs, Redactor(), today="2026-09-13")

    # 19 位 msg_id 一个都不许出现
    for mid in (7685024133064673881, 7685024133064673978, 7685024133064673918):
        assert str(mid) not in text, f"提示词里不该出现长 msg_id: {mid}"
    # 也不该有行首序号
    for i in (1, 2, 3):
        assert f"\n{i}. " not in text, f"提示词里不该出现序号 {i}"
    # 发信人代号仍要保留——它是判断「同一人说了两次」的信号
    assert "U1 甲" in text
    assert "U2 乙" in text
    # 匿名者仍要逐条区分
    assert "匿名1" in text


def test_cli_refine_model_falls_back_to_default(monkeypatch, tmp_path):
    """⚠️ argparse 不给 `--model` 时传的是 `None`，而 `None` 会**绕过**
    `refine()` 的默认参数值（默认值只在「未传参」时生效）。

    CLI 不自己兜底的话，会把 `None` 当模型名发给 SiliconFlow。
    """
    from vigil import cli, refine as refine_mod

    captured = {}

    def fake_refine(config, **kwargs):
        captured.update(kwargs)
        return refine_mod.RefineStats()

    monkeypatch.setattr(refine_mod, "refine", fake_refine)
    monkeypatch.setattr(cli, "_load_config_only", lambda: object())
    monkeypatch.setattr(cli, "_require_export_db", lambda c: tmp_path / "x.db")

    assert cli.main(["refine", "--dry-run"]) == 0
    assert captured["model"] == refine_mod.DEFAULT_MODEL
    assert captured["dry_run"] is True


def test_load_llm_key_prefers_env_over_file(monkeypatch, tmp_path):
    """密钥读取：环境变量优先于 `.env`；都没有时返回空串而不是抛错。"""
    from vigil.config import load_llm_key

    env = tmp_path / ".env"
    env.write_text("SILICONFLOW_API_KEY=sk-from-file\n", encoding="utf-8")

    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    assert load_llm_key(env) == "sk-from-file"

    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-from-env")
    assert load_llm_key(env) == "sk-from-env", "环境变量应优先于 .env"

    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    assert load_llm_key(tmp_path / "nonexistent.env") == "", "文件不存在不该崩"


def test_refine_saves_items(seeded, monkeypatch):
    """一条消息产出条目 → 落库 → 记账。"""
    fake = FakeLLM(
        lambda user: {
            "items": [
                {
                    "quote": "明天下午有讲座", "kind": "activity",
                    "title": "西太湖报告厅有讲座",
                    "detail": None, "deadline": None, "place": "西太湖报告厅",
                    "amount": None, "confidence": 0.9,
                }
            ]
        }
    )
    monkeypatch.setattr(refine, "chat_json", fake)

    stats = refine.refine(
        StubConfig(), api_key="k", db_path=None, conn=seeded,
        on_progress=lambda *a, **k: None,
    )

    assert stats.items_saved == 1
    assert seeded.execute("SELECT kind, title FROM items").fetchone() == (
        "activity", "西太湖报告厅有讲座",
    )
    assert seeded.execute("SELECT item_id, msg_id FROM item_sources").fetchall() == [(1, 1)]


def test_refine_passes_thinking_switch_to_llm(seeded, monkeypatch):
    """思考开关必须一路到得了请求层。

    只断言 `refine()` 收得下参数是不够的——那正是「空守卫」的形状：
    参数在签名里、被接受、被忽略，测试照样绿。这里断言的是它
    **真的传到了交给 chat_json 的 LLMConfig 上**。

    实测依据见 llm.LLMConfig 的注释：Qwen3.5-35B-A3B 开思考 111.5s /
    11,124 输出 token，关掉 2.8s / 220 token。这个参数丢了就是 40 倍代价。
    """
    seen = []

    def fake(cfg, *, system, user, sleep=None):
        seen.append(cfg)
        return LLMResult(payload={"items": []}, input_tokens=1, output_tokens=1)

    monkeypatch.setattr(refine, "chat_json", fake)
    quiet = lambda *a, **k: None

    refine.refine(
        StubConfig(), api_key="k", conn=seeded, batch_size=1, on_progress=quiet
    )
    assert seen, "一批都没跑，这条测试就没在验证任何东西"
    assert all(c.enable_thinking is False for c in seen), "默认必须关思考"

    seen.clear()
    refine.refine(
        StubConfig(), api_key="k", conn=seeded, batch_size=1, redo=True,
        enable_thinking=True, on_progress=quiet,
    )
    assert seen, "redo 那轮一批都没跑"
    assert all(c.enable_thinking is True for c in seen), "--think 没传到请求层"


def test_refine_records_discarded_for_noise(seeded, monkeypatch):
    """硬丢弃的消息也要记账——M1 出口要求 refine_runs 无遗漏。"""
    monkeypatch.setattr(refine, "chat_json", FakeLLM())
    refine.refine(StubConfig(), api_key="k", conn=seeded, on_progress=lambda *a, **k: None)

    row = seeded.execute(
        "SELECT status FROM refine_runs WHERE msg_id = 2"
    ).fetchone()
    assert row == (STATUS_DISCARDED,)


def test_refine_is_idempotent(seeded, monkeypatch):
    """跑两次，第二次不该重复调模型、不该重复写条目。"""
    fake = FakeLLM(
        lambda user: {
            "items": [
                {"quote": "明天下午有讲座", "kind": "activity", "title": "讲座", "detail": None,
                 "deadline": None, "place": None, "amount": None, "confidence": 0.9}
            ]
        }
    )
    monkeypatch.setattr(refine, "chat_json", fake)

    refine.refine(StubConfig(), api_key="k", conn=seeded, on_progress=lambda *a, **k: None)
    first_calls = len(fake.calls)
    refine.refine(StubConfig(), api_key="k", conn=seeded, on_progress=lambda *a, **k: None)

    assert len(fake.calls) == first_calls, "第二次不该再调模型"
    assert seeded.execute("SELECT count(*) FROM items").fetchone()[0] == 1


def test_refine_parses_deadline(seeded, monkeypatch):
    fake = FakeLLM(
        lambda user: {
            "items": [
                {"quote": "数学作业截止到9月7号", "kind": "academic",
                 "title": "数学作业截止",
                 "detail": None, "deadline": "2026-09-07", "place": None,
                 "amount": None, "confidence": 0.9}
            ]
        }
    )
    monkeypatch.setattr(refine, "chat_json", fake)
    refine.refine(StubConfig(), api_key="k", conn=seeded, on_progress=lambda *a, **k: None)

    deadline = seeded.execute(
        "SELECT deadline_ts FROM items WHERE title = '数学作业截止'"
    ).fetchone()[0]
    import datetime as dt
    assert dt.datetime.fromtimestamp(deadline).strftime("%Y-%m-%d") == "2026-09-07"


def test_refine_drops_unmatchable_quote(seeded, monkeypatch):
    """摘录匹配不上就必须丢弃，不能挂到随便某条消息上。

    这是「可回溯」的最后一道闸：M1 出口标准要求能跳回原文**且内容对得上**，
    **挂错的来源比没有来源更糟**——它会让人以为数据没问题。
    """
    fake = FakeLLM(
        lambda user: {
            "items": [
                {"quote": "这段文字不在任何消息里啊", "kind": "notice",
                 "title": "编的", "detail": None, "deadline": None,
                 "place": None, "amount": None, "confidence": 0.9}
            ]
        }
    )
    monkeypatch.setattr(refine, "chat_json", fake)
    stats = refine.refine(StubConfig(), api_key="k", conn=seeded,
                          on_progress=lambda *a, **k: None)
    assert stats.items_saved == 0
    assert seeded.execute("SELECT count(*) FROM items").fetchone()[0] == 0


def test_match_source_tolerates_punctuation_but_not_rewriting():
    """摘录匹配容忍**标点/空白**差异，但不容忍**改写**。

    这条守的是 `_normalize` 的两侧边界：
      · **容忍**：全角括号 vs 半角、多余空格——模型转写时的格式差异
      · **不容忍**：换了词——那就是编的，必须丢（挂错来源比没来源更糟）
      · **太短不匹配**（`len(needle) < 4`）——否则「收到」会命中一大片

    ⚠️ 原先这里是一条「序号必须相对 batch 而非 in_scope」的测试。
    改用摘录匹配后它**失去了区分力**：`in_scope` 是所有批次的并集，
    摘录匹配到哪条就是哪条，搜 `batch` 与搜 `in_scope` 结果必然相同。
    测试的前提没了就该删，而不是留着装作还在守什么。
    """
    from vigil.store import PendingMessage

    batch = [
        PendingMessage(
            msg_id=9, group_id=1, ts=1, sender_uid="u", sender="x",
            content="有人捡到校园卡和钥匙（640）吗",
        )
    ]
    # 全角 → 半角：容忍
    assert refine._match_source("有人捡到校园卡和钥匙(640)吗", batch) is not None
    # 标点被剥掉：容忍
    assert refine._match_source("有人捡到校园卡和钥匙", batch) is not None
    # 改写：不容忍
    assert refine._match_source("有人丢失了校园卡和钥匙", batch) is None
    # 太短：不匹配
    assert refine._match_source("校园卡", batch) is None


def test_refine_respects_budget(seeded, monkeypatch):
    """预算护栏必须在超限时停下并如实报告。

    batch_size=1 是必须的：护栏在**每批开始前**检查，样本只有 3 条消息，
    默认 batch_size=30 会全挤进一批，护栏根本没机会触发。
    """
    monkeypatch.setattr(
        refine, "chat_json",
        lambda cfg, *, system, user, sleep=None: LLMResult(
            payload={"items": []}, input_tokens=10_000, output_tokens=10_000
        ),
    )
    stats = refine.refine(
        StubConfig(), api_key="k", conn=seeded, budget_tokens=5_000, batch_size=1,
        on_progress=lambda *a, **k: None,
    )
    assert stats.budget_hit is True
    # ⚠️ 计划批数与**实际**批数必须分开断言（I-3 修复的连带改动）：
    # batch_size=1 → 计划 3 批，但第 2 批开始前的预算闸就 break 了，
    # 所以实际只跑了 1 批。原先断言 `stats.batches == 3` 是在断言**旧口径**
    # （把计划数当成已跑数），那正是 CLI 在预算截断时误报「317 批」的根因。
    assert stats.batches_planned == 3, "计划 3 批"
    assert stats.batches == 1, "预算闸在第 2 批前触发，实际只跑了 1 批"
    assert stats.batches < stats.batches_planned
    assert len(seeded.execute(
        "SELECT 1 FROM refine_runs WHERE status = 'ok'"
    ).fetchall()) < 3


def test_refine_survives_llm_error(seeded, monkeypatch):
    """单批失败不该让整轮崩掉——降级并记录，沿用 export.py 的既有取舍。"""
    from vigil.llm import LLMError

    def boom(cfg, *, system, user, sleep=None):
        raise LLMError("模拟失败")

    monkeypatch.setattr(refine, "chat_json", boom)
    stats = refine.refine(StubConfig(), api_key="k", conn=seeded,
                          on_progress=lambda *a, **k: None)
    assert stats.errors, "失败要如实记录"
    assert seeded.execute(
        "SELECT count(*) FROM refine_runs WHERE status = 'error'"
    ).fetchone()[0] > 0


def test_refine_rejects_redo_with_limit(seeded):
    """redo + limit 会重复产出 items 并白烧 token——必须快速失败挡住。

    W1 Task 4 审查实测：`pending_messages(redo=True, limit=2)` 返回 [1,2,3,4,5]
    里含已处理的；CLI 上 `--redo --limit N` 是个安静的烧钱陷阱。
    """
    with pytest.raises(ValueError, match="redo"):
        refine.refine(
            StubConfig(), api_key="k", conn=seeded, redo=True, limit=2,
            on_progress=lambda *a, **k: None,
        )


def test_dry_run_makes_no_calls(seeded, monkeypatch):
    """--dry-run 只报告不调模型、不写库。"""
    fake = FakeLLM()
    monkeypatch.setattr(refine, "chat_json", fake)
    stats = refine.refine(StubConfig(), api_key="k", conn=seeded, dry_run=True,
                          on_progress=lambda *a, **k: None)
    assert fake.calls == []
    assert stats.items_saved == 0
    assert seeded.execute("SELECT count(*) FROM refine_runs").fetchone()[0] == 0


# ── 截止日写入前核验（M3 Task 1）────────────────────────────
#
# ⚠️ 本文件原本**没有** `_msg` / `_extracted`。brief 已预告这一点，按本文件既有风格补：
# 造 `PendingMessage` 的既有做法是**就地构造**（见 test_match_source_tolerates_...），
# 这里只是把同一形状收成一个函数；conftest 里另有一个 `msg_factory` fixture，
# 但它造的是「任意内容」的通用消息，而这两条用例关心的是**正文本身**
# （核验就是拿正文去比日期），所以留了局部版本、签名也保持 brief 的 `_msg` 形状。


def _msg(msg_id: int, *, content: str) -> store.PendingMessage:
    """造一条源消息。核验只关心 msg_id 与正文，其余字段取固定值。"""
    return store.PendingMessage(
        msg_id=msg_id, group_id=100, ts=1000, sender_uid="u_a",
        sender="班长小王", content=content,
    )


def _extracted(
    *, deadline_ts: int | None, title: str = "数学作业截止"
) -> store.ExtractedItem:
    """造一条 ExtractedItem，字段形状与 `_to_item` 的产出一致，来源挂在 msg 1。"""
    return store.ExtractedItem(
        kind="academic", title=title, detail=None, event_ts=1000,
        deadline_ts=deadline_ts, group_id=100, actor_uid="u_a", place=None,
        links=(), amount=None, confidence=0.9, src_msg_ids=(1,),
    )


def test_refine_drops_deadline_without_literal_evidence():
    """源文写「明早」，模型却填了具体日期——这个截止日不许落库。

    真实数据里的原样：「明早7：20各班在宿舍楼下集合」被填成 09-15。
    """
    import datetime as dt

    ts = int(dt.datetime(2026, 9, 15, 12, 0).timestamp())
    batch = [_msg(1, content="各位小班：明早7：20各班在宿舍楼下集合")]
    item = _extracted(deadline_ts=ts)
    out, dropped = refine._drop_unsupported_deadlines([item], batch)
    assert dropped == 1
    assert out[0].deadline_ts is None
    assert out[0].title == item.title       # 其余字段一个都不许动


def test_refine_keeps_deadline_with_literal_evidence():
    import datetime as dt

    ts = int(dt.datetime(2026, 9, 16, 12, 0).timestamp())
    batch = [_msg(1, content="9月16日12:00开始报名缴费")]
    out, dropped = refine._drop_unsupported_deadlines([_extracted(deadline_ts=ts)], batch)
    assert dropped == 0
    assert out[0].deadline_ts == ts


def test_parse_deadline_treats_out_of_range_dates_as_no_deadline():
    """⚠️ 「能解析成日期」与「能转成 unix 秒」是**两件事**——坏输入有两种形状。

    `_parse_deadline` 原先只捕 ValueError（挡"格式错"），而 `"1970-01-01"`
    是**合法日期**，却在 `timestamp()` 上抛 OSError（本机实测；Windows 拒绝
    1970-01-03 之前的日期）。而它偏偏是模型表达「没有截止日」最经典的哨兵
    ——最常见的那个值成了地雷。既有语义是"解析不了就当没有——**不猜**"，
    格式错与范围外在这条语义下没有区别，所以都返回 None。

    ⚠️ 这几格是**平台相关**的（POSIX 的 `timestamp()` 通常接受 1970 年）。
    本项目是 Windows 本地工具，按本机事实写；换平台时这条要重新裁决，
    别把它的绿当成跨平台的绿。
    """
    # 本体：无论"吞掉异常"还是"本来就转得成"，**都不许抛**出去——
    # 抛出去就是「一条 item 掀掉整轮」的起点（见下面两条端到端用例）
    for value in ("1970-01-01", "1970-01-02", "4000-01-01", "9999-12-30"):
        assert refine._parse_deadline(value) is None, value
    assert refine._parse_deadline("不是日期") is None   # 原有的格式错照旧
    assert refine._parse_deadline("") is None
    assert refine._parse_deadline(None) is None
    # 阳性对照：窗口内的正常日期照常解析——上面那些 None 不是"整个函数瘫了"
    import datetime as dt

    assert refine._parse_deadline("2026-09-07") == int(
        dt.datetime(2026, 9, 7).timestamp()
    )


# ── B-1：一个模型输出不许掀掉整轮 refine ────────────────────
#
# ⚠️ 下面两条端到端用例的分工，读之前先看明白（brief 的原始配方在这里做了
# 一处必要的拆分，理由写进报告）：
#   · `..._survives_the_1970_sentinel_...` 就是 brief 的配方本身：模型吐哨兵
#     日期 1970-01-01，整轮必须跑完。它钉的是修法**第一步**的语义（范围外的
#     日期 = 没有截止日），把 `_parse_deadline` 的捕获退回 ValueError 它就变红。
#   · `..._keeps_going_when_a_batch_postprocess_fails` 注入一个**真正的**本地
#     后处理异常（落库失败），钉的是修法**第二步**。把保护圈退回只捕 LLMError
#     它就变红——终审点名的性质（「单批失败不中断整轮」）由它验收。
# 两条合起来才盖住「M1 留的洞」与「M3 塞进去的新调用点」两个半边。


def _scripted(user: str, *, deadline: str | None) -> dict:
    """按批次内容产出条目——3 条种子消息 → batch_size=1 时正好 3 批。"""
    if "明天下午有讲座" in user:
        return {
            "items": [
                {"quote": "明天下午有讲座", "kind": "activity",
                 "title": "西太湖报告厅有讲座", "detail": None, "deadline": None,
                 "place": None, "amount": None, "confidence": 0.9}
            ]
        }
    if "数学作业截止到9月7号" in user:
        return {
            "items": [
                {"quote": "数学作业截止到9月7号", "kind": "academic",
                 "title": "数学作业截止", "detail": None, "deadline": deadline,
                 "place": None, "amount": None, "confidence": 0.9}
            ]
        }
    return {"items": []}


def test_refine_survives_the_1970_sentinel_end_to_end(seeded, monkeypatch):
    """⚠️ `"1970-01-01"` 是模型表达「没有截止日」最经典的哨兵，而它是**合法
    日期**——`strptime` 过了，`timestamp()` 抛 OSError。它从 `_to_item` 抛出，
    而 `_to_item` 在每批 try/except 的**外面**，于是整轮 refine 终止：
    前面跑完的批次白跑，剩下的批次永远不跑。

    这条从模型输出一路走到 items 表，断的是**整轮跑完**，
    不是"`_parse_deadline` 不抛"（那只是单元级、证明不了什么）。
    """
    fake = FakeLLM(lambda user: _scripted(user, deadline="1970-01-01"))
    monkeypatch.setattr(refine, "chat_json", fake)

    stats = refine.refine(
        StubConfig(), api_key="k", conn=seeded, batch_size=1,
        on_progress=lambda *a, **k: None,
    )

    assert stats.batches == 3, "3 批必须全部跑完（被掀掉的话停在 1）"
    assert stats.errors == [], "哨兵日期是「没有截止日」，不是错误"
    # 两条条目都落库：哨兵那条的 deadline_ts 是 NULL（"没有截止日"），
    # 其余字段照常——降级的是日期，不是条目本身
    assert dict(seeded.execute("SELECT title, deadline_ts FROM items").fetchall()) == {
        "西太湖报告厅有讲座": None, "数学作业截止": None,
    }
    assert stats.items_saved == 2
    assert stats.deadlines_dropped == 0, "哨兵不是「源文无依据」，不该计入降级"
    assert seeded.execute(
        "SELECT count(*) FROM refine_runs WHERE status = 'error'"
    ).fetchone()[0] == 0


def test_refine_keeps_going_when_a_batch_postprocess_fails(seeded, monkeypatch):
    """⭐ 单批的**本地后处理**失败，整轮不被打断。

    保护圈原先只圈住 `chat_json` 那一句（M1 的形状：只对**网络**失败成立），
    解析/核验/落库/记账全在圈外——`store.save_items(...)` 那个 sqlite3.Error
    正是 brief 亲自点名的一半。这条注入一个真的本地失败，然后断言：

      · 3 批全部跑完（被掀掉的话 `stats.batches == 1`）
      · 失败那批进 `stats.errors`、进 refine_runs 的 error 行（**可见**，
        不是静默吞异常——静默吞异常是不可接受的）
      · 别的批次的 item **真的落库了**（"继续跑"必须有产出）
    """
    fake = FakeLLM(lambda user: _scripted(user, deadline=None))
    monkeypatch.setattr(refine, "chat_json", fake)

    real_save = store.save_items

    def flaky_save(conn, items, **kwargs):
        if any(it.title == "西太湖报告厅有讲座" for it in items):
            raise sqlite3.OperationalError("模拟落库失败")
        return real_save(conn, items, **kwargs)

    monkeypatch.setattr(refine.store, "save_items", flaky_save)

    stats = refine.refine(
        StubConfig(), api_key="k", conn=seeded, batch_size=1,
        on_progress=lambda *a, **k: None,
    )

    assert stats.batches == 3, "3 批必须全部跑完（被掀掉的话停在 1）"
    assert any("第 1 批" in e for e in stats.errors), stats.errors
    assert seeded.execute(
        "SELECT count(*) FROM refine_runs WHERE status = 'error' AND msg_id = 1"
    ).fetchone()[0] == 1, "失败要记进 refine_runs，不能只写在 stats 里"
    assert seeded.execute("SELECT title FROM items").fetchall() == [
        ("数学作业截止",)
    ], "后面那批的条目照常落库——「继续跑」得是有产出的"
    assert stats.items_saved == 1


def test_refine_wires_the_deadline_drop_end_to_end(seeded, monkeypatch):
    """接线也要守——**brief 的两条用例直接调私有函数，一条都没经过 `refine()`**。

    那正是「空守卫」的形状：函数本身对，但批次循环里没人调它、或调了却忘了把计数
    累加进 stats，上面两条照样全绿，而库里仍然躺着模型编出来的日期。所以这条从模型
    输出一路走到 items 表。
    """
    fake = FakeLLM(
        lambda user: {
            "items": [
                {"quote": "数学作业截止到9月7号", "kind": "academic",
                 "title": "数学作业截止",
                 "detail": None, "deadline": "2026-09-10", "place": None,
                 "amount": None, "confidence": 0.9}
            ]
        }
    )
    monkeypatch.setattr(refine, "chat_json", fake)

    stats = refine.refine(StubConfig(), api_key="k", conn=seeded,
                          on_progress=lambda *a, **k: None)

    # 源文只有「9月7号」，模型填的 09-10 在源文里没有依据 → 只降级那一个字段
    assert stats.deadlines_dropped == 1, "降级计数必须流到 stats（CLI 靠它报警）"
    assert stats.items_saved == 1, "条目本身照常落库，降级的只是日期"
    assert seeded.execute(
        "SELECT title, deadline_ts FROM items"
    ).fetchone() == ("数学作业截止", None)
    assert seeded.execute(
        "SELECT count(*) FROM item_sources"
    ).fetchone()[0] == 1, "来源行不受影响"


# ── M4 T5：批次写入原子化 + record_run 保护圈 + M2-3 ────────────────


def test_batch_write_is_atomic_items_do_not_survive_a_failed_record(seeded, monkeypatch):
    """⭐⭐ 洞 B 的判据：**items 落库与消息记账要么都成、要么都不成。**

    注入一个"记账那一步炸掉"的失败。旧实现里 `save_items` 已经自己 commit
    过了，于是这一批的 items **留在库里**而消息**没被标记**——下次
    `pending_messages` 会把同一批再抽一遍，产出重复 items，全程无声。
    修好后：两者在同一个事务里，记账失败 ⇒ items 一并回滚。

    断言三件事：
      · 那一批的 items **不在**库里（回滚了）
      · 那一批的消息**没有**被标成 ok/discarded（否则下次就不再抽它了，
        那才是真丢数据）
      · 整轮没有被掀掉（别的批照常产出）——保护圈仍然有效
    """
    fake = FakeLLM(lambda user: _scripted(user, deadline=None))
    monkeypatch.setattr(refine, "chat_json", fake)

    real_record = store.record_run
    state = {"blown": False}

    def flaky_record(conn, msg_ids, **kwargs):
        # 只炸**成功路径**的那次（status=ok），不炸 error 记账——
        # 炸后者会连带把 _record_error 也弄坏，那就测不出想测的东西了
        if not state["blown"] and kwargs.get("status") == store.STATUS_OK:
            state["blown"] = True
            raise sqlite3.OperationalError("模拟记账失败")
        return real_record(conn, msg_ids, **kwargs)

    monkeypatch.setattr(refine.store, "record_run", flaky_record)

    stats = refine.refine(
        StubConfig(), api_key="k", conn=seeded, batch_size=1,
        on_progress=lambda *a, **k: None,
    )

    assert state["blown"], "注入没生效——测试本身有问题，别当成通过"
    assert stats.batches == 3, "3 批必须全部跑完"
    assert any("第 1 批" in e for e in stats.errors), stats.errors
    # 第 1 批那 3 条消息（scripts 里第 1 条）不许留下 ok/discarded 记账——
    # 留下了就意味着这条消息永远不会再被抽，而它的 item 已经回滚没了
    assert seeded.execute(
        "SELECT count(*) FROM refine_runs WHERE msg_id = 1 AND status != 'error'"
    ).fetchone()[0] == 0, "回滚要连记账一起回滚"
    # ⚠️ 补强（逃逸舱，见报告「偏差」）：brief 原版只断言 `count(*) >= 1`，
    # 而**旧实现照样满足它**——第 1 批的 item 还在库里、第 3 批的也在，
    # `>= 1` 分不清「回滚了」与「没回滚」。洞 B 的判据必须点名**那一批**的
    # item：它要么跟着记账一起消失，要么就是那个会引来重抽的重复条目。
    assert seeded.execute(
        "SELECT count(*) FROM items WHERE title = '西太湖报告厅有讲座'"
    ).fetchone()[0] == 0, "记账失败的批次，它的 items 必须一并回滚"
    assert seeded.execute("SELECT count(*) FROM items").fetchone()[0] >= 1, \
        "后面那批的条目照常落库——「继续跑」得是有产出的"
    # ⚠️ 补强（逃逸舱，见报告「偏差」）：**「落了盘」与「还挂在连接的事务里」
    # 在同一连接上看起来一模一样**——本文件其余 refine 用例全都在同一条连接上
    # 读，把 `with store.transaction(conn)` 整块删掉（只留 `commit=False`）
    # 它们**照样全绿**（实测，报告里的 M2）。而真管线用的是**文件库**、
    # `finally: conn.close()`：真没 commit 的话，`close()` 会把这一轮的产出
    # 整个回滚掉——无人值守下就是「跑完了、库里什么都没有」。
    # 所以这里钉一条「连接上不许留着没提交的事务」：它与 items 是否可见无关，
    # 是唯一能区分「已提交」与「pending」的判据。
    assert not seeded.in_transaction, "一轮跑完不许留着未提交的事务"


def test_record_error_failure_does_not_kill_the_run(seeded, monkeypatch):
    """⭐ M3-2：**记账自己也失败时，不许掀掉整轮。**

    三处 `record_run` 原先都裸奔在 `except` 体里。异常处理路径上再抛异常，
    `except` 接不住自己。这里让 `record_run` **永远**炸——模拟"库锁死/只读/
    磁盘满"，那正是最可能连续失败的时候。

    断言：整轮跑完、错误**仍然可见**（进 stats.errors），不是静默吞掉。
    """
    fake = FakeLLM(lambda user: _scripted(user, deadline=None))
    monkeypatch.setattr(refine, "chat_json", fake)

    def always_boom(conn, msg_ids, **kwargs):
        raise sqlite3.OperationalError("模拟库一直写不进去")

    monkeypatch.setattr(refine.store, "record_run", always_boom)

    stats = refine.refine(
        StubConfig(), api_key="k", conn=seeded, batch_size=1,
        on_progress=lambda *a, **k: None,
    )

    assert stats.batches == 3, "记账全炸也不许掀掉整轮"
    assert any("记账" in e for e in stats.errors), \
        f"记账失败必须可见（进 stats.errors），实际：{stats.errors}"


def test_prompt_sanitizes_fullwidth_quotes(seeded, monkeypatch):
    """M2-3 + 发现 9：出网文本里不许有全角引号。

    两重收益：① 防模型退化成无限空格循环（原先的理由）；② `“”` 换成
    `「」` 之后，refine 的归一化表（`_PUNCT`）**认得** `「」` 而不认得 `“”`
    ——所以模型摘录时引号包一层也不会再丢掉来源（发现 9 实测的那个洞）。

    ⚠️ 偏差（逃逸舱）：brief 里这条用的是 `_seeded_with(msg)` 这个**并不存在**
    的夹具。这里改成**用既有的 `seeded` 夹具**、往它里面补一条带全角引号的
    消息——batch_size=1 时每条消息自成一批，最后一批就是这条，断言落在
    最后一次出网的 `user` 上。没有新造/改写任何既有夹具。
    """
    sent = {}
    fake = FakeLLM()

    def capture(cfg, *, system, user, sleep=None):
        sent["user"] = user
        return fake(cfg, system=system, user=user)

    monkeypatch.setattr(refine, "chat_json", capture)

    # ts 取最大，保证它是**最后**一批（pending_messages 按时间升序）
    seeded.execute(
        "INSERT INTO messages VALUES (?,?,?,?,?)",
        (4, 100, 1003, "u_x", "他说“明天交作业”了"),
    )
    seeded.commit()

    refine.refine(StubConfig(), api_key="k", conn=seeded, batch_size=1,
                  on_progress=lambda *a, **k: None)

    assert sent, "一批都没跑，这条测试就没在验证任何东西"
    assert "“" not in sent["user"] and "”" not in sent["user"], \
        "全角引号必须被 sanitize_for_llm 换掉"
    assert "「明天交作业」" in sent["user"]


def test_quote_with_fullwidth_quotes_still_matches_its_source():
    """⭐ 源文**自己**含全角引号时，摘录整句仍要匹配回来源。

    这是 M2-3 修复**引入的回归**的判据：`sanitize_for_llm` 把 `“”` 换成 `「」`
    送出去，模型照抄回来的是 `「」`，而源文里躺着 `“”`。只剥 `「」` 不剥 `“”`
    的话两侧归一化不对称，**整句摘录的子串对不上 ⇒ 那条 item 丢掉来源**。
    修之前这些消息是匹配得上的（两侧都是 `“”`），所以这是净回归。
    实测全库 ~25/47,719 命中。

    ⚠️ 修法是让 `refine._PUNCT` 与 `digest._PUNCT` **逐字一致**（那边早就有
    这组引号，理由与这边同源：一侧出网时换过字符、另一侧没有）。
    """
    from vigil.store import PendingMessage

    batch = [
        PendingMessage(msg_id=9, group_id=1, ts=1, sender_uid="u", sender="x",
                       content="他说“明天交作业”了"),
    ]

    # ① 模型按**净化后**的提示词逐字摘录（提示词里是 「」）→ 必须命中（回归本体）
    assert refine._match_source("他说「明天交作业」了", batch) is not None
    # ② 模型照抄库内原文（“”）→ 也要命中：两个方向靠同一张表兜住
    assert refine._match_source("他说“明天交作业”了", batch) is not None
    # ③ 反面：不相干的摘录照样不命中——剥引号不许把「不同的句子」也放进来
    assert refine._match_source("他说「后天交作业」了", batch) is None
    assert refine._match_source("他说明天交体育作业了", batch) is None


def test_stripping_quote_characters_does_not_manufacture_wild_attribution():
    """反向阳性对照：多剥一组引号，会不会**制造假匹配 / 误归属**？

    ⚠️ 这是 `_PUNCT` 加 `“”`、`"` 之后必须回答的问题（比丢来源更糟的那种错）。
    分三层钉：

    ① **不许把只差一个字的句子混起来**（真正的鉴别力还在）：两条消息
       「明天交作业」/「后天交作业」只差一个字，摘录必须落回**对的那条**。
       剥引号若伤到正文，两条会归一化成同一个串，先到先得就会误归属。
    ② **不许跨到真正不同的消息上**：批里的无关消息永远不许被认成来源。
    ③ **同文异引号之间确实是歧义**，且这是**既有的**、不是本次改动引入的：
       实测（改 `_PUNCT` 之前跑同一份探针）「A 的净化形摘录」就已经会落到 B 上
       ——因为 `sanitize_for_llm` 抹掉的那两个字符，模型**本来就没看见**，
       两条消息对模型本来就不可区分。改后修复的方向（净化形摘录）反而开始
       落回真来源 A。所以这里只断言「返回的那条在文字上支持这条摘录」，
       不假装它总能挑对双胞胎。
    """
    from vigil.store import PendingMessage

    def m(mid: int, content: str) -> store.PendingMessage:
        return PendingMessage(msg_id=mid, group_id=1, ts=mid, sender_uid="u",
                              sender="x", content=content)

    # ① 只差一个字：剥引号之后仍必须分得开
    tomorrow = m(1, "他说“明天交作业”了")
    dayafter = m(2, "他说“后天交作业”了")
    assert refine._match_source(
        "他说「后天交作业」了", [tomorrow, dayafter]
    ).msg_id == 2, "剥引号不许把「明天/后天」也归一化掉"
    assert refine._match_source(
        "他说「明天交作业」了", [tomorrow, dayafter]
    ).msg_id == 1

    # ② 真正不同的消息绝不能被认成来源
    unrelated = m(3, "数学作业截止到9月7号")
    assert refine._match_source(
        "数学作业截止到9月7号", [tomorrow, dayafter, unrelated]
    ).msg_id == 3
    assert refine._match_source("他说「明天交作业」了", [unrelated]) is None

    # ③ 双胞胎（同文异引号）：返回的那条必须在**文字上支持**这条摘录
    twin_raw = m(1, "他说“明天交作业”了")
    twin_plain = m(2, "他说明天交作业了")
    for quote in ("他说「明天交作业」了", "他说“明天交作业”了", "他说明天交作业了"):
        src = refine._match_source(quote, [twin_raw, twin_plain])
        assert src is not None, quote
        assert refine._normalize(quote) in refine._normalize(src.content), (
            f"来源不支持这条摘录：{quote!r} -> {src.content!r}"
        )

    # ④ **表格的边界：只许剥标点/空白，不许碰正文。**
    #    ⚠️ 先把一条**错误论证**钉在这里（独立审查推翻、本机复现）：
    #    「两侧对称剥离，所以不会误归属」是**假的**——两侧同时剥字符，**仍然**
    #    会让「只差被剥字符」的两条消息互相顶替，摘录挂到另一个人头上。
    #    反例（③ 的双胞胎就是同一形状）：批序 [msg2 李四…, msg1 小王…]，
    #    模型照抄 msg1 的净化形 ⇒ 改前 None（fail-safe 丢来源）、**改后 → msg2**。
    #    让本次改动站得住的是**实测**：全库 47,719 条按群、按 message-id 簇比较，
    #    新增歧义簇 = 0（口径见 refine.py 的 `_PUNCT` 注释）。
    #    ⇒ 危险的是**剥到正文**：那才会把内容不同的句子变成同一条。
    #    这条直接钉住表格边界——往 `_PUNCT` 里加任何正文汉字（哪怕只加一个「天」）
    #    都会立刻变红。⚠️ 它同时是反向对照的牙齿：①②③ 单凭自身抓不住
    #    「表格被写宽了」（实测：只加「天」时 ①②③ 全绿）。
    assert refine._normalize("明天交作业") == "明天交作业", \
        "_PUNCT 只许剥标点/空白：剥到正文就会把不同的句子变成同一条"
    assert refine._normalize('他说“明天交作业”了') == "他说明天交作业了", \
        "全角引号（本次新增的那组）必须被剥掉"
    assert refine._normalize("　（640）\t") == "640", "标点/空白照旧剥掉（既有语义不变）"


def test_progress_failure_after_commit_does_not_poison_the_ledger(seeded, monkeypatch):
    """⭐⭐ 事务**提交之后**报进度失败，**不许**把已成功的批次改记成 error。

    旧形状：成功话术的 `on_progress` 在 `try` **里面** ⇒ 它抛（写日志失败）
    会被下面那个 `except Exception` 接住 ⇒ `_record_error` 对**整批** `batch_ids`
    做 `INSERT OR REPLACE` 记 `error` ⇒ **把刚提交的 `ok` 覆盖掉**（`hit_ids ⊆
    batch_ids`，所以一定被覆盖）⇒ 下轮 `pending_messages` 把那些消息**重新取出来**
    ⇒ **重复 items 且无声**。

    ⇒ 它是 M4 要消灭的形状，只在「事务已提交、报进度失败」这个**夹缝**里触发：
    提交之前炸会被回滚（安全），提交之后炸才会毒化账目。

    修法：成功话术必须放在 `try/except` **之外**——报告类失败要**响**（冒出去），
    不许被那个 `except Exception` 接住。
    """
    fake = FakeLLM(lambda user: _scripted(user, deadline=None))
    monkeypatch.setattr(refine, "chat_json", fake)

    def flaky_progress(msg, *a, **kw):
        # 只炸**成功话术**那一条（`批次 N/M`）；错误话术（`第 N 批…失败`）不炸——
        # 炸后者会把 `_record_error` 那条路径也弄坏，就测不出想测的东西了
        if "批次" in msg:
            raise RuntimeError("模拟写日志失败")
        return None

    # ⚠️ 不用 `pytest.raises` 包住整个调用：那样旧代码下会红在「有没有抛」，
    # 而本条要钉的是**账目有没有被毒化**——账目断言必须排在**最前面**，
    # 否则「红在正确的那条断言上」这件事就没被证明。
    raised: RuntimeError | None = None
    try:
        refine.refine(StubConfig(), api_key="k", conn=seeded, batch_size=1,
                      on_progress=flaky_progress)
    except RuntimeError as exc:
        raised = exc

    # ① 已提交的那批，账目必须还是 ok——**这条就是本修复的全部意义**
    assert seeded.execute(
        "SELECT count(*) FROM refine_runs WHERE msg_id = 1 AND status = 'ok'"
    ).fetchone()[0] == 1, "提交成功的批次被 _record_error 改记成 error 了"
    # ② 它**不许**再被当成待处理：重抽 = 重复 items（洞 B 的同一个形状）
    assert 1 not in [m.msg_id for m in store.pending_messages(seeded)], \
        "被改记成 error 的消息下轮会被重抽 ⇒ 重复 items 且无声"
    # ③ 条目数不许因这次失败变多：只有第 1 批提交过，items 就只有它那一条
    assert seeded.execute("SELECT count(*) FROM items").fetchone()[0] == 1
    # ④ 报告类失败要**响**（计划 §8.5）：它必须冒出去，不许被批次循环的
    #    `except Exception` 吞掉——吞掉的话整轮会带着被毒化的账目继续跑。
    assert raised is not None, "报进度失败必须冒出去"


def test_punct_tables_stay_identical():
    """⭐ 两张 `_PUNCT` 必须逐字一致——一致性只有注释在承重时不叫契约。

    它们必须相同的理由见 `refine.py` 里那段注释：`sanitize_for_llm` 把 `“”` 换成
    `「」` 送出去、模型照抄回来，而**源文里是 `“”`**；两侧字符集不一致就会
    一边剥一边不剥 ⇒ **丢来源或误归属**（实测 ~25/47,719）。
    ⇒ 日后扩大这个字符集，**必须两处同改，且必须重跑包含关系的测量**（见 refine.py 注释）。
    """
    from vigil import digest, refine
    assert refine._PUNCT.pattern == digest._PUNCT.pattern


# ── Task 1：prompt v3 的商业推广判据 ──────────────────────────────


def test_prompt_version_is_v3():
    """版本号必须跟着提示词一起走。

    ⚠️ 这个断言是**回归锁**，不是行为测试——它只证明"文案改了、版本也改了"。
    真正的行为测试在 M5 出口判据 2（5 条已知好条目重抽后必须仍在），
    以及 `tests/test_repass.py` 的误杀守卫。**别把它当成"规则生效了"的证据。**
    """
    assert refine.PROMPT_VERSION == "v3"


def test_system_prompt_discards_commercial_promo():
    """prompt 里必须有商业推广的丢弃规则，且必须写明「看目的不看词」。"""
    from vigil.categories import load_categories

    prompt = refine.build_system_prompt(load_categories())
    assert "商业推广" in prompt
    # 反例必须出现在 prompt 里：它们正是 D13 判据的由来（实测误杀样本）
    assert "打电话办卡的都别信" in prompt
    assert "最早9.5" in prompt


# ── Task 2：两道闸门接进 _to_item ─────────────────────────────────


def test_to_item_drops_place_without_evidence(msg_factory):
    """源文里没有地点 ⇒ place 降级为 None，**条目本身保留**（与 deadline 同一取舍）。"""
    batch = [
        msg_factory(
            1,
            "大概这周会有面试 到时候具体时间通知大家",
            uid="u_1",
        )
    ]
    it = refine._to_item(
        {"quote": "到时候具体时间通知大家", "kind": "notice",
         "title": "面试通知", "place": "立德楼1阶", "confidence": 0.9},
        batch,
        known_kinds=frozenset({"notice"}),
    )
    assert it is not None          # ⚠️ 条目必须还在
    assert it.place is None        # ⚠️ 只有 place 被降级


def test_to_item_keeps_place_with_evidence(msg_factory):
    batch = [msg_factory(1, "西太湖连隔板", uid="u_1")]
    it = refine._to_item(
        {"quote": "西太湖连隔板", "kind": "notice", "title": "澡堂隔板",
         "place": "西太湖校区", "confidence": 0.9},
        batch,
        known_kinds=frozenset({"notice"}),
    )
    assert it.place == "西太湖校区"


def test_to_item_drops_past_deadline(msg_factory):
    """item 83 的形状：死线早于消息日。"""
    # ⚠️ ts 是本机实算值（1785902400 = 2026-08-05 12:00 本地时，见报告「偏差」）
    batch = [msg_factory(1, "档案袋封口时间：5 月 6 日", ts=1785902400, uid="u_1")]
    it = refine._to_item(
        {"quote": "档案袋封口时间：5 月 6 日", "kind": "notice",
         "title": "档案袋封口", "deadline": "2026-05-06", "confidence": 0.9},
        batch,
        known_kinds=frozenset({"notice"}),
    )
    assert it is not None
    assert it.deadline_ts is None


def test_to_item_keeps_future_deadline(msg_factory):
    # ⚠️ ts 是本机实算值（1789531200 = 2026-09-16 12:00 本地时，见报告「偏差」）
    batch = [msg_factory(1, "9月20日前交表", ts=1789531200, uid="u_1")]
    it = refine._to_item(
        {"quote": "9月20日前交表", "kind": "notice", "title": "交表",
         "deadline": "2026-09-20", "confidence": 0.9},
        batch,
        known_kinds=frozenset({"notice"}),
    )
    assert it.deadline_ts is not None
