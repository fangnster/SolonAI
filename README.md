# Solon AI

简体中文 | [English](README.en.md)

> Solana生态全链路非托管AI金融智能体

## 项目简介

Solon AI 是一个基于 Solana 区块链的 AI 金融智能体平台，通过多智能体协同为用户提供资产诊断、策略生成、风险管理和自动化执行服务。

### 核心特性

- 🔐 **非托管架构** - 用户完全掌控私钥，资产安全可控
- 🤖 **多智能体协同** - 意图识别、策略生成、风控、执行四大智能体协同工作
- 📊 **全链路资产诊断** - 实时分析链上资产、收益率、风险敞口
- 💡 **智能策略推荐** - 基于用户风险偏好生成个性化DeFi策略
- 🛡️ **实时风控监控** - 7x24小时监控资产安全，异常自动预警
- 💬 **自然语言交互** - 通过对话完成复杂的DeFi操作

## 技术栈

### 前端
- **框架**: Next.js 14 (App Router)
- **语言**: TypeScript
- **样式**: Tailwind CSS
- **区块链**: @solana/web3.js, @solana/wallet-adapter
- **状态管理**: Zustand
- **部署**: Vercel (免费)

### 后端
- **框架**: FastAPI (Python 3.11+)
- **数据库**: PostgreSQL (Supabase免费版)
- **缓存**: Redis (Upstash免费版)
- **认证**: JWT
- **部署**: Railway (免费)

### AI服务
- **框架**: LangGraph
- **LLM**: OpenAI GPT-4 / Claude
- **向量数据库**: Pinecone (免费版)

### 区块链服务
- **RPC节点**: Alchemy (免费版)
- **DeFi协议**: Jupiter, MarginFi, Kamino
- **钱包**: Phantom, Solflare

## 项目结构

```
solon-ai/
├── apps/
│   ├── web/              # Next.js前端应用
│   └── api/              # FastAPI后端服务
├── services/
│   ├── ai-agents/        # LangGraph智能体服务
│   └── blockchain/       # Solana区块链交互服务
├── packages/
│   ├── types/            # 共享TypeScript类型
│   ├── utils/            # 共享工具函数
│   └── config/           # 共享配置
├── docs/                 # 项目文档
├── .github/              # GitHub Actions CI/CD
└── docker-compose.yml    # 本地开发环境
```

## 快速开始

### 环境要求

- Node.js 18+
- Python 3.11+
- Docker & Docker Compose
- Git

### 1. 克隆项目

```bash
git clone https://github.com/your-org/solon-ai.git
cd solon-ai
```

### 2. 安装依赖

```bash
# 安装前端和共享包依赖
npm install

# 安装后端依赖
cd apps/api
pip install -r requirements.txt
cd ../..

# 安装AI服务依赖
cd services/ai-agents
pip install -r requirements.txt
cd ../..
```

### 3. 配置环境变量

```bash
# 复制环境变量模板
cp apps/web/.env.example apps/web/.env.local
cp apps/api/.env.example apps/api/.env
cp services/ai-agents/.env.example services/ai-agents/.env
```

编辑各个 `.env` 文件，填入必要的配置：

**前端 (apps/web/.env.local)**
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SOLANA_RPC_URL=https://solana-mainnet.g.alchemy.com/v2/YOUR_KEY
```

**后端 (apps/api/.env)**
```env
DATABASE_URL=postgresql://user:password@localhost:5432/solon_ai
REDIS_URL=redis://localhost:6379
JWT_SECRET=your-secret-key
SOLANA_RPC_URL=https://solana-mainnet.g.alchemy.com/v2/YOUR_KEY
```

**AI服务 (services/ai-agents/.env)**
```env
OPENAI_API_KEY=your-openai-key
PINECONE_API_KEY=your-pinecone-key
API_BASE_URL=http://localhost:8000
```

### 4. 启动开发环境

**使用 Docker Compose (推荐)**

```bash
docker-compose up -d
```

**或手动启动各服务**

```bash
# 终端1: 启动数据库和Redis
docker-compose up postgres redis

# 终端2: 启动前端
cd apps/web
npm run dev

# 终端3: 启动后端
cd apps/api
uvicorn main:app --reload --port 8000

# 终端4: 启动AI服务
cd services/ai-agents
python main.py
```

### 5. 访问应用

- 前端: http://localhost:3000
- 后端API: http://localhost:8000
- API文档: http://localhost:8000/docs

## 开发指南

钱包报告的精确数量、账户身份、缓存时效及离线/真实 Redis 回归步骤见 [wallet-report.md](docs/wallet-report.md)。该回归套件使用 Node.js 24。

### 代码规范

项目使用严格的代码规范和自动化检查工具，确保代码质量和一致性。

#### 前端规范
- **ESLint**: 代码质量检查
- **Prettier**: 代码格式化（无分号、单引号、100字符宽度）
- **TypeScript**: 严格类型检查

#### Python 规范
- **Black**: 代码格式化（100字符宽度）
- **Flake8**: 代码质量检查
- **isort**: import 语句排序
- **mypy**: 类型检查（可选）

#### Git Hooks
项目配置了自动化 Git Hooks，在提交代码时会自动运行检查：

- **pre-commit**: 提交前自动运行 lint 和格式化
- **commit-msg**: 校验提交信息格式

### 分支策略

- `main` - 生产环境分支，受保护
- `develop` - 开发环境分支，受保护
- `feature/*` - 功能开发分支
- `bugfix/*` - Bug修复分支
- `hotfix/*` - 紧急修复分支

### 提交规范

使用约定式提交 (Conventional Commits):

```
<type>(<scope>): <subject>

<body>

<footer>
```

**类型 (type)**
- `feat`: 新功能
- `fix`: Bug修复
- `docs`: 文档更新
- `style`: 代码格式调整
- `refactor`: 重构
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建/工具链相关
- `revert`: 回退
- `ci`: CI/CD相关

**示例**
```bash
git commit -m "feat(wallet): 添加Phantom钱包连接功能"
git commit -m "fix(api): 修复资产查询接口超时问题"
git commit -m "docs: 更新README"
```

**注意**: 提交信息会被自动校验，不符合规范的提交会被拒绝。

### 首次设置

克隆项目后，需要安装开发工具：

```bash
# 安装 Node.js 依赖（会自动安装 Git Hooks）
npm install

# 安装 Python 开发工具
pip install -r requirements-dev.txt
```

### 编辑器配置

推荐使用 VSCode，项目已配置：
- 保存时自动格式化
- 自动运行 ESLint 修复
- 推荐插件列表

打开项目时会提示安装推荐插件，请安装以获得最佳开发体验。

### 代码审查

所有代码必须通过 PR 合并，需要至少 1 人审查通过。

**审查清单**
- [ ] 代码符合项目规范
- [ ] 通过所有 CI 检查（lint、type-check、build）
- [ ] 通过所有测试
- [ ] 无明显性能问题
- [ ] 无安全漏洞
- [ ] 文档已更新

**CI 检查项**
- ✅ 前端 ESLint + Prettier + TypeScript
- ✅ 前端构建检查
- ✅ 后端 Black + isort + Flake8
- ✅ Commit 信息格式检查

### 模块开发

#### 前端开发 (apps/web)

```bash
cd apps/web
npm run dev          # 启动开发服务器
npm run build        # 构建生产版本
npm run lint         # ESLint 检查
npm run lint:fix     # ESLint 自动修复
npm run format       # Prettier 格式化
npm run format:check # Prettier 检查
npm run type-check   # TypeScript 类型检查
```

#### 后端开发 (apps/api)

```bash
cd apps/api
uvicorn main:app --reload    # 启动开发服务器
pytest                       # 运行测试
black .                      # 代码格式化
black --check .              # 格式检查
isort .                      # import 排序
flake8 .                     # 代码检查
mypy .                       # 类型检查
```

#### AI服务开发 (services/ai-agents)

```bash
cd services/ai-agents
python main.py               # 启动服务
pytest                       # 运行测试
black .                      # 代码格式化
isort .                      # import 排序
flake8 .                     # 代码检查
```

## 部署

### 前端部署 (Vercel)

1. 在 Vercel 创建新项目
2. 连接 GitHub 仓库
3. 设置构建配置:
   - Framework: Next.js
   - Root Directory: `apps/web`
   - Build Command: `npm run build`
4. 配置环境变量
5. 部署

### 后端部署 (Railway)

1. 在 Railway 创建新项目
2. 连接 GitHub 仓库
3. 添加 PostgreSQL 和 Redis 服务
4. 设置构建配置:
   - Root Directory: `apps/api`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. 配置环境变量
6. 部署

### 数据库 (Supabase)

1. 在 Supabase 创建新项目
2. 获取数据库连接字符串
3. 运行迁移脚本:
   ```bash
   cd apps/api
   alembic upgrade head
   ```

## 免费资源配额

| 服务 | 免费额度 | 限制 |
|------|---------|------|
| Vercel | 100GB带宽/月 | 无限项目 |
| Railway | 500小时/月 | $5免费额度 |
| Supabase | 500MB数据库 | 2个项目 |
| Upstash | 10K命令/天 | 1个数据库 |
| Alchemy | 300M请求/月 | 5个应用 |
| Pinecone | 1个索引 | 100K向量 |

## 团队协作

详细的团队协作规范请查看 [团队协作与项目管理规范.md](./团队协作与项目管理规范.md)

### 团队分工

- **前端组** (3人): 负责 apps/web 开发
- **后端组** (2人): 负责 apps/api 开发
- **AI组** (3人): 负责 services/ai-agents 开发
- **区块链组** (2人): 负责 services/blockchain 开发
- **全栈/DevOps** (1人): 负责架构、部署、CI/CD

### 沟通协作

- **每日站会**: 每天10:00，15分钟同步进度
- **代码审查**: PR提交后24小时内完成审查
- **技术讨论**: 使用GitHub Discussions
- **问题跟踪**: 使用GitHub Issues

## 常见问题

### 1. 如何获取免费的Solana RPC节点？

访问 [Alchemy](https://www.alchemy.com/) 注册账号，创建Solana应用，获取API Key。

### 2. 本地开发如何连接钱包？

使用 Phantom 或 Solflare 浏览器插件，切换到 Devnet 网络进行测试。

### 3. AI服务需要哪些API Key？

- OpenAI API Key (用于GPT-4)
- Pinecone API Key (用于向量存储)

### 4. 如何运行测试？

```bash
# 前端测试
cd apps/web && npm run test

# 后端测试
cd apps/api && pytest

# AI服务测试
cd services/ai-agents && pytest
```

## 文档

### 核心文档
- [📚 文档导航中心](./docs/README.md) - 快速找到你需要的文档
- [📋 需求文档](./需求.md) - 产品需求和功能说明
- [👥 团队协作规范](./团队协作与项目管理规范.md) - Git工作流、代码规范、分工方案
- [🏗️ 系统架构](./docs/ARCHITECTURE.md) - 架构设计和数据流图
- [🚀 快速上手](./docs/GETTING_STARTED.md) - 新人入职指南
- [👨‍💻 角色指南](./docs/ROLE_GUIDE.md) - 按角色划分的开发任务
- [✅ 检查清单](./docs/CHECKLIST.md) - 项目启动检查清单
- [🎨 前端设计规范](./docs/FRONTEND_DESIGN.md) - 视觉风格和组件设计
- [📦 API文档](http://localhost:8000/docs) - FastAPI 自动生成的 API 文档（启动后端后访问）

### 项目规范文档
- [📝 代码规范配置](./docs/CODE_STANDARDS.md) - ESLint、Prettier、Black、Flake8 配置说明
- [🔧 Git Hooks 说明](./.husky/) - pre-commit 和 commit-msg 钩子
- [🤖 CI/CD 配置](./.github/workflows/) - GitHub Actions 工作流

## 许可证

MIT License

## 联系我们

- GitHub Issues: [提交问题](https://github.com/your-org/solon-ai/issues)
- 项目负责人/微信: [xaochen66]

---

**注意**: 本项目处于早期开发阶段，API可能会有变动。生产环境使用前请充分测试。

