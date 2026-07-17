# Topic Brief — ConfigMap 修改后不生效 v0.1

## 状态

`documentation_only`。不改变 lab 发布状态，不改变 article_url/cta_enabled，不修改 `LABGEN_ENABLED_LAB_IDS`/`LABGEN_AUTO_VM_PROVISION_LAB_IDS`。

## 真实痛点

`kubectl edit configmap` 或 `kubectl patch configmap` 成功返回、`kubectl get configmap -o yaml` 也确认新值已经写入——但应用行为完全没变。这是 Second Wave 要覆盖的第一类"静态判断"故障（与 First Wave 三个"Pod 状态类"故障不同）：**没有任何报错、没有 CrashLoop、没有 Pending，一切看起来都"正常"，唯独不对**，这类故障对新手最难排查，因为习惯性的"看报错、看状态"路径在这里完全用不上。

根因是 Kubernetes 环境变量注入（`env.valueFrom.configMapKeyRef` / `envFrom.configMapRef`）只在 Pod（准确说是容器）**创建时**由 kubelet 解析一次，写死进容器的进程环境；ConfigMap 对象本身更新之后，已经在运行的容器不会重新读取——这是 K8s 的既有设计（相对的，卷挂载的 ConfigMap 有 kubelet 周期性同步机制，会在约一分钟内更新，但本实验不涉及 volume mount，只做 env 注入这一种，以保持单一变量）。必须显式触发一次新的 Pod 创建（最直接的方式是 `kubectl rollout restart deployment/<name>`）才能让新值生效。

## 搜索意图 / 用户会怎么搜

- "configmap 改了不生效"
- "kubectl configmap updated but pod not changed"
- "configmap change not reflected in pod"
- "k8s 修改配置不生效怎么办"

## 常见误区（读者带着这些误解来）

1. 以为 K8s 会自动感知所有配置对象的变化并热更新到所有引用它的地方——实际上只有卷挂载（且非 subPath）有周期性同步，env 注入完全没有
2. 反复确认 ConfigMap 内容确实已经是新值（`kubectl get configmap -o yaml`/`kubectl describe configmap`），却不知道问题根本不在 ConfigMap 这一侧，而在于"运行中的 Pod 不会重新读取"
3. 用 `kubectl edit pod` 或直接改 Pod 试图"手动刷新"——Pod 的多数字段创建后不可变，这条路直接走不通，唯一正确路径是让 Deployment 产生一个新的 Pod

## 学习路径价值

完成本实验后，读者获得一个 First Wave 三个 lab 都没覆盖的判断分支：**当前状态"看起来正常"（无报错、Pod Ready）但行为不符合预期时，要检查的不是 Pod/Service 的状态，而是"引用的配置对象是否在容器创建之后才被修改"**。这补全了系列的核心心智模型——"工具判断优先于猜测"——的另一个维度：不仅要会读报错和状态，还要理解 K8s 各类资源"何时被解析/生效"这一时序模型，这是本系列 Second Wave 的主题方向。

## 为什么现在生产这个作为 Second Wave 第一个实验

- CEO/CTO 决策：Second Wave 第一个主题聚焦"配置类"故障，与 First Wave 的"Pod 状态类"故障形成互补，扩大系列覆盖面
- 复用 First Wave 已验证的基础设施（`namespace_exists`/`deployment_ready`/`namespace_not_exists`），只新增两个最小可复用 verifier（`configmap_value_equals`、`deployment_restart_triggered`/`deployment_restart_not_triggered`），工程范围可控
- 教学关键机制（env 注入只在容器创建时解析一次）用真实 K3s 集群可以稳定复现，不需要伪造或引入不确定性

## 与 volume 挂载更新行为的区别（仅在文章中简要说明，不新开实验）

卷挂载的 ConfigMap 有 kubelet 周期性同步（通常一分钟内生效，`subPath` 挂载除外——`subPath` 完全不会同步，是另一个更细分的坑）。本实验只覆盖 env 注入这一种最常见、最容易复现、行为最确定的路径，卷挂载场景留给未来的 Second Wave 后续主题或作为文章里的一句话延伸提示，不在本实验里展开或验证。

## 是否已具备发布条件

不具备。参照 First Wave 模式：本 lab 只做 internal soft launch（若 rehearsal + smoke 通过，`publish_status` 保持内部可见状态，不加入 `LABGEN_ENABLED_LAB_IDS`），配套 official article 是 `ready_to_publish_draft`，不做公开发布，不创建 Directus article 记录。
