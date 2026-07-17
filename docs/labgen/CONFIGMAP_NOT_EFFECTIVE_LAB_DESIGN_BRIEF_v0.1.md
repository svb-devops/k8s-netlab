# Lab Design Contract — ConfigMap 修改后不生效 v0.1

## 元信息

- Sprint: Second Wave Sprint #1 — CEO/CTO 决策后的 Second Wave 第一个主题
- 生成路径：Admin 人工 curated（`LABGEN_LLM_PROVIDER_MODE=fake_only`，无真实 LLM 凭证）——通过 `article-drafts`/`generate-lab` API 拿 stub 骨架后人工编写真实内容并 PATCH 替换，路径与 First Wave 三个 lab 一致
- target_domain: `k8s`
- runtime: `dedicated_vm`（VM 401，复用现有 K3s 单命名空间实验模型）

## 范围约束（本 sprint 明确不做）

- 只做单命名空间 / single runtime 实验
- 不涉及多 VM
- 不涉及 DNS 服务发现或 Pod Pending（Second Wave 后续主题）
- 不面向真实学生开放（`LABGEN_ENABLED_LAB_IDS`/`LABGEN_AUTO_VM_PROVISION_LAB_IDS` 保持不变）
- 不发布 Directus article
- 不覆盖卷挂载（volume mount）ConfigMap 的更新行为——只做 env 注入这一种最常见、行为最确定的路径，卷挂载的周期性同步机制留给文章一句话延伸提示
- 不使用 `kubectl edit`（无 TTY 沙箱里必然失败）、不使用 `kubectl exec`（学员和 verifier 都被 RBAC/`kubectl_executor` 禁止）

## 核心设计约束：为什么不能直接验证"Pod 里的环境变量值"

这是本 sprint 调研阶段发现的真实工程冲突，必须在这里诚实记录，而不是在实现时才发现：

`kubectl_executor.py` 的 `_BLOCKED_SUBCOMMANDS` 禁止 `exec`——这意味着无论是学员本人还是 verifier，都**无法**在这个沙箱环境里真正进入运行中的容器读取 `printenv` 的实际输出。而 K8s API 层面，Pod 的 `spec.containers[].envFrom`/`env[].valueFrom.configMapKeyRef` 存储的**始终是对 ConfigMap key 的引用**，不是 kubelet 在容器创建时解析出的字面值——查 Pod 对象本身，在 ConfigMap 更新前后看到的都是同一个引用文本，无法借此判断"这个 Pod 当前进程里的值是 old 还是 new"。

因此本 lab **不**验证"Pod 进程里的字面环境变量值"，而是验证一个逻辑等价、且 100% 可通过 K8s API 机器化确认的替代断言：**这个 Deployment 自创建以来是否发生过一次 rollout restart**。K8s 语义上，只修改 ConfigMap 的 `data` 字段完全不会触碰 Deployment 的 `spec.template`（env 的引用文本不变），因此不会触发新的 ReplicaSet/Pod；只有 `kubectl rollout restart` 才会在 `spec.template.metadata.annotations` 写入 `kubectl.kubernetes.io/restartedAt`，进而产生新的 Pod。已在 VM 401 真实 K3s 集群上做过实测验证（见下方"实测验证记录"）：ConfigMap patch 前后这个 annotation 均不存在，只有 rollout restart 才会让它出现——这个信号和"Pod 是否已经用新配置重新创建过"是完全等价的机器可验证事实，不是近似或降级方案。

### 实测验证记录（VM 401，2026-07-17）

```
初始 annotations（创建 Deployment 后）: None
patch configmap 后 annotations:        None      ← 未触发任何重启
rollout restart 后 annotations:        {'kubectl.kubernetes.io/restartedAt': '2026-07-17T12:26:38-07:00'}
```

## 新增 verifier（本 sprint 交付，见「资产沉淀」章节）

- `configmap_value_equals(namespace, name, config_key, expected_value)` — 直接读 ConfigMap `.data[key]`，验证"配置对象本身已经更新"
- `deployment_restart_not_triggered(namespace, name)` — 验证"这个 Deployment 存在，且尚未发生过 rollout restart"（配合 configmap_value_equals 一起用，构成"配置已改但还没重启"这一关键教学状态的机器化证据）
- `deployment_restart_triggered(namespace, name)` — 验证"这个 Deployment 已经发生过 rollout restart"

三者均只读 ConfigMap/Deployment 对象本身（`list_namespaced_config_map`/`list_namespaced_deployment`，复用已授予的 RBAC），不需要 exec，不需要新增学员权限。

## 学习目标

学生能够：
1. 理解 K8s env 注入（`envFrom`/`valueFrom.configMapKeyRef`）只在容器创建时解析一次，ConfigMap 更新后不会自动传播到运行中的容器
2. 识别"没有报错、Pod 依然 Ready，但行为不符合预期"这一类故障的判断起点：检查引用的配置对象是否在容器创建之后才被修改，而不是去看 Pod/Service 状态
3. 用 `kubectl describe configmap` 确认配置对象本身已更新（而不是用被沙箱禁止的 `-o jsonpath`）
4. 用 `kubectl rollout restart deployment/<name>` 非交互式触发新 Pod 创建，理解这是生产环境让"仅改了引用配置、未改 Pod 模板本身"的 Deployment 应用新配置的标准做法
5. 理解生产环境中这类变更通常经 Deployment YAML / Helm / GitOps 触发正式 rollout，而不是手工 patch ConfigMap 后手工 restart——本 lab 的手工步骤是教学简化，不是生产操作指导

## 步骤设计（8 步）

| Step | 动作 | 命令类型 | verify |
|------|------|---------|--------|
| 1 | 创建 ConfigMap `app-config`（`APP_MODE=old`） | `kubectl create configmap` | `configmap_exists` |
| 2 | 创建 Deployment `demo`，通过 `envFrom.configMapRef` 注入 `app-config` | `kubectl create deployment` + `kubectl set env --from` | `deployment_ready` |
| 3 | 观察基线：`kubectl describe configmap app-config` 确认当前值为 `old`；此时尚未发生任何 restart | 只读观察 | `deployment_restart_not_triggered` |
| 4 | 修改配置：`kubectl patch configmap app-config --type merge -p '{"data":{"APP_MODE":"new"}}'` | 非交互式 patch，无 exec/edit | `configmap_value_equals`（`config_key=APP_MODE`, `expected_value=new`） |
| 5 | **核心观察点**：ConfigMap 已经是 `new`，但 Deployment 仍未发生 restart——引导学生意识到"配置对象更新"与"运行中容器已应用新配置"是两件独立的事 | 只读观察，无新 kubectl 命令（复用 Step 3/4 的输出对比） | `deployment_restart_not_triggered`（再次确认——证明仅 patch configmap 不会自动触发重启） |
| 6 | 修复：`kubectl rollout restart deployment/demo` | 非交互式，无 patch/edit | `deployment_restart_triggered` |
| 7 | 确认修复：`kubectl rollout status deployment/demo` + `kubectl get pods` 确认新 Pod 已产生且 Ready | 只读观察 | `deployment_ready` |
| 8 | 清理：`kubectl delete deployment demo && kubectl delete configmap app-config` | 清理 | 无（命名空间由系统回收，同 First Wave 模式） |

## 为什么用"env 注入 + rollout restart"而不是别的修复路径

- **可复现、无副作用**：纯本地集群状态变更，不依赖外部 registry/网络条件（与 ImagePullBackOff 那种需要真实 404 的设计不同，这里教学重点是"配置生效时机"而非"错误信息读取"）
- **修复路径是生产环境的真实标准动作**：`kubectl rollout restart` 是 K8s 官方推荐的、非破坏性的强制刷新手段，学生学到的是可以直接用在真实工作里的操作
- **verify 密度与 First Wave 持平**：8 个 step 里 6 个有机器化 verify（Step 1/2/4/5/6/7），Step 3 是纯观察基线（无需要验证的新状态，`describe configmap` 本身就是确认动作），Step 8 是清理

## Known Gap（诚实记录，不假装已解决）

- 不覆盖卷挂载 ConfigMap 的行为对比（有周期性同步，行为与 env 注入完全不同）——本 sprint 判断"引入第二种资源引用方式 + 对比两种机制"会让单个 lab 的认知负载过重，留给未来 Second Wave 后续主题或直接作为文章的一句话延伸提示
- 无法验证"运行中容器进程里的字面环境变量值"（见上方"核心设计约束"），只能验证"是否发生过 rollout restart"这一逻辑等价信号——这是 exec 被禁用后的架构性限制，不是本 lab 特有的妥协，未来任何需要"确认容器内实际状态"的 lab 主题都会撞到同一个边界，值得记入 Second Wave 的架构风险清单

## Cleanup Contract

`cleanup.namespace_cleanup.type = delete_namespace`，命名空间由 `complete_session()`/rehearsal complete 路径回收，与 First Wave 完全一致模式，不引入新的清理逻辑。

## Publish Contract

- 内部发布：若 rehearsal + smoke 通过，`publish_status` 保持内部可见状态（不写入 `LABGEN_ENABLED_LAB_IDS`），真实学生仍然 403
- 不创建 Directus article 记录，不打开任何公开 CTA
- `image_resolution`：Step 2 使用的镜像与 First Wave 一致（内部 registry 已知可用镜像），按已有先例正常注册进 `image_resolution`（与 ImagePullBackOff 的"故意不可解析"场景不同，这里没有需要豁免的理由）
