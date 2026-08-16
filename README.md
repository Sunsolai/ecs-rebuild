<p align="center">
  <img src="docs/assets/banner.png" alt="ECS Rebuild — LangGraph Multi-Agent E-commerce Customer Service" width="100%"/>
</p>

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/语言-简体中文-1B4F72?style=for-the-badge" alt="简体中文"/></a>
  &nbsp;
  <a href="README.en.md"><img src="https://img.shields.io/badge/Language-English-117A65?style=for-the-badge" alt="English"/></a>
</p>

---

# ECS Rebuild — 方案 A（LangGraph 多智能体）

**企业级电商客服**方案 A：用 **LangGraph Supervisor + 领域专家 Agent** 做对话编排，用 **Tools** 承载业务读写，用 **GraphRAG** 做商品知识问答。

> 本地路径：`ecs-rebuild`  
> 演进路线：A（本仓库）→ B（Temporal 事务）→ C（领域微服务）

## 架构

```text
Channel / Client
       │
       ▼
┌──────────────────┐
│ FastAPI Gateway  │  POST /v1/chat
└────────┬─────────┘
         ▼
┌──────────────────┐
│ LangGraph        │  Supervisor 路由
│ Orchestrator     │  → order / logistics / postsale / knowledge / chitchat
│ + Checkpointer    │  memory | sqlite | postgres
└────────┬─────────┘
         ├──────── Domain Tools (MySQL)
         └──────── GraphRAG (Neo4j + Embedding)
```

## 能力对照

| 原 Rasa 能力 | Scheme A |
|--------------|----------|
| CALM flows | LangGraph 节点 + ReAct Agent |
| `actions/*` | `apps/tools/*` |
| EnterpriseSearch / GraphRAG | `apps/knowledge/graphrag.py` |
| REST channel | FastAPI `/v1/chat` |
| In-memory tracker | LangGraph checkpointer |

覆盖：订单查询 / 改址 / 取消、物流查询与投诉、退款退货换货、商品知识问答、闲聊兜底。

## 目录

```text
ecs-rebuild/
├── apps/
│   ├── gateway/          # FastAPI 入口
│   ├── orchestrator/     # LangGraph 编排与 Agents
│   ├── tools/            # 订单 / 物流 / 售后 Tools
│   └── knowledge/        # GraphRAG
├── packages/shared/      # 配置、SQLAlchemy ORM
├── docs/assets/          # README 资源（横幅图等）
├── infra/                # 架构说明
├── tests/
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## 快速开始

### 1. 环境

- Python 3.10+
- MySQL 8（电商业务库，默认库名 `ecs`）
- Neo4j 5（可选，商品知识问答需要）
- DashScope API Key
- Embedding 服务（OpenAI 兼容，默认 `http://127.0.0.1:10010/v1`）

```bash
cd ecs-rebuild
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

编辑 `.env`，填写 `API_KEY`、`DB_*`、`NEO4J_*`。

### 2. 启动

```bash
# 在 ecs-rebuild 根目录
set PYTHONPATH=.
uvicorn apps.gateway.main:app --host 0.0.0.0 --port 8080 --reload
```

### 3. 调用

```bash
curl -X POST http://127.0.0.1:8080/v1/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"message\": \"帮我查一下订单\", \"user_id\": \"1\", \"thread_id\": \"demo-1\"}"
```

健康检查：`GET /health`

### 4. Docker（可选）

```bash
docker compose up -d --build
```

注意：Compose 仅拉起空 MySQL/Neo4j，需自行导入与原项目一致的业务数据与图谱索引。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/v1/chat` | 多轮对话；同一 `thread_id` 保持会话 |

请求体：

```json
{
  "message": "查询物流",
  "user_id": "1",
  "thread_id": "session-001"
}
```

## 与后续方案的衔接

- **方案 B**：将 `cancel_order` / `commit_postsale` / `update_order_receive_info` 改为向 Temporal 投递命令，Agent 只负责澄清与确认。
- **方案 C**：把 `apps/tools` 抽成独立 Order / Logistics / Postsale / Knowledge 微服务，Gateway 与 Orchestrator 仅编排。
