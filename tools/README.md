# 数据备份与同步工具

> 目标：无论网站（服务器）是否到期、是否还能访问，本机始终有一份可恢复的最新数据。

## 脚本一览

| 文件 | 在哪运行 | 作用 |
| --- | --- | --- |
| `backup_local.py` | 本机 | 本机数据库每日备份（现在就能用） |
| `sync_server.py` | 本机 | 从生产服务器拉取数据到本机（服务器上线后用） |
| `backup_now.sh` | 服务器 | 服务器端一致性快照，由 `sync_server.py` 通过 ssh 调用 |
| `db_tool.py` | 本机 | SQLite 备份/校验辅助（被上面脚本调用） |
| `restart.ps1` | 本机 | 干净重启本地服务（`-Check` 只体检） |
| `verify_training.py` | 本机 | 训练链路验证（评分下发 / 会不会提前结束） |

## 一、本机每日备份（立即可用）

```powershell
C:\Python311\python.exe D:\projects\Jin-Gui\tools\backup_local.py
```

产物：

```
D:\projects\Jin-Gui\backups\local\
    tcm-YYYYMMDD-HHmmss.db   每次一份，默认保留 90 份
    tcm-latest.db            最新副本，恢复时优先用它
    backup.log               执行日志
```

注册成每天 03:00 自动执行：

```powershell
schtasks /Create /TN "JinGui-LocalBackup" ^
  /TR "\"C:\Python311\python.exe\" \"D:\projects\Jin-Gui\tools\backup_local.py\"" ^
  /SC DAILY /ST 03:00 /F
```

## 二、从服务器同步（服务器上线后）

### 前提：配好 SSH 密钥免密

脚本用 `BatchMode=yes`，不会交互输密码。先做一次：

```powershell
ssh-keygen -t ed25519 -C "jingui-backup"
# 一路回车，然后把公钥放到服务器
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@你的服务器IP "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

验证：

```powershell
ssh root@你的服务器IP "echo ok"
```

### 把服务器端脚本部署上去

`backup_now.sh` 必须存在于服务器（部署时随代码一起上传）：

```bash
/root/JinGui/tools/backup_now.sh
```

### 定时拉取

```powershell
C:\Python311\python.exe D:\projects\Jin-Gui\tools\sync_server.py --server root@你的服务器IP
```

注册成每天 03:30 执行：

```powershell
schtasks /Create /TN "JinGui-ServerSync" ^
  /TR "\"C:\Python311\python.exe\" \"D:\projects\Jin-Gui\tools\sync_server.py\" --server root@你的服务器IP" ^
  /SC DAILY /ST 03:30 /F
```

产物：

```
D:\projects\Jin-Gui\backups\server\
    recent\   tcm-*.db + uploads-*    最近 14 份
    daily\    tcm-YYYYMMDD.db         每天一份，保留 180 天
    sync.log  执行日志
```

## 三、恢复

### 用服务器备份恢复到本机

```powershell
# 1. 停服务
taskkill /IM python.exe /F

# 2. 备份当前库（防手滑）
Copy-Item D:\projects\Jin-Gui\backend\data\tcm.db D:\projects\Jin-Gui\backend\data\tcm.before-restore.db

# 3. 用最新备份覆盖
Copy-Item D:\projects\Jin-Gui\backups\server\recent\tcm-最新一份.db D:\projects\Jin-Gui\backend\data\tcm.db -Force

# 4. 启动服务
cd /d D:\projects\Jin-Gui\backend
C:\Python311\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

恢复后验证：

```powershell
C:\Python311\python.exe D:\projects\Jin-Gui\tools\db_tool.py check D:\projects\Jin-Gui\backend\data\tcm.db
```

输出 `ok texts=... cases=... sessions=...` 即为正常。

### 恢复到服务器

见 `SERVER_DEPLOY_GUIDE.md`，注意生产库路径是 `/var/lib/jingui/tcm.db`，**不要**恢复到 Git 仓库里的 `backend/data/tcm.db`。

## 四、本地开发服务重启

Windows 上重启服务有个坑：旧的 uvicorn 进程（尤其是 `--reload` 留下的子 worker）没清干净时会继续占着 8000 端口，
新进程绑定失败即退出，而旧进程照常响应请求 —— 表面上「重启成功」，页面跑的却是旧代码。

用这一条命令替代手动重启：

```powershell
powershell -ExecutionPolicy Bypass -File D:\projects\Jin-Gui\tools\restart.ps1
```

执行顺序：结束占用端口的进程和本项目 uvicorn（连同进程树；`--reload` 父进程会重启子进程，所以循环复查直到干净）
→ 等端口真正释放 → 启动新进程 → 轮询 `/ready` → 校验新进程启动时间晚于最新 `.py` 修改。
任一步失败就停下并打印日志尾部，不会带着脏状态硬启动。

| 参数 | 作用 |
| --- | --- |
| `-Check` | 只体检不重启：端口占用、进程信息、`/ready`、代码新鲜度 |
| `-Reload` | 启用热重载（默认关闭；Windows 下 `--reload` 会漏写文件，改完最好显式重启） |
| `-KillAllPython` | 连本机其他 `python.exe` 一起结束，仅在残留进程识别不出来时用 |
| `-Port 8000` | 换端口 |
| `-WaitSeconds 40` | 调整等待就绪的超时 |
| `-NoWait` | 启动后不等就绪就返回 |

双击运行用 `tools\restart.cmd`（失败时窗口会停住，方便看报错）。

> `restart.ps1` 必须保存为 **UTF-8 with BOM**。Windows PowerShell 5.1 会把无 BOM 的 UTF-8 当 GBK 读，
> 中文字符串被截断后会报「缺少字符串终止符」一类假语法错误。

## 五、训练链路验证

改完评分逻辑或对话流程后，用它确认整条链路没被弄坏。需要服务已在跑（先用 `restart.ps1`）。

```powershell
# 快速：起会话 → 直接补几条学生发言 → 评价 → 看要点得分
C:\Python311\python.exe D:\projects\Jin-Gui\tools\verify_training.py --case 12 --level 高级

# 重放：按固定发言逐轮走真实对话，检查会不会提前结束（较慢）
C:\Python311\python.exe D:\projects\Jin-Gui\tools\verify_training.py --mode replay --case 12
```

| 模式 | 做什么 | 耗时 |
| --- | --- | --- |
| `quick`（默认） | 直接往库里插学生发言再评价，不调对话模型 | 十来秒（含一次评价调用） |
| `replay` | 逐轮真实对话，每轮打印四阶段进度与会话状态 | 一分钟上下 |

参数：`--case` 病案 id、`--level` 难度、`--base-url` 服务地址、`--keep` 保留测试会话。
脚本默认会在结束时删掉自己造的会话（读 `backend/.env` 的 `ADMIN_PASSWORD` 做认证），
读不到密码就保留并打印会话 id。

退出码：`0` 正常、`1` 链路异常、`2` `replay` 中途被判定结束（这一项应视为缺陷）。

## 六、注意事项

- **不要等网站过期了再拉**：云服务器到期后磁盘通常只保留几天，之后直接释放。同步任务必须平时就在跑。
- 备份用 SQLite Online Backup API，服务运行中也能安全备份，不会拉到半个文件。
- 每次拉取后都做 `integrity_check`，损坏的备份会被拒绝入库。
- 本机 `backend/data/tcm.db` 与服务器数据是**两套**，恢复时想清楚用哪边覆盖哪边。
- `backups/` 目录不在 Git 里，也不会被 `git clean` 影响。
