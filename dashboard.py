import streamlit as st
import time
import subprocess
import psutil

st.set_page_config(page_title="AI 服务监控", layout="wide")
st.title("🤖 本地 AI 推理服务监控面板")

LOG_FILE = "/var/log/ai_monitor.log"
CONTAINER_NAME = "ollama"


def get_docker_stats():
    try:
        result = subprocess.run(
            [
                "docker", "stats", "--no-stream",
                "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}",
                CONTAINER_NAME,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = result.stdout.strip().split("\n")
        if lines and lines[0]:
            parts = lines[0].split("\t")
            if len(parts) >= 3:
                return {
                    "name": parts[0],
                    "cpu": parts[1].replace("%", ""),
                    "memory": parts[2],
                }
    except Exception:
        return None
    return None


def get_recent_logs(n=20):
    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
        return lines[-n:]
    except Exception:
        return ["日志文件不存在或无法读取"]


placeholder = st.empty()

while True:
    with placeholder.container():
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("📊 容器资源")
            stats = get_docker_stats()
            if stats:
                st.metric("容器", stats["name"])
                st.metric("CPU", f"{stats['cpu']}%")
                st.metric("内存", stats["memory"])
            else:
                st.error("获取容器状态失败，请确认容器正在运行")

        with col2:
            st.subheader("📝 最近日志")
            logs = get_recent_logs()
            for line in reversed(logs):
                line = line.strip()
                if not line:
                    continue
                if "SUCCESS" in line:
                    st.success(line)
                elif "ERROR" in line:
                    st.error(line)
                else:
                    st.info(line)

        st.subheader("💻 主机资源")
        c1, c2, c3 = st.columns(3)
        c1.metric("CPU 使用率", f"{psutil.cpu_percent()}%")
        mem = psutil.virtual_memory()
        c2.metric("内存使用率", f"{mem.percent}%")
        c3.metric("可用内存", f"{mem.available / 1024 ** 3:.1f} GB")

        st.caption("每 5 秒刷新一次")
        time.sleep(5)
        st.rerun()
