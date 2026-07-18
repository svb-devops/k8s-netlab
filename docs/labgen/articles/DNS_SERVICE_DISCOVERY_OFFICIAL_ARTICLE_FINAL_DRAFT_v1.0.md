# Pod 里解析不到 Service？先查 namespace，再查短名称和 FQDN

`kubectl get svc` 看到 Service 明明存在，`kubectl get endpoints` 也确认有 Endpoints，Pod 状态也是 `Running`——但在另一个 Pod 里用这个 Service 的短名称去访问，DNS 查询直接失败。没有报错日志，没有异常事件，一切看起来都很正常，除了这一次查询就是查不到。

## 为什么"Service 明明存在"却解析不到

Kubernetes 集群里每个 Pod 的 DNS 解析都带有一组搜索域（search domain），大致等价于：

```
<pod所在namespace>.svc.cluster.local
svc.cluster.local
cluster.local
```

用短名称（比如 `api`）发起查询时，DNS 客户端会依次拼接这些搜索域去尝试解析——也就是说，短名称查询**只会命中当前 Pod 所在 namespace 里同名的 Service**。如果目标 Service 部署在另一个 namespace，无论你查多少次，短名称查询都会在所有搜索域里得到 NXDOMAIN（域名不存在）。

这不是网络故障，不是 CoreDNS 出问题，也不是 RBAC 权限不够——纯粹是短名称的设计范围本来就只覆盖当前 namespace。

## 复现现象

假设目标 Service `api` 部署在 `labgen-dns-target` namespace，你在自己的 namespace 里发起查询：

```bash
nslookup api
```

```
** server can't find api.<your-namespace>.svc.cluster.local: NXDOMAIN
** server can't find api.svc.cluster.local: NXDOMAIN
** server can't find api.cluster.local: NXDOMAIN
```

换成完整域名（FQDN）：

```bash
nslookup api.labgen-dns-target.svc.cluster.local
```

```
Name:   api.labgen-dns-target.svc.cluster.local
Address: 10.43.189.170
```

同一个目标，只是显式指定了 namespace，立刻就解析成功了。

## 判定依据：什么时候该往这个方向想

当你确认了以下两点，就该怀疑是 namespace 范围问题，而不是集群网络或 DNS 故障：

- 目标 Service 本身状态正常（`kubectl get svc`/`kubectl get endpoints` 都显示正常，Endpoints 不为空）
- 发起查询的 Pod 和目标 Service 不在同一个 namespace

这种情况下，短名称查询失败是预期行为，不是 bug。

## 修复/定位路径：用完整 FQDN

Kubernetes Service 的完整 DNS 名称格式固定为：

```
<service-name>.<namespace>.svc.cluster.local
```

显式指定 namespace 之后，DNS 客户端不再依赖搜索域拼接，直接命中正确的记录。这是跨 namespace 访问 Service 的标准写法——如果你的应用代码里需要访问另一个 namespace 的 Service，直接在配置里写完整 FQDN，而不要依赖短名称"侥幸"落在同一个 namespace。

## 排查心智模型

- **短名称查询失败，但目标 Service 状态一切正常** → 先检查发起查询的 Pod 和目标 Service 是否在同一个 namespace，而不是怀疑 CoreDNS 或网络分区
- **确认是跨 namespace 场景** → 换成完整 FQDN（`<service>.<namespace>.svc.cluster.local`）验证，能解析说明问题出在短名称的搜索域范围，不是 DNS 服务本身出了故障
- **应用配置里的跨 namespace 依赖**，一律使用完整 FQDN，不要依赖短名称

## 配套实验

想亲手试一次吗？点击「进入实验」，几秒钟内就能拿到一个预置了这个场景的 Kubernetes 环境，用上面讲的每一条命令亲自观察短名称失败、FQDN 成功这两个现象。

## 系列文章

本文是《Kubernetes 高频故障排查实战系列》的第五篇。如果你的问题是 Pod 一直重启，看 [Pod 一直重启？从 CrashLoopBackOff 学会用 describe 和 logs 定位根因](https://lab.cloudnetops.tech/article.html?slug=crashloopbackoff-describe-logs)；如果 Pod 起来了但访问不通，看 [Service 建好了但访问不通？先检查 Endpoints 和 selector](https://lab.cloudnetops.tech/article.html?slug=service-no-endpoints-selector-labels)；如果 Pod 一直起不来，看 [Pod 卡在 ImagePullBackOff？从 Events 看镜像拉取失败原因](https://lab.cloudnetops.tech/article.html?slug=imagepullbackoff-events-diagnosis)；如果配置改了但不生效，看 [kubectl patch 改了 ConfigMap，应用读到的还是老值？](https://lab.cloudnetops.tech/article.html?slug=configmap-not-effective-rollout-restart)。

---

（internal_preview_version：本文当前为 `ready_to_publish_draft`，尚未公开发布，仅供内部 rehearsal/owner dogfood 引用；未来正式发布时替换文末 CTA 段落为公开可点击的「进入实验」入口，方式与前四篇一致）
