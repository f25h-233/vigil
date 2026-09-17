"""配置包 —— M6 T7（spec §4.2 ① 的导入导出）。"""

from __future__ import annotations

import pathlib

import pytest

from vigil import categories, config, configpack, overrides


@pytest.fixture
def roots(tmp_path):
    """两个**互不相干**的数据根，用来验「另一个目录能导入并生效」（出口判据 4）。

    ⚠️ 每个根下都有自己的 `config/` 与 `data/`，并且**都不碰真仓库**。
    """
    class Roots:
        def __init__(self, base: pathlib.Path):
            self.base = base
            self.config_dir = base / "config"
            self.config_dir.mkdir(parents=True)
            self.qq = base / "qqdb"
            self.qq.mkdir()
            self.groups = self.config_dir / "groups.toml"
            self.cats = self.config_dir / "categories.toml"
            self.persons = self.config_dir / "persons.toml"

        def make_config(self, groups):
            return config.Config(
                qq_db_dir=self.qq,
                output_db=self.base / "data" / "vigil.db",
                groups=tuple(groups),
            )

    a = Roots(tmp_path / "A")
    b = Roots(tmp_path / "B")
    return a, b


def _seed(root):
    config.save_config(
        root.make_config([
            config.Group(id=111, name="甲群", tier="high"),
            config.Group(id=222, name="乙群", enabled=False),
        ]),
        root.groups,
    )
    categories.save_categories(
        (categories.Category(slug="notice", label="通知", desc="正式通知", icon="📋"),),
        root.cats,
    )
    config.save_persons(
        (config.Person(uin=100000001, label="某辅导员"),), root.persons
    )


def _open_overlay():
    """可写的 overlay 连接（表先备好——`connect()` 自己不建表）。"""
    overrides.ensure_schema()
    return overrides.connect()


def test_export_then_import_into_another_root(roots):
    """⭐ **出口判据 4 的机械形式**。"""
    a, b = roots
    _seed(a)

    pack_path = a.base / "vigil-config.toml"
    configpack.write_pack(
        pack_path,
        config=config.load_config(a.groups),
        cats=categories.load_categories(a.cats),
        persons=config.load_persons(a.persons),
        aliases=(("life_old", "life"),),
    )

    parsed = configpack.parse(pack_path.read_text(encoding="utf-8"), pack_path)
    report = configpack.import_pack(
        parsed,
        keep_settings=False,
        paths=configpack.Paths(
            groups=b.groups, categories=b.cats, persons=b.persons
        ),
    )
    assert report.groups == 2
    assert report.categories == 1
    assert report.persons == 1
    assert report.aliases == 1

    # ⭐ "生效" = 用**新根**重新读一遍，拿到的就是包里的东西
    assert [g.id for g in config.load_config(b.groups).groups] == [111, 222]
    assert [c.slug for c in categories.load_categories(b.cats)] == ["notice"]
    assert [p.uin for p in config.load_persons(b.persons)] == [100000001]


def test_keep_settings_leaves_the_local_paths_alone(roots):
    """⭐ `--keep-settings` 不是可选糖：`qq_db_dir` 是**机器相关**的。

    ⚠️ 把别人的包原样导入，`load_config` 会报「QQ 数据库目录不存在」——
    响亮，但对用户毫无帮助（他想要的只是那几个群和类目）。
    """
    a, b = roots
    _seed(a)
    # B 根上先有一份自己的配置
    config.save_config(b.make_config([config.Group(id=999, name="本机群")]), b.groups)
    local_qq = config.load_config(b.groups).qq_db_dir

    pack_path = a.base / "pack.toml"
    configpack.write_pack(
        pack_path, config=config.load_config(a.groups),
        cats=categories.load_categories(a.cats),
        persons=config.load_persons(a.persons), aliases=(),
    )
    parsed = configpack.parse(pack_path.read_text(encoding="utf-8"), pack_path)
    report = configpack.import_pack(
        parsed, keep_settings=True,
        paths=configpack.Paths(groups=b.groups, categories=b.cats, persons=b.persons),
    )
    assert report.settings_skipped is True
    assert config.load_config(b.groups).qq_db_dir == local_qq, "本机路径不许被覆盖"
    assert [g.id for g in config.load_config(b.groups).groups] == [111, 222], (
        "群清单仍然来自包——keep-settings 只保留 [settings]"
    )


def test_the_pack_never_contains_a_secret(roots, monkeypatch):
    """⭐ **密钥永远不进配置文件**（spec §3.2）——本条检查的是**产物**。

    ⚠️ 判据是「产物里没有那些**值**」，而不是「代码里没写」。做法是把
    两个密钥塞进环境变量，再导出一次，断言它们的字面量不出现在包里。
    只 grep 字段名（`api_key`）是不够的：一个拼错的键名照样会漏。
    """
    a, _ = roots
    _seed(a)
    secret_db = "SUPER-SECRET-DB-KEY-1234567890"
    secret_llm = "sk-SUPER-SECRET-LLM-KEY"
    monkeypatch.setenv("VIGIL_DB_KEY", secret_db)
    monkeypatch.setenv("SILICONFLOW_API_KEY", secret_llm)

    text = configpack.build(
        config=config.load_config(a.groups),
        cats=categories.load_categories(a.cats),
        persons=config.load_persons(a.persons), aliases=(),
    )
    assert secret_db not in text
    assert secret_llm not in text
    assert "key" not in text.lower() or "密钥" in text, (
        "包里出现了 key 字样——先确认它不是任何一个密钥的值"
    )


def test_the_pack_has_exactly_the_six_expected_top_level_keys(roots):
    """⭐ 上面那条「包里没有密钥」**本身没有牙**（它今天不可能红：`build` 从不读环境）。

    ⇒ 有牙的形式是钉住**产物的顶层键集合**：多出一个 `[secrets]` / `[llm]`
    这类段（或某一段被写成了嵌套的子表）都会立刻红。这也正是本项目
    「一个说多了的理由比没有理由更糟」那条判据的机械面——
    一条永远为真的断言看起来像守卫，实际是装饰（勘误 E7 的形态 1）。

    ⚠️ 变异反证：在 `build` 里加一行 `lines += ["[secrets]", 'key = "x"', ""]`
    ⇒ 本条**必红**（顶层多出 `secrets`）。

    ⚠️ `tomllib` 判据是**顶层键**：`[settings]` 若被写成 `[groups.settings]`
    这类穿过数组的显式路径，顶层键会少一个 `settings` ⇒ 同样会红。
    """
    import tomllib

    a, _ = roots
    _seed(a)
    text = configpack.build(
        config=config.load_config(a.groups),
        cats=categories.load_categories(a.cats),
        persons=config.load_persons(a.persons),
        aliases=(("life_old", "life"),),
    )
    raw = tomllib.loads(text)
    assert set(raw) == {
        "schema", "settings", "groups", "categories", "persons", "kind_aliases"
    }, f"配置包的顶层键有意外的东西：{sorted(raw)}"


def test_a_pack_from_a_newer_schema_is_refused(roots):
    """版本闸：形状变了就必须**拒绝**，不许静默错读。"""
    a, _ = roots
    _seed(a)
    text = configpack.build(
        config=config.load_config(a.groups),
        cats=categories.load_categories(a.cats),
        persons=config.load_persons(a.persons), aliases=(),
    )
    bumped = text.replace(
        f"schema = {configpack.PACK_SCHEMA}", f"schema = {configpack.PACK_SCHEMA + 1}"
    )
    assert bumped != text, "包头部必须有一个可识别的 schema 行"
    with pytest.raises(config.ConfigError, match="版本"):
        configpack.parse(bumped, pathlib.Path("x.toml"))


def test_import_is_all_or_nothing(roots):
    """⭐ **导入是全有或全无**：校验不过 ⇒ 一个文件都不许被写。

    ⚠️ 不这么做的后果是**最坏的一种**：类目写进去了、群没写进去，
    而用户看到的是「导入失败」——他会以为什么什么都没发生，实际配置已经半新半旧。
    校验（`validate_config_raw` / `validate_categories`）在**任何写入之前**
    全部跑完，这一条才成立。
    """
    a, b = roots
    _seed(a)
    # 一份**类目合法、群非法**（零个群）的包
    bad = configpack.build(
        config=config.Config(
            qq_db_dir=a.qq, output_db=a.base / "data" / "vigil.db", groups=()
        ),
        cats=categories.load_categories(a.cats),
        persons=config.load_persons(a.persons), aliases=(),
    )
    with pytest.raises(config.ConfigError):
        configpack.parse(bad, pathlib.Path("bad.toml"))
    assert not b.cats.exists(), "解析失败时 b 根上不许有任何文件"
    assert not b.groups.exists()


def test_parse_refuses_a_malformed_external_pack_with_configerror(roots):
    """⭐ 形状错的外部输入必须是 `ConfigError`，**不是 `AttributeError`**。

    ⚠️ 这条钉的是 C6（T2 的 deferred，T7 之前收）：`configpack.parse` 消费
    `validate_config_raw`，而它接的是**用户拷来拷去的文件**。一份
    `groups = [1, 2]` 的包在修前会抛 `AttributeError` ⇒ 端点回 **500**、
    排障方向完全错（去看服务端，而真相是包写错了）。

    ⚠️ 变异反证：把 `config.validate_config_raw` 里那句
    `isinstance(entry, dict)` 的守卫删掉 ⇒ 本条**必红**（抛的是 `AttributeError`）。
    """
    a, _ = roots
    _seed(a)
    # ⚠️ `groups = [111, 222]` **必须写在 `[settings]` 之前**：TOML 里落在
    # `[settings]` 之后的裸键是 `settings.groups`（顶层根本没有 `groups`），
    # 那样探的是**另一条**分支（「段为空（根本没写）」），C6 的守卫压根不在路径上
    # ——那正是 E7 的形态 5「输入到不了被测分支」。
    broken = (
        "schema = 1\n"
        "groups = [111, 222]\n"
        "\n"
        "[settings]\n"
        f'qq_db_dir = "{a.qq.as_posix()}"\n'
        f'output_db = "{(a.base / "data" / "vigil.db").as_posix()}"\n'
        "\n"
        "[[categories]]\n"
        'slug = "notice"\n'
        'label = "通知"\n'
        'desc = "正式通知"\n'
    )
    with pytest.raises(config.ConfigError, match="键值表"):
        configpack.parse(broken, pathlib.Path("broken.toml"))


def test_import_prunes_an_alias_that_shadows_a_live_slug(roots):
    """⭐ 导入必须维持 T5 的别名不变量：表里**不许有 `old_kind ∈ 现存 slug` 的行**。

    场景是真实会发生的（不是构造出来的）：本机把 `life` 改名成 `life_v2`
    ⇒ 表里有 `life→life_v2`；然后导入一份**把 `life` 带回来**的包。
    不剪的话，`store._EFFECTIVE_KIND` 里那个无条件的
    `LEFT JOIN ov.kind_alias ka2 ON ka2.old_kind = ost.kind` 会把界面上
    手工选的**合法**类目 `life` 顶成 `life_v2`——正是 `prune_kind_aliases`
    docstring 里那个实测反例（spec §4.2 ④ 要禁的状态）。

    ⚠️ 标量断言（`"life" not in aliases`）**不够**：真正的不变量是
    「表里没有 old_kind ∈ 现存 slug 的行」，下面按它判。

    ⚠️ 变异反证：把 `import_pack` 里那次 `prune_kind_aliases` 调用删掉
    ⇒ 本条**必红**（`life→life_v2` 留在表里）。
    """
    a, b = roots
    _seed(a)
    # 本机（B）先欠着一条指向 life_v2 的别名
    ov = _open_overlay()
    try:
        overrides.set_kind_alias(ov, old_kind="life", new_kind="life_v2")
    finally:
        ov.close()

    pack = configpack.parse(
        configpack.build(
            config=config.load_config(a.groups),
            cats=(
                categories.Category(slug="life", label="生活", desc="生活"),
                categories.Category(slug="notice", label="通知", desc="正式通知"),
            ),
            persons=(),
            aliases=(("life", "life_v2"),),
        ),
        pathlib.Path("p.toml"),
    )
    report = configpack.import_pack(
        pack, keep_settings=False,
        paths=configpack.Paths(groups=b.groups, categories=b.cats, persons=b.persons),
    )
    assert report.aliases == 1, "包里的那条别名确实写进去了（剪枝发生在写入之后）"

    live = {c.slug for c in categories.load_categories(b.cats)}
    assert "life" in live, "包的类目确实生效了（否则下面的断言会因为别的原因通过）"
    ov = _open_overlay()
    try:
        aliases = overrides.kind_aliases(ov)
    finally:
        ov.close()
    assert not (set(aliases) & live), (
        f"别名表里有 old_kind ∈ 现存 slug 的行：{sorted(set(aliases) & live)}——"
        "`ka2` 会把用户手工选的合法类目顶掉"
    )
