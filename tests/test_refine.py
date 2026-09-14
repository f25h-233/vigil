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
