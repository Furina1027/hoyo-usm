# hoyo-usm

[English](README.en.md) | 简体中文

对 **原神（gi）/ 星穹铁道（hsr）/ 绝区零（zzz）** 的过场动画（CRI USM 容器）进行
**无损解密并导出**的本地工具，提供图形界面（GUI）与命令行（CLI）两种使用方式。
只读取本机已有的游戏文件，完全离线运行。

## 便携版（推荐）

`release/hoyo-usm-gui-portable-<版本>.zip` 是免安装的绿色版（由 `python packaging/build_release.py` 打包，内含 ffmpeg 与密钥快照）：

1. 解压到任意目录，双击 `hoyo-usm-gui.exe` 即可使用
2. 配置与导出产物都写在程序目录的 `config/` 下；删掉整个文件夹即完全卸载
3. 需要 WebView2 运行时（Windows 11 自带，Windows 10 一般也已安装）
4. 可选参数：`--browser` 浏览器模式、`--port=8788` 指定端口、`--no-open` 仅启动服务不开窗口

## 它做什么

- 解析 USM 容器，支持两代加密（旧版反馈 XOR 掩码 / 新版 AES-128-CTR）
- 视频流**原样复制**（codec copy），不重新编码、不损画质
- 音频（HCA / ADX）解码为 PCM 后封装为 **FLAC / WAV / AAC**，也可按原始码流旁路
- 多语言音轨：四轨全出（带 language 标签）或单轨输出
- 容器 **MP4 / MKV / WebM**，可按编码自动选择或手动指定
- 导出后可选 ffmpeg 全量解码校验
- 批量导出：按版本新增/更新筛选、按文件名通配、多进程并行，输出导出报告
- 外部文件（不在游戏目录里的 .usm）按内容 md5 反查原始路径与密钥

## 安装

依赖 Python 3.11+；导出需要 numpy / pycryptodome / cricodecs / ffmpeg。

```bash
pip install -e .
pip install -e ".[gui]"        # GUI 可选组：fastapi / uvicorn / pywebview
```

## 使用

### CLI

```bash
hoyo-usm check                        # 环境、密钥库、游戏目录自检
hoyo-usm status --game zzz            # 本地文件 × 密钥覆盖率
hoyo-usm list --game gi --mode new    # 版本变更清单
hoyo-usm probe <file.usm>             # 只读解析：容器结构 / 加密形态 / 导出管线
hoyo-usm export --game zzz --audio none          # 按模式批量导出
hoyo-usm export --game gi "C:\path\xxx.usm" --audio all   # 直接指定文件（可省 --game）

# GUI（本地 Web 服务 + 原生窗口；--browser 回退浏览器模式）
hoyo-usm gui
```

`--game` 取值：`gi`（原神）/ `hsr`（星穹铁道）/ `zzz`（绝区零）。

### GUI

`hoyo-usm gui` 启动本地服务（仅绑定 127.0.0.1）并打开应用窗口：

- **首启向导**：自动检测游戏目录（注册表 + 盘符扫描），路径即时校验
- **总览**：各游戏本地文件数、体积、可解密比例（按加密类型分段）、最新版本新增数
- **游戏文件**：虚拟滚动大表，即时搜索、版本 / 加密类型筛选、列排序、
  Shift 连选与键盘浏览，右侧详情面板显示视频 / 音轨 / 密钥 / 导出方式
- **导出任务**：实时进度与剩余时间、任务排队、历史持久化（重启可查）、逐文件结果与播放定位
- **外部文件**：窗口内直接拖入文件或文件夹，自动识别游戏与密钥，多游戏自动分任务
- **设置**：游戏目录 / ffmpeg / 输出目录（原生浏览对话框 + 校验）、密钥库更新与回滚、
  深 / 浅 / 跟随系统主题


## 密钥

密钥快照随仓库打包在 `keys/`（来源与统计见 `keys/PROVENANCE.md`），运行时零外部依赖。
游戏更新后可在 GUI 设置中从更新源拉取最新快照（自动备份，可回滚）。

## 免责声明

仅供个人学习与观看，请勿传播导出内容；本项目与 miHoYo / HoYoverse 无任何关联。

## 许可

MIT
