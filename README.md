# ai-infra-monitor

基于 Docker + Ollama 的本地 AI 推理服务运维平台，含健康检查、监控告警与私有镜像仓库双机部署。

开发环境是 VMware 里的 Ubuntu 22.04，生产环境是 Rocky Linux 8.10。两台机器通过私有 Registry 分发镜像，监控栈用的 Prometheus + Grafana，服务管理用 systemd 托管。

物理显卡没法直通虚拟机，GPU 监控没做，指标全是主机和容器维度的。

---

## 架构

```
开发机 (Ubuntu 22.04)
├── 构建镜像 → 推送到私有 Registry
└── ai-infra-monitor 源码

生产机 (Rocky Linux 8.10)
├── Docker Registry（私有镜像仓库）:5000
├── Ollama（推理服务）:11434
├── Node Exporter（主机指标）:9100
├── Docker Stats Exporter（容器指标）:9487
├── Prometheus（指标采集）:9090
├── Grafana（可视化面板）:3000
└── systemd → health_check.sh（健康检查）
```

所有监控端口绑定 `127.0.0.1`，外部通过 SSH 隧道访问。

---

## 功能

- Docker Compose 统一编排所有服务，一条命令全起来
- Ollama 容器内置 healthcheck，状态异常自动标记
- systemd 托管健康检查脚本，开机自启，崩了自动拉起
- Prometheus 采集主机（Node Exporter）和容器（Docker Stats Exporter）指标
- Grafana 展示主机资源和容器状态，导入 Node Exporter Full 仪表盘（ID 1860）
- 私有 Registry 实现开发机构建、生产机部署的镜像分发流程
- Apache Bench 压力测试验证服务吞吐能力

> `dashboard.py` 是早期用 Streamlit 写的轻量监控面板，后来换成 Prometheus + Grafana，文件保留作参考。

---

## 技术栈

- Docker / Docker Compose
- Ollama（模型：qwen:0.5b）
- Prometheus + Node Exporter + Docker Stats Exporter
- Grafana
- systemd
- Docker Registry
- Apache Bench

---

## 环境说明

| 角色 | 系统 | 说明 |
|------|------|------|
| 开发机 | Ubuntu 22.04 | 构建镜像，推送到 Registry |
| 生产机 | Rocky Linux 8.10 | 运行所有服务 |

---

## 快速启动

```bash
git clone https://github.com/你的用户名/ai-infra-monitor.git
cd ai-infra-monitor

docker compose up -d
docker compose ps
```

访问：
- Grafana：`http://localhost:3000`（默认账号 admin / 123456，**首次登录请修改密码**）
- Prometheus：`http://localhost:9090`

**健康检查脚本（systemd 托管）：**

> 使用前先把 `systemd/ai-healthcheck.service` 里的 `YOUR_USERNAME` 和路径改成你自己的。

```bash
sudo cp systemd/ai-healthcheck.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ai-healthcheck
sudo systemctl start ai-healthcheck

sudo systemctl status ai-healthcheck
```

---

## 双机部署（私有 Registry）

**生产机搭建 Registry：**

```bash
docker run -d \
  --name registry \
  -p 5000:5000 \
  -v /data/registry:/var/lib/registry \
  --restart=unless-stopped \
  registry:latest

sudo firewall-cmd --add-port=5000/tcp --permanent
sudo firewall-cmd --reload
```

配置信任 HTTP 仓库（两台机器都要做，IP 改成你的生产机地址）：

```bash
sudo tee /etc/docker/daemon.json <<EOF
{
  "insecure-registries": ["生产机IP:5000"]
}
EOF
sudo systemctl restart docker
```

**开发机构建并推送：**

```bash
docker build -t ai-monitor:v2 .
docker tag ai-monitor:v2 生产机IP:5000/ai-monitor:v2
docker push 生产机IP:5000/ai-monitor:v2

docker tag ollama/ollama 生产机IP:5000/ollama:latest
docker push 生产机IP:5000/ollama:latest
```

**生产机拉取运行：**

```bash
docker pull 生产机IP:5000/ollama:latest
docker pull 生产机IP:5000/ai-monitor:v2
docker compose up -d
```

---

## Grafana 配置

1. 添加数据源：Prometheus，URL 填 `http://prometheus:9090`
2. 导入主机仪表盘：Import → ID `1860`（Node Exporter Full）
3. 容器监控自定义面板，指标用 `dockerstats_cpu_usage_ratio` 和 `dockerstats_memory_usage_bytes`

---

## 压力测试

```bash
sudo apt install -y apache2-utils
ab -s 60 -n 1000 -c 10 -p payload.json -T 'application/json' http://127.0.0.1:11434/api/generate
```

| 指标 | 数值 |
|------|------|
| 平均吞吐量 | 2.35 req/s |
| 95% 延迟 | 7.5s |
| 最长请求 | 10.5s |

> `Failed requests (Length)` 是每次响应长度不同导致的，不是真实失败。

---

## 项目结构

```
.
├── docker-compose.yml            # 所有服务编排
├── prometheus/
│   └── prometheus.yml            # Prometheus 采集配置
├── systemd/
│   └── ai-healthcheck.service    # systemd 服务文件（使用前修改用户名和路径）
├── Dockerfile                    # 监控面板镜像
├── health_check.sh               # 健康检查脚本
├── dashboard.py                  # 早期 Streamlit 面板（已由 Grafana 替代，保留参考）
├── payload.json                  # ab 压测请求体
├── requirements.txt              # Python 依赖
└── README.md
```

---

## 踩过的坑

**cAdvisor 跑不起来**：cgroup v2 不兼容，换成 Docker Stats Exporter 解决。

**Docker Stats Exporter 指标名对不上**：网上找的 Grafana 模板用的是 cAdvisor 指标，自己建面板直接用 `dockerstats_*` 前缀的指标就行。

**health_check.sh 里 docker 命令找不到**：systemd 托管时环境变量不完整，脚本开头加 `export PATH=/usr/bin:/bin` 解决。

**Docker Hub 拉基础镜像失败**：配国内镜像加速，`daemon.json` 改完用 `python3 -m json.tool /etc/docker/daemon.json` 验证格式再重启，格式错了 Docker 直接起不来。

**数据卷挂桌面路径重启不自启**：桌面目录依赖用户登录才挂载，Docker 启动时找不到，换到 `/opt/` 下就正常了。

**Prometheus targets 写 localhost 采集不到数据**：Compose 网络里容器间要用容器名通信，不能用 localhost，改成 `node_exporter:9100` 就好了。

**镜像里装 Docker CLI 失败**：用官方源 `download.docker.com` 在构建时访问不到，改成 Debian 官方源的 `docker.io` 包就好了。

---

## 说明

本项目在 VMware 虚拟机环境下开发测试，无物理 GPU 直通，不含 GPU 监控。如需接入 GPU 指标，物理机上可以用 `nvidia-smi` 或 AMD ROCm 的 exporter 对接 Prometheus。