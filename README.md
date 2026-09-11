# 学生错题集生成器 v2

选择「试卷 PDF」与「答题情况 Excel」，自动识别**选择题**题干与选项，为每位学生生成
`错题集_学生姓名.docx` 并归档到 `错题集/[班级]/[日期]-[试卷名]/`。

v2 是完整重写：**双通道 PDF 解析引擎 + Vue3 界面**，修复了旧版一批会产出错误内容的缺陷。

> 详细使用说明见 [`使用说明.md`](使用说明.md)，架构方案见 [`docs/PLAN.md`](docs/PLAN.md)，接口契约见 [`docs/API.md`](docs/API.md)。

---

## 核心特性

- **双通道 PDF 解析**：自动探测文字层，电子版走 pdfplumber（16 题约 1 秒、零 OCR 错字），
  扫描版走 pypdfium2 渲染 + RapidOCR，混合卷按页分流。
- **表格识别**：电子版直接取单元格结构；扫描版用 OpenCV 线检测识别框线。
- **配图自动抽取**：按题目纵向区间把插图自动归属到题并导出。
- **核对向导界面**：逐题显示题干/选项、来源标注、置信度、缺口告警；每题核对后才可生成。
- **多文件夹合并**：按班级分组合并，同名学生的多份文档合并、编号自动续接。

## 快速开始

```bash
pip install -r requirements.txt
python -m app.launcher              # 启动本地服务并自动打开界面
python -m app.launcher --no-window  # 仅启动服务
```

前端在 `web/`，如需改动界面：

```bash
cd web
npm install
npm run build     # 产物输出到 web/dist，由后端直接托管
```

Windows 用户也可直接双击 `启动.bat`（首次会自动安装依赖）。

## 目录结构

```
app/         后端：FastAPI 服务、双通道解析引擎、Word 生成与归档
  core/      引擎层（pdf_router / digital / scanned / tables / figures / docx_build ...）
web/         Vue3 + Vite + TypeScript + Pinia 前端
tests/       回归测试与快照（tests/regression.py）
legacy/      旧版单文件实现（tkinter + OCR），仅作参考归档
docs/        架构方案与接口契约
```

## 回归测试

```bash
python tests/regression.py            # 与快照对比（缺快照则生成）
python tests/regression.py --update   # 用当前结果重写快照
```

> 注意：回归测试需要自备测试用试卷 PDF（`选择题训练-1.pdf`、`选择题训练-2.pdf`、
> `贵阳市2026届高三年级摸底考试试卷+生物.pdf`）。出于版权与体积考虑，这些 PDF
> **未纳入版本库**，需自行放入仓库根目录后再运行。

## 数据与隐私说明

本仓库**只包含工程源码**，以下内容已通过 [`.gitignore`](.gitignore) 排除，不会上传：

| 类别 | 说明 |
|---|---|
| 密钥凭据 | `.env`、`*.key`、`*.pem`、`*secret*.json`、`api_key*` 等 |
| 学生隐私 | `错题集/`（含真实姓名的 docx）、`*.xlsx` 答题表、`*.docx` |
| 试卷素材 | `*.pdf` 等大文件 |
| 打包产物 | `build/`（约 990MB）、`dist/`（约 484MB） |
| 本地配置 | `settings.json`（含机器绝对路径） |
| 缓存与 IDE | `.cache/`、`.idea/`、`__pycache__/`、`node_modules/` |

本项目 OCR 全部在本地完成（RapidOCR / ONNX Runtime），**不需要任何云端 API Key**。
若后续接入在线模型，请把密钥写入 `.env`（已被忽略）并参考 `.env.example` 的方式提供模板。

## 许可证

未指定。如需开源请自行补充 LICENSE。
