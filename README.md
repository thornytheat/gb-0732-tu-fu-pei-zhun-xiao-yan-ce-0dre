# 图幅配准校验册

县域测绘档案员用它核对历史图幅的像素点表、地面坐标册与独立拼缝见证表。册页汇总图幅配准、源行隔离、拼缝偏差与签审结果；导出的证据包可供下一班复核。

## 启动与验证

```bash
docker compose up --build
```

打开 `http://localhost:18421/`，选「河西四幅 · 外业原件」并点击「运行校验」。图幅索引可切换到单幅，拼缝索引可展开逐站偏差。左栏各章可预检样例，也可查看已运行批次的证据。保持参数不变，点击「重跑校验」复用同一批次。工具条提供打印册页与 JSON 证据下载。

```bash
docker compose exec -T app pytest -q
```

本地使用 Python 3.12 安装依赖并运行。

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
uvicorn app.main:app --port 18421
```

Compose 将批次与签审保存到 `register-data` 命名卷。需要空册时可通过 `REGISTER_DB_PATH` 指向一个新 SQLite 文件。本地默认文件是 `data/register.sqlite3`。

## 模块和入口

| 章节 | 入口 | 校验动作 |
|---|---|---|
| 点表收件 | `GET /api/intake` | 解码、识别空档和分段表头、保留物理行范围 |
| 坐标换算 | `GET /api/coordinates` | WGS84 与本地米／厘米换成 ENU 平面米 |
| 控制点配对 | `GET /api/pairing` | 点名归并、重测冲突隔离、像素与地面对表 |
| 仿射拟合 | `GET /api/affine` | 仿射最小二乘、秩检查、逐点初始残差 |
| 离群重估 | `GET /api/refit` | 阈值内多数点拟合、稳定复估、保留离群依据 |
| 接缝验核 | `GET /api/seams` | 复用筛查、证明覆盖与次序、贴边独立测距 |
| 图幅签审 | `POST /api/review/runs` | 原件勾稽、图边签审判定、批次留存 |

预检入口接收 `dataset=field` 或 `dataset=reference`，以及可选的 `control_limit_m`、`seam_limit_m`。运行接口接收同名 JSON 字段。`GET /api/review/runs/{run_id}` 回读，`POST /api/review/runs/{run_id}/signatures` 对可签图幅录名，`GET /api/review/runs/{run_id}/export` 下载一份证据。接口目录在 `/docs`。

## 基准对照裁定

左栏「基准对照裁定」在**外业原件**与**校准副本**之间逐幅裁定一册整幅沿用的基准，是下一班签审唯一认可的册页：

- 逐幅写清采用的基准与放弃另一版的原因。外业原件保留唯一一次现场修正，凡可拟合的图幅（河西、青石桥、柳湾）一律整幅沿用原件；只有原件模型不可用的双井 0432（共线退化）才整幅改用校准副本。全程禁止逐点拼合，避免两版来源混成一册。
- 拼缝仍用外业原件的独立尺量见证，逐站投影到各幅实际采用的模型上测距，给出每条拼缝的通过/超限结论。
- 裁定编号由两版共八份档件的字节摘要、拼缝阈值与规则版本决定。同一对照点「形成基准对照裁定」重跑只会回读旧册（`reused=true`），不新增裁定、已录签审不变；保存失败时单事务整笔回滚，上一册完整保留。
- 签审只认这份裁定：`POST /api/baseline/rulings/{ruling_id}/signatures` 仅接受裁定为可签的图幅，`GET /api/baseline/rulings/{ruling_id}` 回读，`GET /api/baseline/rulings/{ruling_id}/export` 导出证据。

默认原件包含一个高影响离群点、冲突重测及一幅共线退化图。河西和青石桥均可拟合，但两图之间的见证偏差超限；柳湾可以签审。校准副本的 48 个控制点采信、三条边通过，四幅均可签。

[字段、阈值与支持范围](docs/DATA-DICTIONARY.md) · [业务测试与陷阱](docs/DEPTH.md)
