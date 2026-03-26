# 触发条件：执行 systemctl restart k8s-netlab 之后

每次重启服务后必须执行，两项都通过才算部署完成：

```bash
sleep 3
curl -s https://lab.cloudnetops.tech/api/health
journalctl -u k8s-netlab -p err --since "2 minutes ago" --no-pager
```

- health 端点必须返回 `{"status":"healthy"}`
- 错误日志无新增异常

任意一项失败，立即停止并告知用户，不要继续后续操作。
