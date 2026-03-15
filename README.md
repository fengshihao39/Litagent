# Litagent 文献智能助手

## 部署

### Docker 部署

(WIP)

### 一键部署

(WIP)

### 手动部署

Litagent 需要 Python 3.13 或更高版本。我们使用 `uv` 进行依赖管理。

当前版本的 Litagent 需要分别启动后端和前端，我们将在后续版本中给出一键启动脚本和一键部署脚本。

```bash
# Clone 该 Repo 到本地
git clone https://github.com/fengshihao39/Litagent.git
cd Litagent

# 使用 uv 管理环境
uv sync

# 启动后端
python -m litagent.backend.run

# 启动前端
streamlit run litagent/frontend/app.py
```
