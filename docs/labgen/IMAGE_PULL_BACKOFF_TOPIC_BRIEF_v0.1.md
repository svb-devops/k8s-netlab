# Topic Brief — ImagePullBackOff / ErrImagePull v0.1

## 状态

`documentation_only`。不改变 lab 发布状态，不改变 article_url/cta_enabled。

## 真实痛点

Pod 卡在 `ImagePullBackOff` 或 `ErrImagePull` 是 Kubernetes 新手遇到的第三类高频"部署了但用不了"故障（前两类：CrashLoopBackOff——容器起来了又崩，Service 无 Endpoints——流量到不了 Pod）。这一类的特征是**容器从未启动过**：`kubectl get pods` 里 `READY` 永远是 `0/1`，`RESTARTS` 永远是 `0`（与 CrashLoopBackOff 的"反复重启"形成鲜明对比，是两者最容易被读者混淆、也最值得在文章里明确对比的一点）。

根因集中在四类：镜像名拼错、tag 不存在、registry 不可达、pull secret 缺失/权限不对。对新手而言最反直觉的一点是：YAML/命令本身完全合法，`kubectl apply` 或 `kubectl create` 会成功返回，故障要等到 kubelet 真正去 registry 拉镜像时才暴露——这也是本系列反复强调的"工具判断优先于猜测"心智模型的又一次印证：光看命令是否报错不够，必须看 Pod 实际状态和 Events。

## 搜索意图 / 用户会怎么搜

- "kubectl ImagePullBackOff"
- "ErrImagePull 怎么解决"
- "pod 一直 pending imagepullbackoff"
- "kubectl describe pod image pull error"

## 常见误区（读者带着这些误解来）

1. 以为是网络问题，反复 `kubectl delete pod` 重建——但 Pod 会被 Deployment 立刻重建为同样的失败状态，因为镜像引用本身没变
2. 把 ImagePullBackOff 和 CrashLoopBackOff 混为一谈，用排查 CrashLoopBackOff 的思路去看 `kubectl logs`——但容器从未启动，`kubectl logs` 只会返回空或报错，日志路径在这里是死路
3. 以为要等待更长时间"重试几次就会好"——如果根因是 tag 真的不存在，等多久都不会自愈，`Back-off pulling image` 只是重试节奏在拉长，不代表问题在解决

## 学习路径价值

完成本实验后，读者获得一个补全"Pod 起不来"这一大类故障的判断分支：**Pod 未 Ready → 看 RESTARTS 是否为 0 → 为 0 且 STATUS=ImagePullBackOff/ErrImagePull → 用 `kubectl describe pod` 的 Events 找到镜像拉取失败的具体原因（而不是查日志）→ 核对镜像名/tag → 修正**。这与 CrashLoopBackOff（RESTARTS 递增，日志路径有效）形成互补分支，两篇文章放在一起读，读者能建立一个覆盖"Pod 是否曾经启动过"这一关键判断点的完整决策树。

## 为什么现在生产这个作为 first wave 第三个实验

- 与前两个 lab 共享"Pod 状态类"故障诊断心智模型（`kubectl get pods` → `kubectl describe` → 定位 → 修复 → 验证），学习曲线平滑，不引入新的资源类型（Service/ConfigMap 等），符合 `PHASE1_SERIES_ALIGNMENT_v0.1.md` 排期
- 复用现有 verifier 能力（`deployment_unavailable`/`deployment_ready`），不需要新增 verify 原语或扩大 RBAC 面——是三个 first wave lab 里工程范围最小的一个
- 内部镜像仓库（`172.16.100.1:5000`）已确认存在大量已知 tag（如 `library/busybox` 的完整 tag 列表），可以用一个真实不存在的 tag 触发**真实的** `404 manifest unknown`，而不是伪造的失败场景

## 当前只做单命名空间 / single runtime

不涉及 pull secret 场景（该场景需要私有 registry + imagePullSecrets 配置，属于更复杂的变体，本次不做）。本次只覆盖"tag 不存在"这一根因，是四类根因里最常见、最容易复现、也最适合新手入门的一种。

## 是否已具备发布条件

不具备。参照 lab #1/#2 模式：本 lab 只做 internal soft launch（`publish_status=published` 但不写入 `LABGEN_ENABLED_LAB_IDS`），配套 official article 仍是 `ready_to_publish_draft`，不做公开发布。
