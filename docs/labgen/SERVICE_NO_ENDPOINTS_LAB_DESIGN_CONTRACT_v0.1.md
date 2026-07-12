# Lab Design Contract — Service 无 Endpoints（selector/labels 不匹配）v0.1

## 元信息

- Sprint: Lab-to-Article Sprint Day 1 — 第二个 internal soft launch lab
- 生成路径：Admin 人工 curated（`LABGEN_LLM_PROVIDER_MODE=fake_only`，无真实 LLM 凭证，见 `docs/CEO_CTO_EXECUTION_RULES.md` 红线 1/2）——通过 `article-drafts`/`generate-lab` API 拿 stub 骨架后，由 Claude（本次执行者）人工编写真实内容并 PATCH 替换，路径与 lab #1（crashloopbackoff）一致
- target_domain: `k8s`
- runtime: `dedicated_vm`（复用现有 K3s 单命名空间实验模型，不涉及多 VM）

## 范围约束（本 sprint 明确不做）

- 只做单命名空间 / single runtime 实验
- 不涉及多 VM
- 不涉及 reader upload / URL scraping（内容为人工原创，非抓取自外部文章）
- 不做面向真实学生的 growth/expansion（`LABGEN_ENABLED_LAB_IDS` 保持不加入，仅 admin/owner 可见）
- 不重复 CrashLoopBackOff 主题

## 学习目标

学生能够：
1. 识别 Service 无法路由流量的症状（`kubectl get endpoints` 为空）
2. 用 `kubectl describe service` 找到 Service 的 selector
3. 用 `kubectl get pods --show-labels` 找到 Pod 实际标签
4. 对比两者，定位 selector 与 labels 不匹配的根因
5. 用 `kubectl delete` + `kubectl expose` 修复 Service（而非手动 patch selector——见下方 RBAC 设计说明）
6. 验证修复后 Endpoints 已填充

## 步骤设计（7 步，对齐 lab #1 的结构与 verify 密度）

| Step | 动作 | 命令类型 | verify |
|------|------|---------|--------|
| 1 | 创建 Deployment（app=web-backend，真实 label）+ `kubectl create service clusterip`（不指定 --selector，默认值 app=web-svc，自然不匹配） | `kubectl create deployment` + `kubectl create service` | `namespace_exists` |
| 2 | 观察 Service 无法访问：`kubectl get endpoints` | 只读观察 | `service_exists`（确认 Service 对象本身存在，Endpoints 内容为空这件事本身没有专门 verify 原语，见下方 Known Gap） |
| 3 | `kubectl describe service web-svc` 读出 selector（app=web-svc） | 只读观察 | `service_exists` |
| 4 | `kubectl get pods -l app=web-backend --show-labels` 读出 Pod 实际标签（app=web-backend） | 只读观察，用 label selector（符合 kubectl_executor 对 `-l` 的放行规则） | `pod_ready` |
| 5 | 修复：`kubectl delete service web-svc` + `kubectl expose deployment web-backend --port=80 --name=web-svc`（expose 自动从 Deployment 的真实 Pod 标签生成 selector） | 非交互式，无 patch | `service_exists` |
| 6 | 确认修复：`kubectl get endpoints` + `kubectl describe service` | 只读观察 | `service_exists` + `pod_ready` |
| 7 | 清理：`kubectl delete service web-svc`、`kubectl delete deployment web-backend` | 清理 | 无（命名空间由系统在完成实验后回收，同 lab #1 模式） |

### 为什么改用 delete+expose 而不是 patch（重要设计决策，非临时绕过）

最初设计用 `kubectl patch service --type=json` 修复 selector（与 lab #1 patch deployment 的风格一致）。为支持这个 lab，`LEARNER_ALLOWED_PERMISSIONS` 新增了 `services` 资源的 RBAC 权限，safety-reviewer 审出：K8s RBAC 无法按 `spec.type` 字段值做限制，一旦授予 `services` 的 `update`/`patch` verb，学员就能用 `kubectl patch service --type=merge -p='{"spec":{"type":"NodePort"}}'` 之类命令把 ClusterIP Service 升级成 NodePort/LoadBalancer（绑定集群所有节点的宿主机端口，绕过 namespace 隔离）。

尝试在 `kubectl_executor.py` 层用字符串解析拦截"patch 是否触碰了 type 字段"，五轮 safety-review 里每一版都被找到新的绕过（JSON Patch path 形式、YAML 无引号形式、转义引号、flag 值被误判为目标资源、逗号分隔多资源语法、`--request-timeout` 等未枚举的全局 flag、`kubectl replace -f <url>`、以及一个和本 lab 无关但同样严重的预置漏洞 `kubectl get --raw` 绕过 `-o yaml/json` 保护）。这是一场针对 kubectl/pflag 全部语法面做字符串枚举的军备竞赛，结构性地打不赢。

最终架构决策：**不在 `services` 上授予 `update`/`patch` verb**，把信任边界从"执行器能否解析出危险命令"移到"K8s API Server 本身是否接受该请求"——RBAC 层直接拒绝任何 patch/update/replace，无论 CLI 语法怎么变化都无法绕过。相应地，本 lab 的"修复"步骤改为 delete+expose，这不仅规避了整个问题，还是更好的教学设计：expose 自动从 Deployment 的真实标签生成 selector，天然不会打错字，比手动 patch 更贴近"正确的修复姿势"。

## Known Gap（诚实记录，不假装已解决）

`backend/labgen/models.py::VerifyType` 目前没有 `service_has_endpoints` 这个校验原语（只有 `SERVICE_EXISTS`，只检查 Service 对象存在，不检查 `.subsets` 是否非空）。这意味着"Endpoints 从空到非空"这个本 lab 的核心症状/修复结果，**无法被机器化 verify 直接断言**，只能作为学生的"observe"环节人工确认。

本 sprint 范围内不新增这个 verify 原语（属于范围外的 verifier 基础设施扩展，不是"单命名空间实验"范围内的工作）。这是一个真实的产品缺口，写入 `verifier_patterns` 资产（见 sprint log），建议下一个 sprint 作为独立 feature 补上，而不是本次为了凑 verify 覆盖率而伪造一个不准确的检查。

## Cleanup Contract

`cleanup.namespace_cleanup.type = delete_namespace`，命名空间由 `complete_session()`/rehearsal complete 路径回收，与 lab #1 完全一致模式，不引入新的清理逻辑。

## Publish Contract

- 内部发布：`publish_status = published`，但**不**写入 `LABGEN_ENABLED_LAB_IDS` 白名单 → 真实学生仍然 403（与当前 LabGen 锁定状态保持一致，见 `project_session_state.md` 里"LabGen 白名单扩容决策未决"— 本 sprint 不改变该决策）
- CTA：仅在内部/admin 可见的文章草稿上打开 `cta_enabled`，不面向公开 Directus 文章
