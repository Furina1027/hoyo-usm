# keys/ 数据来源与快照说明

本目录的 JSON 是**静态数据快照**，随本仓库一起版本管理。运行时只读这些本地文件，
不依赖 `hoyo-files` 或任何兄弟仓库（自包含要求，见 PLAN §3.2）。

## 快照信息

| 项 | 值 |
|---|---|
| 复制来源 | `E:\github\hoyo-files\pkg_version\usm\` |
| 快照日期 | 2026-11-21 |

## 文件清单与条目统计

| 文件 | 用途 | 条目数 | 构成 |
|---|---|---|---|
| `hk4e_keys.json` | 原神密钥（basename） | 360 | mask 344 / aes 16（全部带 audio） |
| `hk4e_history.json` | 原神版本历史 | 360 | 含 DELETED 81 |
| `hkrpg_keys.json` | 星铁密钥（basename） | 1263 | mask 812 / plain 313 / aes 138（带 audio 76，无 audio 62） |
| `hkrpg_history.json` | 星铁版本历史 | 1270 | 含 DELETED 36 |
| `hkrpg_keys_versions.json` | 星铁同名多版本归档 | 2 | CS_Chap03_Act320_f / _m（2.2.0 / 3.8.0 / 4.0.0 三版本异钥） |
| `nap_keys.json` | 绝区零密钥（basename） | 2808 | mask 2756 / plain 4 / aes 48（均无 audio 字段） |
| `nap_history.json` | 绝区零版本历史 | 2667 | 含 DELETED 495 |
| `nap_keys_by_path.json` | 绝区零路径覆盖表 | 50 | 键 = 相对 `StreamingAssets/Video/HD` 的路径（去 .usm）；同名异钥必用 |

## 条目形态（加载规格，见 hoyo_usm/keys.py）

- `"16位HEX"` 非全零 → `mask`（库值即成品 finalKey，直接参与掩码派生，不做二次派生）
- `"0000000000000000"` → `plain`（明文文件）
- `{"aes": "32位HEX", "audio": "16位HEX"?}` → `aes`（nap 条目无 audio 字段；audio 缺失或全零 = 该文件音轨按缺 key 处理）
- 非法/不完整条目在加载时丢弃并计入统计

## 刷新步骤（手动）

新版本游戏更新密钥库后：

1. 从 `E:\github\hoyo-files\pkg_version\usm\` 重新复制上表 8 个 JSON 覆盖本目录同名文件；
2. 更新本文件的快照日期与条目统计；
3. 运行 `hoyo-usm check` 核对条目数一致。

不做自动同步、不做网络下载——密钥采集属于兄弟仓/上游生态的职责，本项目只消费快照。
