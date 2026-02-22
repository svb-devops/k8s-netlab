# K8S NetLab - Kubernetes 网络实验平台

> **Security & Privacy Notice**
>
> This is an educational Kubernetes networking platform. Network diagrams
> and configuration examples may reference private IP addresses (RFC 1918).
> All sensitive credentials have been sanitized.
>
> Current codebase uses environment variables and placeholders for all
> sensitive data. Pre-commit security checks prevent future leaks.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)](https://www.python.org)
[![Platform](https://img.shields.io/badge/platform-linux-lightgrey.svg)](https://www.linux.org)
[![GitHub stars](https://img.shields.io/github/stars/svb-devops/k8s-netlab.svg)](https://github.com/svb-devops/k8s-netlab/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/svb-devops/k8s-netlab.svg)](https://github.com/svb-devops/k8s-netlab/network)


## 🎉 现在可以使用！

K8S NetLab v1.0 正式发布，最好用的 Kubernetes 网络实验平台。

---

## ✨ 核心特性

**11 个完整实验**
- ✅ 从基础到高级，循序渐进
- ✅ 7,400+ 行中文文档
- ✅ 100% 测试通过
- ✅ 实践导向，100% 可执行

**智能 Web 界面**
- ✅ 左右分栏（文档 + 终端并排）
- ✅ 步骤导航（一键跳转定位）
- ✅ 进度追踪（知道完成程度）
- ✅ 代码一键复制
- ✅ 响应式设计（支持移动端）

**即开即用**
- ✅ 一键创建 K8s 环境
- ✅ 无需本地安装
- ✅ 浏览器直接使用
- ✅ 30 分钟自动清理

---

## 🎯 适用人群

- Kubernetes 初学者
- 云原生工程师
- DevOps 工程师
- 网络工程师
- 想要实践学习的人

---

## 🔒 安全配置（部署前必读）

本项目使用环境变量管理所有敏感配置，**请勿硬编码密码**。

**配置步骤：**

```bash
# 1. 复制环境变量模板
cp .env.example .env

# 2. 编辑并填入真实配置
nano .env
```

关键配置项：
```env
PROXMOX_HOST=your-proxmox-ip
PROXMOX_USER=root@pam
PROXMOX_PASSWORD=your-strong-password
PROXMOX_NODE=pve
VM_SSH_PASSWORD=your-vm-template-password
```

> ⚠️ **安全提示**：`.env` 文件已在 `.gitignore` 中排除，永远不要将其提交到 Git。

详细部署说明见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

### Git 提交安全检查（强制）

本项目包含基础设施配置，**严禁**将以下信息提交到 Git：

- 密码、API 密钥、Token
- 真实 IP 地址（使用 `<HOST_IP>` 等占位符）
- `.env` 配置文件、私钥文件
- 网络拓扑细节（含真实地址）
- 用户数据文件

**安装自动检查 Hook（每次克隆后运行一次）：**

```bash
bash scripts/install-git-hooks.sh
```

安装后每次 `git commit` 前自动拦截敏感信息。手动检查：

```bash
bash scripts/pre-commit-security-check.sh
```

完整规范见 [docs/GIT-SECURITY-CHECKLIST.md](docs/GIT-SECURITY-CHECKLIST.md)（**所有贡献者必读**）

---

## 🚀 快速开始

1. 配置 `.env` 文件（见上方"安全配置"章节）
2. 启动服务：`python backend/main.py`
3. 访问平台：`http://your-server:8000`
4. 点击"创建实验环境"，等待 2-3 分钟
5. 看到终端 = 就绪 ✅

详见 [docs/QUICK-START.md](docs/QUICK-START.md)

---

## 📋 实验列表

**网络基础（实验 1-3）**

| 实验 | 标题 | 难度 | 时长 |
|------|------|------|------|
| 实验 1 | Kubernetes 网络基础 | ⭐⭐ | 30-35 分钟 |
| 实验 2 | Pod 网络深入探索 | ⭐⭐⭐ | 35-40 分钟 |
| 实验 3 | Service 负载均衡 | ⭐⭐⭐ | 35-40 分钟 |

**高级网络（实验 4-6）**

| 实验 | 标题 | 难度 | 时长 |
|------|------|------|------|
| 实验 4 | Ingress 控制器详解 | ⭐⭐⭐⭐ | 45-50 分钟 |
| 实验 5 | NetworkPolicy 网络策略 | ⭐⭐⭐ | 35-40 分钟 |
| 实验 6 | DNS 服务发现 | ⭐⭐⭐ | 35-40 分钟 |

**存储配置（实验 7-8）**

| 实验 | 标题 | 难度 | 时长 |
|------|------|------|------|
| 实验 7 | 持久化存储 PV/PVC | ⭐⭐⭐ | 40-45 分钟 |
| 实验 8 | ConfigMap 和 Secret | ⭐⭐⭐ | 35-40 分钟 |

**有状态应用（实验 9-10）**

| 实验 | 标题 | 难度 | 时长 |
|------|------|------|------|
| 实验 9 | StatefulSet 有状态应用 | ⭐⭐⭐⭐ | 45-50 分钟 |
| 实验 10 | 监控和日志管理 | ⭐⭐⭐ | 35-40 分钟 |

**综合实战（实验 11）**

| 实验 | 标题 | 难度 | 时长 |
|------|------|------|------|
| 实验 11 | 综合实战项目 | ⭐⭐⭐⭐ | 50-60 分钟 |

---

## 💡 使用技巧

**步骤导航**
- 点击顶部步骤按钮快速跳转
- 滚动时自动高亮当前位置
- 完成一步勾选复选框

**进度追踪**
- 顶部显示总体进度
- 刷新后进度自动保持
- 每个实验独立记录

**代码复制**
- 点击代码块右上角"复制"按钮
- 直接粘贴到终端执行

**移动端**
- 手机也能完整使用
- 文档在上，终端在下
- 随时随地学习

---

## 📖 学习建议

1. 按顺序学习（循序渐进）
2. 认真实践（亲手操作）
3. 完成扩展（深入理解）
4. 记录笔记（巩固知识）

---

## 📊 项目统计

| 项目 | 数值 |
|------|------|
| 实验数量 | 11 个 |
| 文档行数 | ~7,400 行 |
| 知识点数 | 100+ |
| 验证点数 | 60+ |
| 测试通过率 | 100% |

---

## 📩 问题反馈

遇到问题或有建议，欢迎反馈！

---

**开始你的 Kubernetes 学习之旅！** 🚀

---

---

<!-- DEVELOPER SECTION - For Claude Code and project contributors -->

## ⚠️ DEVELOPER NOTICE — Development Standards v2.0 (2026-02-20)

**Before starting ANY development work:**
- [ ] Read `k8s-netlab-development-SKILL.md` (full document, 1141 lines)
- [ ] Understand the 5 core principles (lines 800-850)
- [ ] Know when to stop and wait for information (lines 710-760)
- [ ] Apply confidence-level annotations to all analysis

See [QUICK-REFERENCE.md](QUICK-REFERENCE.md) for day-to-day lookup.

**Version:** MVP v1.0 | **Released:** 2026-02-20 | **Status:** ✅ Production Ready
