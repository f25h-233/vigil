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
