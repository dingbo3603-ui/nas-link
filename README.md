# NAS Link

NAS Link 是为一台绿联 DX4600+、一台 MacBook 和两台 Windows 电脑设计的私人数据中枢。它把四类日常动作收进同一个桌面应用：

- Windows 与 macOS 之间同步文字剪贴板；
- 电脑之间通过 NAS 中转文件；
- 将任意文件丢进 NAS 收件箱，由规则与 DeepSeek 自动分类、打标签和生成摘要；
- 对电脑文件夹生成可恢复、内容去重的版本快照；
- 用自然语言检索真实文件，返回精确路径和下载入口。

## 当前版本

版本：`0.1.2 MVP`

当前已经实现服务器、Windows/macOS 共用桌面客户端和 Docker 部署配置。智能资料库支持点击批量选择，也支持从 Finder 或资源管理器直接拖入多个文件，上传后自动去重、分类和索引。MVP 支持文字剪贴板；图片与富文本剪贴板将在后续版本加入。

## 架构

```text
Windows 1 ─┐
Windows 2 ─┼─ NAS Link Desktop ──┐
MacBook  ──┘                      │
                                 ▼
                        NAS Link Server / Docker
                        ├─ SQLite 元数据索引
                        ├─ dropbox 智能收件箱
                        ├─ library 自动资料库
                        ├─ backups 去重快照
                        └─ DeepSeek API（可选）
```

## DX4600+ 部署

建议在绿联 Docker 的持久目录中创建 `nas-link` 文件夹，然后把本项目复制进去。不要把端口映射到公网路由器。

1. 复制环境变量模板：

   ```powershell
   Copy-Item .env.example .env
   ```

2. 生成长连接令牌：

   ```powershell
   .\scripts\new-token.ps1
   ```

   将输出填入 `.env` 的 `NAS_LINK_TOKEN`。三台电脑使用同一个连接令牌。

   自动部署脚本也可以在首次部署时生成令牌，并导出一个权限受限的客户端连接文件；桌面端设置页可以直接导入，无需手抄令牌。连接文件等同于访问凭据，配置完三台电脑后应移入加密存储或删除。

3. 如果使用 DeepSeek，在 NAS 的 `.env` 中填写 `DEEPSEEK_API_KEY`。密钥不要放进桌面安装包、源代码或聊天记录。默认配置：

   - `deepseek-flash`：批量分类、搜索词扩展；
   - `deepseek-v4-pro`：根据候选文件回答“文件在哪里”。

4. 构建并启动：

   ```powershell
   docker compose up -d --build
   docker compose ps
   ```

5. 从 Windows 检查服务：

   ```powershell
   Invoke-RestMethod http://192.168.31.35:8766/health
   ```

   `ok` 应为 `true`，`security_ready` 应为 `true`。DeepSeek没有配置时，`deepseek_configured` 为 `false`，本地分类和文件名检索仍然可用。

6. 在绿联文件服务中把项目的 `data/dropbox` 单独共享成“NAS Link 收件箱”。把资料复制进这个共享目录后，服务会等待文件大小稳定，再进行去重、提取和归档。

容器需要对 `./data` 目录有读写权限。如果健康检查正常但无法入库，先在绿联文件管理器中检查 Docker 容器对该目录的权限，不要通过放宽整个 NAS 的权限来解决。

## 桌面客户端

Windows 构建：

```powershell
Set-Location desktop
npm install
npm test
npm run dist:win
```

安装包生成在 `desktop/dist/`。

macOS 安装包必须在 MacBook 上构建：

```bash
cd desktop
npm install
npm test
npm run dist:mac
```

未签名的个人构建需要在 macOS 中手动确认首次打开。正式长期使用建议配置 Apple Developer 签名与公证。

第一次打开客户端后填写：

- NAS地址：`http://192.168.31.35:8766`（当前三台电脑所在网段的已验证地址）
- 连接令牌：与 NAS `.env` 中一致
- 本机名称：例如“办公室Windows”“设计Windows”“MacBook”

也可以在设置页选择“导入 NAS Link 连接文件”。

快捷键 `Ctrl/Command + Alt + C` 会把当前文字剪贴板发送到其他设备。自动模式会监听新的文字剪贴板；复制密码或验证码前可以临时切换为手动或关闭。

## 数据目录

```text
data/
├─ dropbox/             # 用户可以通过 SMB 一股脑放入的收件箱
├─ inbox/               # 正在处理或撤销归档后的文件
├─ library/             # 按 分类/子类/年/月 归档的资料
├─ review/duplicates/   # 已识别重复、等待人工确认的副本
├─ transfers/           # 设备间临时中转文件
├─ backups/blobs/       # SHA-256 内容去重数据块
├─ backups/manifests/   # 每次快照的可读清单
└─ index/               # SQLite 索引
```

自动整理不会覆盖同名文件。发生重名时会生成带序号的新文件；每次归档都记录原路径和新路径，可以从客户端撤销。重复文件不会静默删除，而是移动到人工确认区。

## 备份边界

- 备份任务默认忽略 `.git`、`node_modules`、虚拟环境和系统回收站等可重建缓存。
- 快照通过 SHA-256 内容指纹去重，旧快照不会因本地文件删除而立即消失。
- 首次部署后必须在客户端选一个测试文件夹，完成备份，再从快照中恢复一个文件并核对内容。
- NAS 本身仍然需要磁盘健康监控、独立快照或另一份离线备份。RAID 与同步都不能单独替代备份。
- 不建议把正在频繁写入的数据库、浏览器配置或项目构建目录直接放在 SMB 共享上运行；保留本地工作副本，由 NAS Link 做版本化备份。

## 安全边界

- 服务使用共享长令牌鉴权；不要开放到公网。
- WebSocket 只接受 `Authorization` 请求头中的令牌，不接受会进入访问日志的 URL 令牌；客户端每 20 秒执行一次心跳检查。
- DeepSeek密钥只存在 NAS `.env`，服务器不把密钥返回客户端。
- 默认会向 DeepSeek发送文件名、类型和最多一小段可提取文本。若只允许元数据，把 `NAS_LINK_DEEPSEEK_CONTENT_MODE` 改为 `metadata`。
- 如果家庭局域网中存在不可信设备，应在 NAS 反向代理中启用 HTTPS，并把客户端地址改为 HTTPS。
- 当前剪贴板历史在设定时间后清理；它不是密码管理器。

## 开发验证

服务器：

```powershell
Set-Location server
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest
```

桌面端：

```powershell
Set-Location desktop
npm test
node --check src\main.cjs
node --check src\preload.cjs
node --check src\renderer\app.js
```
