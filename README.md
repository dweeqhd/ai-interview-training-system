# AI 面试训练与表达分析系统

面向大学生求职训练的中文 AI 面试辅助系统。用户选择岗位并录制回答后，系统将从内容质量和表达流畅度两个方面给出可解释、可执行的训练反馈。

## 当前状态

阶段 4 已完成，阶段 5 已进入真实数据评测：网页可录音或上传音频（兼容未写入容器总时长的浏览器 WebM），在本机完成中文转写、字词时间戳停顿分析和离线内容评分；报告页支持人工修正转写并立即重新生成内容报告，同时保留模型原始转写。项目已提供可复现的标注质检与批量评测脚本，可对比 ASR、停顿、六维人工评分和内容证据。当前 `rules-v2-dev30-syn18` 只是在 30 条单标注员开发数据和 18 条 AI 合成控制样例上校准的开发版本；私人录音、标注原文及评测缓存仍只保存在本机忽略目录。

详细状态请先阅读：[代码现状分析.md](代码现状分析.md)。

## 本地启动

项目依赖均放在本项目目录中，不修改系统 Python 和系统 PATH。请分别打开两个 PowerShell 窗口：

```powershell
.\scripts\dev-backend.ps1
```

```powershell
.\scripts\dev-frontend.ps1
```

启动后访问：

- 前端：http://localhost:5173
- 后端接口文档：http://127.0.0.1:8000/docs
- 后端健康检查：http://127.0.0.1:8000/api/health

运行后端测试和前端构建检查：

```powershell
.\scripts\run-tests.ps1
```

对本地人工标注和原始录音运行阶段 5 评测：

```powershell
.\.venv\Scripts\python.exe .\scripts\evaluate-annotations.py <标注包目录> --audio-dir <录音目录>
```

脚本兼容 UTF-8 和 GB18030 CSV，自动跳过 macOS 资源副本并缓存语音分析结果。匿名汇总写入 `runtime/evaluation/latest/`；该目录、原始转写和音频均不提交到 Git。合成控制样例只用于检查规则误报、漏报和回归，不冒充第二名标注员，也不替代独立真人测试集。

## 项目环境

- 原有 `D:\python\python.exe`（Python 3.13）保持不变；
- 项目专用 Python 3.12 位于 `.tools/python312`；
- Python 依赖安装在项目专用 `.venv`；
- Node.js 与 npm 位于项目专用 `.tools`；
- FFmpeg 9.0.1 位于项目专用 `.tools`，不修改系统 PATH；
- PyTorch/torchaudio 2.11.0 CPU、FunASR 1.4.15 和 ModelScope 1.40.0 安装在 `.venv`；
- Paraformer、FSMN-VAD 和 CT-Punc 模型位于项目 `models`，约 2.04GB；
- `.tools`、`.venv`、`frontend/node_modules`、`models`、`runtime`、`uploads` 和私有音频目录均不提交到 Git。

检查阶段 3 环境：

```powershell
.\scripts\check-stage3-environment.ps1
```

在一台新电脑复现语音环境时，必须先取得项目负责人同意，再运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements-speech.txt
.\scripts\download-models.ps1
```

模型与指标的详细依据见：[阶段 3 语音处理与指标说明](docs/03-语音处理与指标说明.md)。

内容分析、评分公式与人工校准方法见：[阶段 4 内容分析与评分说明](docs/04-内容分析与评分说明.md)。

## MVP 范围

- 首发岗位：软件开发岗；
- 录音后分析，不做实时识别；
- 中文语音转写；
- 语速、停顿、语气词和回答时长分析；
- 题目相关性、STAR 结构和成果表达分析；
- 雷达图、停顿时间轴、改进建议；
- 历史训练对比。

## 明确不做

- 外貌、表情、性别、年龄、口音评分；
- 自动预测是否录用；
- 第一版数字人和实时双向语音；
- 从零训练语音识别模型。

## 文档入口

- [项目总计划](总计划.md)
- [AI 辅助与人工负责清单](AI辅助与人工负责清单.md)
- [MVP 需求与验收标准](docs/01-MVP需求与验收标准.md)
- [人工数据准备指南](docs/02-人工数据准备指南.md)
- [内容分析与评分说明](docs/04-内容分析与评分说明.md)
- [标注员填写包说明](outputs/annotation-kit-20260909/README.md)
- [代码现状分析](代码现状分析.md)

## 数据说明

data/templates 保存空白模板；data/question_bank 保存 AI 生成的题库草案。真实录音、人工标注结果、个人信息和答辩样本不进入 Git 仓库。
