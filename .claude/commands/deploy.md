部署 k8s-netlab 并验证服务健康。

执行以下步骤，每步完成后再进行下一步：

1. 重启服务：
   ```bash
   systemctl restart k8s-netlab
   ```

2. 等待 3 秒，检查 health 端点：
   ```bash
   sleep 3 && curl -s https://lab.cloudnetops.tech/api/health
   ```
   要求返回 `{"status":"healthy"}`，否则停止并报告。

3. 检查错误日志：
   ```bash
   journalctl -u k8s-netlab -p err --since "2 minutes ago" --no-pager
   ```
   如有错误输出，报告具体内容。

两项全部通过才算部署完成。如任意一项失败，立即停止并告知用户，不要继续。
