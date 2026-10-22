---
name: device-report
description: Use when the user asks for a full device health summary (battery, storage, memory, uptime).
---

# Device report

1. Call execute_shell with: termux-battery-status
2. Call execute_shell with: df -h /data
3. Call execute_shell with: free -m
4. Summarize in plain spoken sentences: battery percent and charging state, free storage, free memory.
5. Mention anything unusual, such as battery under 20 percent or storage under 10 percent free.
