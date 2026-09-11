# 错题集生成器 v2 · 前后端接口契约（冻结版 v1）

后端：FastAPI，默认监听 `127.0.0.1:<随机空闲端口>`，根路径 `/` 提供 `web/dist` 静态资源。
所有接口前缀 `/api`。请求/响应 JSON 字段名与 `app/models.py` 完全一致（snake_case）。

## 1. 基础

| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| GET | `/api/health` | - | `{ok:bool, version:str, engine:{pdfplumber:bool, rapidocr:bool, opencv:bool}}` |
| GET | `/api/settings` | - | `Settings` |
| PUT | `/api/settings` | `Settings` | `Settings` |
| POST | `/api/dialog/pick` | `PickRequest` | `{paths:[str]}` （服务端弹原生对话框；无 GUI 环境返回空数组） |
| POST | `/api/fs/open` | `{path:str}` | `{ok:bool}` （资源管理器中定位） |
| GET | `/api/media?path=<abs>` | - | 图片二进制（仅允许 settings 覆盖到的目录，防目录穿越） |

## 2. 试卷来源

| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| POST | `/api/source/inspect` | `{pdf:str}` | `SourceInfo` |

`SourceInfo.kind`：`digital`（全页有文字层）/ `scanned`（全页无文字层）/ `mixed`。
前端首页在选定 PDF 后立刻调用，展示「来源体检卡片」：页数、逐页文字层字符数、通道判定、表格数、图片数。

## 3. 题目识别（异步任务 + SSE）

| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| POST | `/api/jobs/detect` | `DetectRequest` | `{job_id:str}` |
| POST | `/api/jobs/generate` | `GenerateRequest` | `{job_id:str}` |
| POST | `/api/jobs/merge` | `MergeRequest` | `{job_id:str}` |
| GET | `/api/jobs/{job_id}` | - | `JobStatus` |
| POST | `/api/jobs/{job_id}/cancel` | - | `{ok:bool}` |
| GET | `/api/jobs/{job_id}/events` | - | `text/event-stream` |

### SSE 事件格式
```
event: log
data: {"ts":"12:03:41","level":"info","msg":"正在渲染试卷页面 ..."}

event: progress
data: {"stage":"ocr","done":3,"total":6,"percent":50,"msg":"OCR 第 3/6 页"}

event: result
data: { ...DetectPayload 或 GenerateResult 或 MergeResult... }

event: error
data: {"message":"...","traceback":"..."}

event: done
data: {"state":"done"|"error"|"cancelled"}
```
前端用 `EventSource` 订阅；**任务 id 只能订阅一次**，重连时先 `GET /api/jobs/{id}` 拿终态。

## 4. 题目配置

| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| POST | `/api/config/find` | `{pdf?:str, out_dir:str}` | `{found:bool, path:str, config:QuestionConfig}` |
| POST | `/api/config/save` | `{config:QuestionConfig, exam:str, out_dir:str}` | `{path:str, folder:str}` |
| POST | `/api/config/load` | `{path:str}` | `QuestionConfig` |

## 5. 配图与表格

| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| POST | `/api/images/list` | `{images_root:str, qno:int}` | `{files:[{name,path,url,size}]}` |
| POST | `/api/images/assign` | `{images_root:str, qno:int, paths:[str]}` | `{files:[...]}` （复制进 `图片/<题号>/`） |
| POST | `/api/images/delete` | `{images_root:str, qno:int, names:[str]}` | `{files:[...]}` |
| POST | `/api/images/autofill` | `{pdf:str, images_root:str, questions:[QuestionOut]}` | `{assigned:{qno:[...]}}` （电子版按图 bbox 自动归属并导出） |

## 6. 答题表

| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| POST | `/api/excel/peek` | `{path:str}` | `ExcelPeek` |

## 7. 关键交互约定

1. **核对页保存**：前端把用户确认后的 `QuestionOut[]` 放进 `GenerateRequest.questions` 直接生成，
   后端同时把它落盘为 `题目配置.json`（含 `schema_version:2`、`figures`、`tables`）。
2. **来源标注**：每题 `source` ∈ `text|ocr|config|mixed`，前端显示为徽标（文字层=绿 / OCR=橙 / 配置=蓝 / 混合=紫）。
3. **告警**：`warnings[]` 非空或 `dropped[]` 非空的题目，卡片默认展开并高亮。
4. **缺口**：`DetectPayload.gaps` 在核对页顶部以横幅提示：「第 8 题未识别到」。
5. **图片访问**：所有配图经 `/api/media?path=` 读取，前端不直接拼文件路径。
