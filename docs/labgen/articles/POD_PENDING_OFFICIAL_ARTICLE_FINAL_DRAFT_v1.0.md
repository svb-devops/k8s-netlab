# Pod 一直 Pending？先看 Events，不要翻容器日志

`kubectl create deployment` 之后，`kubectl get pods` 显示 `STATUS` 一直是 `Pending`，`READY` 是 `0/1`，而且不管等多久都不会变化。习惯性地去查 `kubectl logs`，得到的是一句"容器还没启动，没有日志"——这条排查路径在这里完全走不通。

## 为什么 `kubectl logs` 在这里毫无意义

`CrashLoopBackOff` 和 `ImagePullBackOff` 都发生在**容器已经被调度到某个节点、kubelet 正在尝试启动它**之后；而 `Pending` 发生在更早的阶段——**调度器（scheduler）还没有为这个 Pod 找到一个可用节点**。既然容器从未被创建过，也就根本不存在任何日志可看。

这是本主题最容易被误判的地方：Pending 状态下 Pod 本身没有任何异常事件的话，很容易让人怀疑是集群本身出了故障，但其实只需要换一个排查方向——看 Pod 有没有被分配到节点，而不是看容器输出了什么。

## 判定依据：先看 Node 列，再看 Conditions

```bash
kubectl get pods -o wide
```

如果 `NODE` 列是空的，说明这个 Pod 从未被调度过。接下来看它的详细状态：

```bash
kubectl describe pod <pod-name>
```

重点看两处：

- **Conditions** 里的 `PodScheduled`：如果是 `False`，说明调度器明确无法为它找到节点
- **Events** 里的 `FailedScheduling`：会带一条具体的 message，说明调度失败的具体原因

## 复现现象

给一个正常运行的 Deployment 打上一个集群里不存在的 `nodeSelector`：

```bash
kubectl patch deployment demo --type=merge -p '{"spec":{"template":{"spec":{"nodeSelector":{"labgen.example/worker":"missing"}}}}}'
```

稍等片刻，新 Pod 的状态：

```
Conditions:
  Type           Status
  PodScheduled   False
```

```
Events:
  Warning  FailedScheduling  ...  default-scheduler  0/1 nodes are available: 1 node(s) didn't match Pod's node affinity/selector.
```

`didn't match Pod's node affinity/selector` 这句话明确指向了问题所在——不是资源不足（那样会提到 `insufficient cpu`/`memory`），也不是 taint 没有容忍（那样会提到 `untolerated taint`），就是 nodeSelector 本身写错了、指向了一个不存在的节点标签。

## 修复：非交互式移除错误配置

```bash
kubectl patch deployment demo --type=json -p '[{"op":"remove","path":"/spec/template/spec/nodeSelector"}]'
```

用 JSON Patch 的 `remove` 操作精确删除这一个字段，不需要 `kubectl edit` 打开交互式编辑器，也是生产环境安全、可脚本化的标准做法。移除后新的 Pod 模板恢复正常，调度器立刻能为它找到可用节点。

## 排查心智模型

- **Pod 一直 Pending，`kubectl logs` 报错说没有日志** → 不是容器故障，是还没被调度，别在这条路径上浪费时间
- **`kubectl get pods -o wide` 的 NODE 列为空** → 确认这是调度阶段的问题
- **`kubectl describe pod` 的 Conditions 里 `PodScheduled=False`，Events 里有 `FailedScheduling`** → 明确是调度失败，看 message 定位具体原因（node selector 不匹配 / 资源不足 / taint 未容忍，是三类不同的调度失败原因，本文只深入其中 nodeSelector 这一类）
- **生产环境提醒**：本文用 `kubectl patch` 演示是为了教学上容易观察和复现这个现象；生产环境里这类配置通常通过 Deployment YAML、Helm values 或 GitOps 流水线的正式变更来修复，而不是运维人员手工执行 patch 命令

## 配套实验

想亲手试一次吗？点击「进入实验」，几秒钟内就能拿到一个预置了这个场景的 Kubernetes 环境，用上面讲的每一条命令亲自观察 Pod 从 Pending 到 Running 的完整过程。

## 系列文章

本文是《Kubernetes 高频故障排查实战系列》的第六篇。如果你的问题是 Pod 一直重启，看 [Pod 一直重启？从 CrashLoopBackOff 学会用 describe 和 logs 定位根因](https://lab.cloudnetops.tech/article.html?slug=crashloopbackoff-describe-logs)；如果 Pod 起来了但访问不通，看 [Service 建好了但访问不通？先检查 Endpoints 和 selector](https://lab.cloudnetops.tech/article.html?slug=service-no-endpoints-selector-labels)；如果 Pod 一直起不来，看 [Pod 卡在 ImagePullBackOff？从 Events 看镜像拉取失败原因](https://lab.cloudnetops.tech/article.html?slug=imagepullbackoff-events-diagnosis)；如果配置改了但不生效，看 [kubectl patch 改了 ConfigMap，应用读到的还是老值？](https://lab.cloudnetops.tech/article.html?slug=configmap-not-effective-rollout-restart)；如果 Pod 里访问不到 Service，看 [Pod 里解析不到 Service？先查 namespace，再查短名称和 FQDN](https://lab.cloudnetops.tech/article.html?slug=dns-service-discovery-namespace-fqdn)。

---

（internal_preview_version：本文当前为 `ready_to_publish_draft`，尚未公开发布，仅供内部 rehearsal/owner dogfood 引用；未来正式发布时替换文末 CTA 段落为公开可点击的「进入实验」入口，方式与前五篇一致）
