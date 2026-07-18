# DNS Service Discovery Topic Brief v0.1

## 现象

Pod 内用 Service 短名称（例如 `api`）访问一个真实存在的 Service，却解析失败——没有任何报错、Service 本身也没有任何异常，`kubectl get pods`/`kubectl get svc` 看到的一切都正常。换成完整域名（FQDN）访问，立刻就通了。

## 关键机制：DNS 搜索域只覆盖当前 namespace

Kubernetes 集群内每个 Pod 的 `/etc/resolv.conf` 都带有一组搜索域（search domain），依次是：

```
<pod所在namespace>.svc.cluster.local
svc.cluster.local
cluster.local
```

短名称查询（例如 `nslookup api`）会依次尝试拼接这些搜索域，也就是只会命中 **当前 namespace 下** 名为 `api` 的 Service。如果目标 Service 部署在另一个 namespace，短名称在所有搜索域里都会得到 NXDOMAIN（域名不存在），这不是网络故障、不是权限问题、也不是 CoreDNS 坏了。

`service.namespace`（短一点的写法）和完整的 `service.namespace.svc.cluster.local`（FQDN）都显式指定了目标 namespace，因此总能正确解析——只要目标 Service 真实存在。

## 为什么容易被误判为集群网络问题

短名称解析失败时，Pod 状态、Service 状态、Endpoints 状态全部正常，很容易让人怀疑是 CoreDNS 故障或者集群网络分区，从而排查方向完全走偏。真正需要检查的只有一件事：**发起查询的 Pod 和目标 Service 是否在同一个 namespace**。

## 判定依据

- 短名称查询失败，但目标 Service 本身状态正常（存在、有 Endpoints）→ 优先怀疑 namespace 不匹配，而不是 CoreDNS/网络故障
- 用完整 FQDN 重试；如果 FQDN 能解析成功，就确认了问题出在短名称的搜索域范围，而不是 DNS 服务本身
