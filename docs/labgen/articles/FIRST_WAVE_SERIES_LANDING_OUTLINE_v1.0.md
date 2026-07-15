# First Wave Series Landing Outline v1.0

**状态**：内容大纲，非可发布页面。不涉及任何前端/路由改动，不创建任何 Directus 记录。

---

## 系列名称

**Kubernetes 高频故障排查实战系列**

## 一句话价值主张

读文章，马上练一次真实故障——每篇文章配一个可动手复现同一个故障、亲手修复的实验环境（当前处于内部验证阶段）。

## 系列定位

面向刚接触 Kubernetes、已经能用基本 `kubectl` 命令、但遇到 Pod/Service 故障时不知道从哪查起的学习者。系列不讲 Kubernetes 概念入门，只讲"看到这个报错/状态，第一步该做什么"。

---

## 三篇文章顺序与依赖关系

| 顺序 | 文章 | 解决什么问题 | 对应 lab 练什么能力 |
|------|------|--------------|----------------------|
| 1 | Pod 一直重启？从 CrashLoopBackOff 学会用 describe 和 logs 定位根因 | Pod 已经"活过"但反复崩溃退出，如何用退出码和历史日志定位崩溃原因 | `kubectl describe`（Last State/Exit Code）、`kubectl logs --previous`、非交互式 `kubectl patch` 修复、`kubectl rollout status` 验证 |
| 2 | Pod 卡在 ImagePullBackOff？从 Events 看镜像拉取失败原因 | Pod 从未启动过，如何区分"没启动"和"启动后崩溃"，如何从 Events 而非日志定位镜像问题 | `RESTARTS` 恒为 0 的判定信号、`kubectl describe` 的 Events 段落、`kubectl set image` 非交互式修复 |
| 3 | Service 建好了但访问不通？先检查 Endpoints 和 selector | Pod 本身健康，但流量路由不到，如何定位 Service/Pod 之间的标签不匹配 | `kubectl get endpoints`、selector 与 labels 对比排查、`kubectl expose` 重建 Service |

**顺序理由**：前两篇都是"Pod 起不来"的排查（CrashLoopBackOff vs ImagePullBackOff 互为对照组，一个重启次数递增、一个恒为 0，放在一起讲能强化读者的判定直觉）；第三篇是"Pod 起来了但流量到不了"，是排查链条上更进一层的问题，适合放在读者已经确认 Pod 健康之后再讲。三篇文章各自的"排查心智模型"段落也据此互相引用，形成一个从"Pod 层"到"Service 层"的完整故障排查地图。

## 每篇文章解决什么问题（详见对应 final draft）

- 详见 `CRASHLOOPBACKOFF_OFFICIAL_ARTICLE_FINAL_DRAFT_v1.0.md`
- 详见 `IMAGE_PULL_BACKOFF_OFFICIAL_ARTICLE_FINAL_DRAFT_v1.0.md`
- 详见 `SERVICE_NO_ENDPOINTS_OFFICIAL_ARTICLE_FINAL_DRAFT_v1.0.md`

## 每个 lab 练什么能力（汇总）

三个 lab 共同训练的核心能力，是"先分流故障类型，再选对应命令，而不是把 `kubectl get/describe/logs` 无差别地全部跑一遍"：

```
Pod 不 Ready？
  → RESTARTS 递增 → CrashLoopBackOff → describe（Last State/Exit Code）+ logs --previous
  → RESTARTS 恒为 0 → ImagePullBackOff → describe（Events）
Pod Ready 但访问不通？
  → Service 层 → get endpoints → 对比 selector 与 labels
```

三个 lab 全部使用非交互式修复命令（`kubectl patch`/`kubectl set image`/`kubectl expose`），刻意不教 `kubectl edit`——现实工程场景里非交互式命令才是可审计、可脚本化、可在 CI 中复用的做法。

## 后续 Second Wave 预告（不承诺上线时间）

first wave 覆盖的是"Pod 层"和"Service 层"最基础的两类故障。后续候选方向（尚未开始，不做任何时间承诺）：

- ConfigMap 修改未生效（配置热更新的常见误解）
- DNS 服务发现失败（集群内部域名解析排查）
- Pod 卡在 Pending（调度失败的常见原因：资源不足、亲和性冲突、污点容忍）

以上仅为方向性候选，**未排期、未立项、未开始任何工程工作**，本大纲不构成对读者或团队的上线时间承诺。

---

## 明确不在本大纲范围内的事项

- 不涉及任何页面路由/前端实现（这是内容大纲，不是页面需求文档）
- 不创建任何 Directus 记录
- 不修改 `LABGEN_ENABLED_LAB_IDS`
- 不包含 CTA 的具体文案落地（见 `FIRST_WAVE_ARTICLE_LAB_ALIGNMENT_v1.0.md` 中的 CTA 一致性检查，以及各篇 final draft 文档自身的 CTA 占位段落）
