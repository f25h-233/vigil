# 路线 C 环境落地记录

> 实测日期：2026-09-13 ｜ 全部结论均为本机实跑验证，非文档推测
> 承接 [`FEASIBILITY.md`](FEASIBILITY.md) §六（耗时估算）与 §七（密钥提取环节）

本文记录开工第一步的验证结果，以及**对 §六/§七 调研结论的两处修正**。

---

## 一、已验证通过（附证据）

| 环节 | 实测结果 | 证据 |
|---|---|---|
| qqcli-rs 二进制 | `qq 0.3.0` 可执行 | `qq --version` 输出，Release ZIP SHA256 校验 `OK` |
| `qq init` | **跑通**，自动发现账号与库 | 见下文 JSON |
| 账号发现 | `1307553675`（无需任何配置） | `qq --json init` |
| 库定位 | `...\1307553675\nt_qq\nt_db\nt_msg.db` | `qq --json init` |
| 库加密判定 | `decrypt_required`；头部为假头 `"SQLite header 3\0"`（真 SQLite 魔数是 `SQLite format 3`） | `qq doctor --json` + 十六进制实测 |
| 密钥提取脚本 | **静态分析通过**，成功解析出目标函数 RVA | 见下文 |
| Python 解密环境 | `sqlcipher3` 为真 SQLCipher `4.12.0 community` | `PRAGMA cipher_version` |

### `qq --json init` 原始输出

```json
{
  "status": "decrypt_setup_required",
  "db_path": "C:\\Users\\qwe13\\Documents\\Tencent Files\\1307553675\\nt_qq\\nt_db\\nt_msg.db",
  "account": "1307553675",
  "next_command": "qq doctor"
}
// EXIT=3
```

### 密钥提取脚本静态分析输出

脚本：`qq-win-db-key/scripts/windows/ntqq/windows_ntqq_get_key.ps1`（commit `b402e50`，2026-07-19）
命令：`powershell -File <脚本> -WrapperNodePath <wrapper.node> -NoDebugForKey`

```
目标字符串 RVA: 0x411C0CC
LEA 指令 RVA:  0x1DC4835
函数 RVA:      0x1DC4820
```

**本机 QQ 版本 `9.9.31-49738`**（对比：教程已确认版本 `9.9.32-51246`）。
脚本用字符串特征定位（而非硬编码字节签名），故跨小版本鲁棒——**静态部分已验证兼容**，
这正面反驳了 §六 风险清单第 2 条（"QQ 版本兼容性"）。

---

## 二、对调研结论的两处修正

### 修正 1：`sqlcipher.exe` 不需要了

qqcli-rs 的解密路径要求外部 `sqlcipher.exe`（源码里给的下载链接是坏的，默认路径
`~/Downloads/voile/sqlcipher.exe`）。但 §七 链上的 **`nt_msg_db_util` 自带 SQLCipher**：
其 `1.decrypt.py` 用 `sqlcipher3` Python 绑定，`uv sync` 即装好（有 Python 3.14 wheel，
无需编译器）。实测 `cipher_version = 4.12.0 community`。

→ **绕开 sqlcipher.exe 这个不确定前置件**，走官方文档《统一解密》的路线。

### 修正 2：`2.slim.py` 不是"按群号过滤"

§六 说"按群号过滤是最大提速杠杆，2.94 GiB → 几 MB"。赛前推测 `2.slim.py` 实现了它，
**读了源码后否定**：该脚本策略是"新建空加密库、逐表复制、**唯独 `group_msg_table` 整张表只建空表**"，
目的是**绕过源库损坏页**、服务备份场景——它丢弃的是全部群消息，而非筛选保留部分群。

→ 按群过滤这个杠杆**仍然要自己实现**（用 `sqlcipher3` 直接开加密库做过滤 CTAS）。
   未做，属于 VIGIL 待开发项。

---

## 三、环境改动（已执行）

| 改动 | 内容 | 可逆性 |
|---|---|---|
| junction | `C:\Users\qwe13\AppData\Local\qqcli` → `D:\qqcli-data` | 删 junction 即回退 |
| uv 环境 | `D:\github\nt_msg_db_util\.venv`（17 包，含 sqlcipher3 0.6.2） | 删目录即回退 |

**为什么建 junction**：qqcli 把解密库、DuckDB 索引、缓存三样全部硬编码在
`%LOCALAPPDATA%\qqcli\`（C 盘），而 C 盘实测仅剩 2.8 GB（99% 已用）。
一次性解密峰值约 5.9 GB（先写 `nt_msg_clean.db` 全量拷贝，再 `sqlcipher_export` 一份），
照原样必定爆盘。junction 一次解决三样产物。

---

## 四、本机工具链落位

| 工具 | 路径 | 说明 |
|---|---|---|
| qqcli | `D:\github\qqcli-rs`（源码）／`D:\github\VIGIL\.cache\qqcli\extract\...`（Release 二进制） | `qq` 命令 |
| qq-win-db-key | `D:\github\qq-win-db-key` | 密钥提取脚本 |
| nt_msg_db_util | `D:\github\nt_msg_db_util`（.venv 已就绪） | 解密/精简/导出 |
| QQDecrypt 文档 | `D:\github\QQDecrypt` | 官方教程库 |
| 本机 QQ | `D:\QQ`，版本 `9.9.31-49738` | `wrapper.node` 在 `versions\<ver>\resources\app\` |

---

## 五、待执行（需人工在场：要关 QQ 并重新登录）

1. **备份** `nt_db`（4.0 GB）→ `D:\qqbackup\nt_db_2026-09-13\`
   —— 必须在**关闭 QQ 之后**做，否则抄到不一致快照（`-wal`/`-shm` 正在写入）
2. **密钥提取**：跑 `windows_ntqq_get_key.ps1`（不带 `-NoDebugForKey`）
   —— 会以调试器启动 QQ 窗口，需在弹出窗口中登录；命中 `nt_sqlite3_key_v2` 断点后打印 16 字节 key
3. **解密**：key 填入 `.env` 的 `NTQQ_DB_KEY` → `uv run python 1.decrypt.py` → `nt_msg_plain.db`
4. **接回 qqcli**：`qq config set-db-path <nt_msg_plain.db>` → `qq index`
5. **验证**：`qq sessions` / `qq history <群号> --since` / `qq search "关键词"`

> ⚠️ 风险知情（§七 原文）：密钥提取属注入式操作，上游警告"可能破坏聊天记录或导致封号"。
> 故第 1 步备份是必需前置，不可跳过。
