# Topic Brief — Service 无 Endpoints（selector/labels 不匹配）v0.1

## 状态

`documentation_only`。不改变 lab 发布状态，不改变 article_url/cta_enabled。

## 真实痛点

Kubernetes 新手在部署 Service 后，最常见的两类"流量不通"故障之一（另一类是 Ingress，已 defer）就是 Service 建好了、Pod 也在 Running，但请求打不到 Pod 上。多数人第一反应是查 Pod 日志、查网络策略、查防火墙——但真正的根因 90% 概率是 `Service.spec.selector` 和 `Pod.metadata.labels` 没对上，Kubernetes 找不到该把流量转发给谁，`kubectl get endpoints` 永远是空的。

这不是一个"边角料"故障：`kubectl create service` 命令行方式默认生成的 selector 与常见的 `kubectl create deployment` 默认标签规则并不总是一致，手写 YAML 时打错一个 label 值也是家常便饭。

## 搜索意图 / 用户会怎么搜

- "kubectl service no endpoints"
- "service 无法访问 pod"
- "kubectl describe service endpoints none"
- "k8s service selector not matching pod labels"

## 常见误区（读者带着这些误解来）

1. 以为是 Pod 没起来 —— 但 Pod 明明是 `Running`
2. 以为是网络策略/防火墙拦截 —— 排查半天发现命名空间里根本没有 NetworkPolicy
3. 以为要重启 Service 才能"生效" —— Service 是声明式对象，没有"生效"这个动作，selector 从来没被满足过

## 学习路径价值

完成本实验后，读者获得一个可复用的排查心智模型：**Service 连不通 → 先查 Endpoints 是否为空 → 空则对比 selector 与 labels → 不对就是根因**。这个心智模型可以迁移到几乎所有 Service 相关故障，是本系列（Kubernetes 常见故障排查实战）里复用率最高的一条诊断路径。

## 与已发布的第一个 lab（CrashLoopBackOff）的关系

CrashLoopBackOff 排查的是"Pod 自己起不来"，本主题排查的是"Pod 起来了但流量到不了"，两者共同覆盖 K8s 新手最常遇到的两类"看起来部署了但用不了"故障，形成互补而非重复的学习路径。

## 是否已具备发布条件

不具备。本 lab 只完成了 internal soft launch（`publish_status=published` 但未加入 `LABGEN_ENABLED_LAB_IDS`），配套的 official article 仍是草稿（`article_url=null`，`cta_enabled=false`）。发布条件详见 `SERVICE_NO_ENDPOINTS_OFFICIAL_ARTICLE_DRAFT_v0.1.md` 底部的 blockers。
