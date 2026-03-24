# AI 推理服务运维平台

用 Docker 跑 Ollama，搭了健康检查、监控面板和压力测试，同时通过私有 Registry 实现了开发机到生产机的镜像分发。

开发环境是 VMware 里的 Ubuntu 22.04，生产环境是 Rocky Linux 8.10。物理显卡没法直通虚拟机，所以 GPU 监控这块没做，面板只展示主机的 CPU 和内存。

---

## 功能

- Docker 容器化部署 Ollama，数据卷挂到 `/opt/ollama_data` 持久化模型
- `--restart=always` 策略，进程崩了会自动拉起
- Shell 脚本每 30 秒检查一次 API，结果写进日志
- Streamlit 面板实时展示容器状态和最近日志
- Apache Bench 压力测试，跑了 1000 个请求（并发 10）
- 私有 Docker Registry 部署在生产机，开发机构建镜像后推送，生产机直接拉取

## 技术栈

- Docker
- Ollama（模型用的 qwen:0.5b）
- Streamlit + psutil
- Apache Bench
- Docker Registry（私有镜像仓库）

## 环境说明

| 角色 | 系统 | IP |
|------|------|----|
| 开发机 | Ubuntu 22.04 | 192.168.32.x |
| 生产机 | Rocky Linux 8.10 | 192.168.32.6 |

---

## 快速开始（单机）

**启动容器**

```bash
docker run -d \
  --name ollama \
  -p 127.0.0.1:11434:11434 \
  -v /opt/ollama_data:/root/.ollama \
  --restart=always \
  ollama/ollama

docker exec -it ollama ollama pull qwen:0.5b
```

**启动健康检查**

```bash
sudo touch /var/log/ai_monitor.log
sudo chmod 666 /var/log/ai_monitor.log
chmod +x health_check.sh
./health_check.sh &
```

**启动监控面板**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
streamlit run dashboard.py
```

浏览器打开 `http://localhost:8501`

**压力测试**

```bash
sudo apt install -y apache2-utils
ab -s 60 -n 1000 -c 10 -p payload.json -T 'application/json' http://127.0.0.1:11434/api/generate
```

> ab 报告里的 `Failed requests (Length)` 是因为每次响应长度不一样，不是真的失败。

---

## 双机部署（私有 Registry）

### 1. 在生产机（Rocky）上搭建私有 Registry

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

配置 Docker 信任 HTTP 仓库：

```bash
sudo tee /etc/docker/daemon.json <<EOF
{
  "insecure-registries": ["192.168.32.6:5000"]
}
EOF
sudo systemctl restart docker
```

### 2. 在开发机（Ubuntu）构建并推送镜像

如果拉基础镜像超时，先配国内镜像加速：

```bash
sudo tee /etc/docker/daemon.json <<EOF
{
  "insecure-registries": ["192.168.32.6:5000"],
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.m.daocloud.io"
  ]
}
EOF
sudo systemctl restart docker
```

构建并推送：

```bash
docker build -t ai-monitor:v2 .
docker tag ai-monitor:v2 192.168.32.6:5000/ai-monitor:v2
docker push 192.168.32.6:5000/ai-monitor:v2

docker tag ollama/ollama 192.168.32.6:5000/ollama:latest
docker push 192.168.32.6:5000/ollama:latest
```

### 3. 在生产机（Rocky）拉取并运行

```bash
docker pull 192.168.32.6:5000/ollama:latest
docker pull 192.168.32.6:5000/ai-monitor:v2

docker run -d \
  --name ollama \
  -p 127.0.0.1:11434:11434 \
  -v /opt/ollama_data:/root/.ollama \
  --restart=always \
  192.168.32.6:5000/ollama:latest

docker run -d \
  --name ai-monitor \
  --network host \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /var/log/ai_monitor.log:/var/log/ai_monitor.log:ro \
  --restart=always \
  192.168.32.6:5000/ai-monitor:v2
```

挂载 `/var/run/docker.sock` 是为了让容器内的 Docker CLI 能跟宿主机通信，监控面板才能拿到容器状态。

**在生产机上跑健康检查脚本：**

```bash
sudo mkdir -p /opt/ai-monitor
sudo nano /opt/ai-monitor/health_check.sh   # 粘贴 health_check.sh 内容
sudo chmod +x /opt/ai-monitor/health_check.sh
sudo touch /var/log/ai_monitor.log
sudo chmod 666 /var/log/ai_monitor.log
sudo nohup /opt/ai-monitor/health_check.sh &
```

浏览器访问 `http://192.168.32.6:8501` 查看面板。

---

## 测试结果

**自动重启**

```bash
docker exec ollama pkill ollama   # 模拟进程崩溃
docker ps                          # 几秒后容器自动重启
```

**压力测试（1000 请求 / 并发 10）**

| 指标 | 数值 |
|------|------|
| 平均吞吐量 | 2.35 req/s |
| 95% 延迟 | 7.5s |
| 最长请求 | 10.5s |

**系统重启自启**

```bash
sudo reboot
docker ps   # ollama 自动运行
```

---

## 项目结构

```
.
├── Dockerfile        # 监控面板镜像构建文件
├── health_check.sh   # 健康检查脚本
├── dashboard.py      # Streamlit 监控面板
├── payload.json      # ab 压测用的请求体
├── requirements.txt  # Python 依赖
└── README.md
```

---

## 踩过的坑

**Docker Hub 拉取失败**：国内访问不稳定，配镜像加速器解决。配完记得 `docker info | grep -A 3 "Registry Mirrors"` 验证一下有没有生效。

**daemon.json 格式错了导致 Docker 起不来**：JSON 不能有多余的逗号，改完一定先用 `python3 -m json.tool /etc/docker/daemon.json` 验证格式再重启。

**镜像里装 Docker CLI 失败**：用官方源 `download.docker.com` 在构建时访问不到，改成 Debian 官方源的 `docker.io` 包就好了。

**监控面板拿不到容器状态**：容器里没有 Docker CLI，加进 Dockerfile 同时挂载 `/var/run/docker.sock` 才能用。

**数据卷路径**：挂桌面路径重启后容器没自启，因为桌面目录要用户登录才挂载。换到 `/opt/ollama_data` 系统级路径就正常了。

**`--restart=always` 的边界**：手动 `docker stop` 不会触发重启，只有进程异常退出才会，所以测自动重启要用 `docker exec ollama pkill ollama`。

**ab 压测超时**：模型冷启动慢，默认 30 秒超时不够，加 `-s 60` 解决。

---

## 说明

本项目在 VMware Ubuntu 22.04 虚拟机中开发，Rocky Linux 8.10 作为生产环境测试。虚拟机无法直通 GPU，监控面板仅展示主机资源。如需 GPU 监控，部署在物理机上可以接 AMD ROCm 或 nvidia-smi。
