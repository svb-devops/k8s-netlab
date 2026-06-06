# 部署案例栏目 — 开发指南

**版本**: 1.0  
**日期**: 2026-06-06  
**状态**: 待实施

---

## 一、背景与目标

### 现状

K8S NetLab 目前有 11 个网络实验，侧重"理解原理"——每个实验验证一个独立概念（veth pair、iptables 规则、DNS 解析等），步骤碎片化。

### 新栏目定位

「部署案例」是独立的第二栏目，侧重"端到端实战"——部署一个完整的、真实的应用，有明确的完成态。

| 维度 | 网络实验 | 部署案例 |
|------|---------|---------|
| 目标 | 理解某个 K8s 网络概念的原理 | 端到端部署一个完整可用的应用 |
| 结构 | 碎片化步骤 + 原理验证 | 完整架构 → 部署 → 验证 → 扩展 |
| 完成态 | "你懂了 veth pair" | "你跑起来了一个留言板" |
| 对标 | K8s 官方 Concepts 文档 | K8s 官方 Tutorials 页面 |

---

## 二、案例规划

### 镜像约束

K3s VM 通过宿主机 registry mirror（`172.16.100.1:5000`）拉取镜像。只有 mirror 中存在的镜像才能稳定使用。

| 状态 | 镜像 | 说明 |
|------|------|------|
| 已在 mirror | `nginx`（all tags） | 直接可用 |
| 已在 mirror | `mysql:8.0` | 直接可用 |
| 已在 mirror | `busybox:1.28` | 直接可用 |
| 宿主机已有，需推送 | `redis:7-alpine` | D01 依赖，实施前推送 |

**推送命令**（实施 D01 前必须执行）：

```bash
docker tag redis:7-alpine 172.16.100.1:5000/library/redis:7-alpine
docker push 172.16.100.1:5000/library/redis:7-alpine
```

### 案例列表

| ID | 标题 | 时长 | 难度 | 镜像 | 优先级 |
|----|------|:----:|:----:|------|:------:|
| D01 | 留言板应用（Guestbook） | 30 min | ⭐⭐⭐ | nginx, redis:7-alpine | P1 |
| D02 | WordPress + MySQL | 45 min | ⭐⭐⭐⭐ | nginx, mysql:8.0 | P2 |
| D03 | 蓝绿部署与滚动更新 | 35 min | ⭐⭐⭐ | nginx:1.24, nginx:1.25 | P1 |
| D04 | CronJob 定时任务系统 | 30 min | ⭐⭐⭐ | busybox:1.28 | P2 |
| D05 | 多命名空间微服务隔离 | 40 min | ⭐⭐⭐⭐ | nginx, mysql:8.0 | P3 |

### 各案例架构说明

#### D01 — 留言板应用（Guestbook）

对标：[kubernetes.io guestbook 教程](https://kubernetes.io/docs/tutorials/stateless-application/guestbook/)

```
用户请求
  ↓
nginx 前端（3副本 Deployment）
  ↓ 写入
redis leader（1副本 Deployment）
  ↓ 同步
redis follower（2副本 Deployment）
```

核心技能：多副本 Deployment、ClusterIP Service、标签选择器、横向扩容、验证负载均衡

#### D02 — WordPress + MySQL

对标：[kubernetes.io WordPress 教程](https://kubernetes.io/docs/tutorials/stateful-application/mysql-wordpress-persistent-volume/)

```
Ingress
  ↓
WordPress Deployment（nginx 模拟，3副本）
  ↓
MySQL StatefulSet（1副本）+ PVC（数据持久化）

配置层：
  Secret     → MySQL root 密码
  ConfigMap  → 应用配置
```

核心技能：StatefulSet + PVC 组合、Secret 注入、kustomize 基础、数据持久化验证（删 Pod 数据不丢）

#### D03 — 蓝绿部署与滚动更新

```
# 初始状态
Service (selector: track=stable)
  → v1 Deployment（nginx:1.24，标签 track=stable）

# 切换后（仅修改 Service selector）
Service (selector: track=canary)
  → v2 Deployment（nginx:1.25，标签 track=canary）

# 滚动更新演示
kubectl set image deployment/app nginx=nginx:1.25
kubectl rollout history deployment/app
kubectl rollout undo deployment/app
```

核心技能：`maxSurge`/`maxUnavailable`、`rollout history`、一键回滚、蓝绿流量切换（只改 selector）

#### D04 — CronJob 定时任务系统

```
CronJob（*/1 * * * *）
  → Job（每分钟触发）
    → Pod（busybox，模拟数据库备份，写入 PVC）

并行 Job（completions=5, parallelism=3）
  → 5个工作器 Pod（busybox，模拟批量数据处理）
```

核心技能：Job/CronJob 生命周期、`completions`/`parallelism`、`concurrencyPolicy`、失败重试与 `backoffLimit`

#### D05 — 多命名空间微服务隔离

```
namespace: frontend
  → nginx Deployment（3副本）

namespace: backend
  → nginx Deployment（2副本，模拟 API 服务）

namespace: data
  → mysql StatefulSet

NetworkPolicy 规则：
  frontend → 只能访问 backend（8080 端口）
  backend  → 只能访问 data（3306 端口）
  data     → 拒绝所有 ingress（除 backend）
```

核心技能：Namespace 资源隔离、跨 namespace DNS（`<svc>.<ns>.svc.cluster.local`）、NetworkPolicy 跨 ns、ResourceQuota

---

## 三、技术架构变更

### 目录结构

```
docs/
├── experiments/          ← 现有，不动
│   ├── 01-*.md
│   └── ...
└── deployments/          ← 新建
    ├── README.md
    ├── D01-guestbook.md
    ├── D02-wordpress-mysql.md
    ├── D03-blue-green-deploy.md
    ├── D04-cronjob.md
    └── D05-multi-namespace.md

backend/
├── docs_routes.py        ← 现有，不动
└── deployments_routes.py ← 新建

frontend/js/
└── docs.js               ← 扩展 mode 支持

frontend/
└── index.html            ← 加 Tab 切换 UI
```

### 后端：新增 deployments_routes.py

完全对称 `docs_routes.py`，约 60 行。

```python
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pathlib import Path
from backend.auth_deps import get_current_user

router = APIRouter(prefix="/api/deployments", tags=["deployments"])

PROJECT_ROOT = Path(__file__).parent.parent
DEPLOYMENTS_DIR = PROJECT_ROOT / "docs" / "deployments"

DEPLOYMENT_CASES = [
    {
        "id": "D01",
        "filename": "D01-guestbook.md",
        "title": "留言板应用（Guestbook）",
        "difficulty": 3,
        "duration": "30 分钟",
        "phase": 1,
    },
    {
        "id": "D02",
        "filename": "D02-wordpress-mysql.md",
        "title": "WordPress + MySQL",
        "difficulty": 4,
        "duration": "45 分钟",
        "phase": 2,
    },
    {
        "id": "D03",
        "filename": "D03-blue-green-deploy.md",
        "title": "蓝绿部署与滚动更新",
        "difficulty": 3,
        "duration": "35 分钟",
        "phase": 1,
    },
    {
        "id": "D04",
        "filename": "D04-cronjob.md",
        "title": "CronJob 定时任务系统",
        "difficulty": 3,
        "duration": "30 分钟",
        "phase": 2,
    },
    {
        "id": "D05",
        "filename": "D05-multi-namespace.md",
        "title": "多命名空间微服务隔离",
        "difficulty": 4,
        "duration": "40 分钟",
        "phase": 3,
    },
]


@router.get("", summary="List all deployment cases")
async def list_deployments(_user=Depends(get_current_user)) -> JSONResponse:
    return JSONResponse({"deployments": DEPLOYMENT_CASES})


@router.get("/{case_id}", summary="Get deployment case content")
async def get_deployment(case_id: str, _user=Depends(get_current_user)) -> JSONResponse:
    case = next((c for c in DEPLOYMENT_CASES if c["id"] == case_id), None)
    if not case:
        return JSONResponse({"error": "Not found"}, status_code=404)

    path = DEPLOYMENTS_DIR / case["filename"]
    if not path.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)

    content = path.read_text(encoding="utf-8")
    return JSONResponse({
        "id": case_id,
        "title": case["title"],
        "content": content,
        "difficulty": case["difficulty"],
        "duration": case["duration"],
    })
```

**main.py 变更**（2 行）：

```python
from backend.deployments_routes import router as deployments_router
app.include_router(deployments_router)
```

### 前端：Tab 切换 UI

在实验学习台区域顶部加 Tab，点击切换数据源。

#### index.html 变更

在 `<span id="doc-loading-indicator">` 上方的工具栏区域，将现有导航栏扩展为：

```html
<!-- Tab 切换 -->
<div class="flex border-b border-gray-200 px-2 pt-1 gap-1">
    <button id="tab-experiments"
            class="tab-btn text-xs px-3 py-1.5 rounded-t font-medium border-b-2 border-k8s-blue text-k8s-blue bg-white">
        网络实验
    </button>
    <button id="tab-deployments"
            class="tab-btn text-xs px-3 py-1.5 rounded-t font-medium border-b-2 border-transparent text-gray-500 hover:text-gray-700">
        部署案例
    </button>
</div>

<!-- 现有 prev/select/next 行保持不变 -->
<div class="flex-shrink-0 flex items-center px-2 py-2 bg-gray-50 border-b border-gray-200 gap-1">
    <!-- ... 现有内容不变 ... -->
</div>
```

#### docs.js 变更

`ExperimentDocs` 类新增 `mode` 属性及切换方法：

```javascript
// 新增属性
this.mode = 'experiments';  // 'experiments' | 'deployments'

// 新增方法：切换模式
async switchMode(mode) {
    if (this.mode === mode) return;
    this.mode = mode;
    this.currentExpId = null;
    this.showPlaceholder();
    // 清空 select
    while (this.selectEl.options.length > 1) this.selectEl.remove(1);
    await this.loadExperimentList();
    this._updateNavButtons();
}

// 修改 loadExperimentList()：
async loadExperimentList() {
    const endpoint = this.mode === 'deployments'
        ? '/api/deployments'
        : '/api/experiments';
    const resp = await fetch(endpoint);
    const data = await resp.json();
    this.experiments = data.experiments || data.deployments || [];
    this.populateSelector();
}

// 修改 populateSelector()：label 差异化
populateSelector() {
    const prefix = this.mode === 'deployments' ? '案例' : '实验';
    this.experiments.forEach(exp => {
        const opt = document.createElement('option');
        opt.value = exp.id;
        const stars = '⭐'.repeat(exp.difficulty);
        opt.textContent = `${prefix} ${exp.id}: ${exp.title}  ${stars}`;
        this.selectEl.appendChild(opt);
    });
}

// 新增 Tab 事件绑定（在 bindEvents() 中追加）：
document.getElementById('tab-experiments')?.addEventListener('click', () => {
    this.switchMode('experiments');
    document.getElementById('tab-experiments').classList.add('border-k8s-blue', 'text-k8s-blue');
    document.getElementById('tab-experiments').classList.remove('border-transparent', 'text-gray-500');
    document.getElementById('tab-deployments').classList.remove('border-k8s-blue', 'text-k8s-blue');
    document.getElementById('tab-deployments').classList.add('border-transparent', 'text-gray-500');
});
document.getElementById('tab-deployments')?.addEventListener('click', () => {
    this.switchMode('deployments');
    document.getElementById('tab-deployments').classList.add('border-k8s-blue', 'text-k8s-blue');
    document.getElementById('tab-deployments').classList.remove('border-transparent', 'text-gray-500');
    document.getElementById('tab-experiments').classList.remove('border-k8s-blue', 'text-k8s-blue');
    document.getElementById('tab-experiments').classList.add('border-transparent', 'text-gray-500');
});
```

---

## 四、案例文档格式规范

每个案例 Markdown 文件遵循统一格式：

```markdown
# 案例 DXX: <标题>

## 📋 案例信息

- **难度**: ⭐⭐⭐ (中级)
- **时长**: XX 分钟
- **环境**: K3s 单节点集群
- **前置**: <前置条件>

## 🎯 你将完成什么

一段话描述完成后的状态（用户视角）。

## 📐 架构图

<ASCII 架构图>

## 🐳 使用的镜像

| 镜像 | 用途 |
|------|------|
| nginx | ... |

## ⚠️ 开始前

<环境检查命令>

---

## 第一步：<标题>

### 目标
<本步骤要达成的状态>

### 操作

```yaml
# YAML 清单（完整，可直接 kubectl apply）
```

```bash
kubectl apply -f -<<EOF
...
EOF
```

### 验证

```bash
<验证命令>
```

**预期输出**：

```
<预期输出>
```

---

## 第二步：...

（重复上述结构）

---

## 验证整体完成

```bash
<端到端验证命令序列>
```

## 清理

```bash
kubectl delete namespace <ns>
```

## 扩展练习

- 练习 1：...
- 练习 2：...
```

**关键规范**：
- 每步都有独立的"验证"小节，带预期输出——学生能自查
- YAML 清单必须完整可直接 apply，不依赖外部 URL
- 镜像只用 registry mirror 中存在的版本（见第二节镜像约束）
- 清理步骤放最后，通过删 namespace 一次清空，不留垃圾资源

---

## 五、测试要求

### 后端测试

新增 `tests/test_deployments_routes.py`，覆盖：

```python
# 必须覆盖的测试用例
- test_list_deployments_authenticated      # 正常返回 5 个案例
- test_list_deployments_unauthenticated    # 401
- test_get_deployment_case_D01             # 返回 content 字段非空
- test_get_deployment_case_not_found       # 404
- test_get_deployment_case_id_format       # D01 格式，非数字 ID
```

覆盖率要求：`deployments_routes.py` 100%（逻辑极简，无理由低于此）

### 前端测试

手动验证清单（代码合并前必须过）：

- [ ] 默认打开显示"网络实验" Tab 激活
- [ ] 点击"部署案例" Tab，select 内容切换为 5 个案例
- [ ] 切换回"网络实验" Tab，select 恢复为 11 个实验
- [ ] 两个 Tab 下的 prev/next 按钮、步骤导航均正常工作
- [ ] 刷新页面后默认回到"网络实验" Tab

### 案例文档验证

每个案例文档写完后，使用 `/validate-experiment` skill 验证：

```bash
# 在 VM 内完整执行一遍，确认：
# 1. 所有 kubectl apply 无报错
# 2. 所有"预期输出"与实际一致
# 3. 清理步骤执行后无残留资源
```

---

## 六、实施计划

### P1（本期，建议先做）

**里程碑 1：基础设施**
1. 推送 `redis:7-alpine` 到 registry mirror
2. 创建 `docs/deployments/` 目录和空的 `README.md`
3. 实现 `backend/deployments_routes.py`
4. 在 `main.py` 注册路由
5. 补 `tests/test_deployments_routes.py`，全量测试通过
6. 前端加 Tab 切换（此时"部署案例" Tab 显示空列表）

**里程碑 2：首批案例**
- D01：留言板（Guestbook）
- D03：蓝绿部署与滚动更新

完成里程碑 2 后，栏目即可上线。

### P2（下期）

- D02：WordPress + MySQL
- D04：CronJob 定时任务系统

### P3（长期）

- D05：多命名空间微服务隔离

---

## 七、变更影响分析

| 模块 | 变更类型 | 风险 |
|------|---------|------|
| `backend/deployments_routes.py` | 新增文件 | 无（完全新增，不碰现有路由） |
| `backend/main.py` | 新增 2 行 | 极低 |
| `frontend/js/docs.js` | 扩展现有类 | 低（mode 属性隔离，不改现有逻辑） |
| `frontend/index.html` | 新增 Tab UI | 低（独立 DOM 节点） |
| `docs/deployments/` | 新增目录 | 无 |
| 现有 11 个网络实验 | 不变 | 无 |

**变更分级**：B 类（新 endpoint + 前端新功能），需调用 safety-reviewer 审查。

---

## 八、快速参考

```bash
# 本地开发启动
source /root/k8s-netlab/venv/bin/activate
cd /root/k8s-netlab
uvicorn backend.main:app --reload --port 8000

# 验证新 API
curl -s -H "Authorization: Bearer <token>" http://localhost:8000/api/deployments | jq

# 运行测试
pytest tests/test_deployments_routes.py -v
pytest tests/ --cov=backend --cov-report=term-missing

# 推送 redis 到 mirror
docker tag redis:7-alpine 172.16.100.1:5000/library/redis:7-alpine
docker push 172.16.100.1:5000/library/redis:7-alpine
```
