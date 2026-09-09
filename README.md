# AI 面试训练与表达分析系统

面向大学生求职训练的中文 AI 面试辅助系统。用户选择岗位并录制回答后，系统将从内容质量和表达流畅度两个方面给出可解释、可执行的训练反馈。

## 当前状态

阶段 2 已完成：项目已有可运行的 Vue 3 前端和 FastAPI 后端，可浏览软件开发岗及 15 道题库草案。录音、语音转写和表达分析将在阶段 3 接入。

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

## 项目环境

- 原有 `D:\python\python.exe`（Python 3.13）保持不变；
- 项目专用 Python 3.12 位于 `.tools/python312`；
- Python 依赖安装在项目专用 `.venv`；
- Node.js 与 npm 位于项目专用 `.tools`；
- `.tools`、`.venv` 和 `frontend/node_modules` 均不提交到 Git。

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
- [代码现状分析](代码现状分析.md)

## 数据说明

data/templates 保存空白模板；data/question_bank 保存 AI 生成的题库草案。真实录音、人工标注结果、个人信息和答辩样本不进入 Git 仓库。
