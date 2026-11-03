# SolonAI

简体中文 | [English](README.en.md) | [个人仓库](https://github.com/fangnster/SolonAI)

SolonAI 是一个持续完善中的 Solana / DeFi 应用。本个人 fork 提供可复现的钱包报告与报价数量契约：保留精确数量和账户身份，限制报告时效，并避免不同代币被错误地统一按 9 位小数换算。

## 已完成的可评审路径

- RPC → WalletService → API → 缓存 → UI：原始整数和固定小数文本使用 JSON 字符串传递。
- 保留 Legacy Token Program 账户地址、owner、program 和读取 slot；区分同 mint 的不同账户。
- 报告命中缓存时保留原始读取窗口，客户端随时间过期；单主 Redis 原子检查阻止被后续请求取代的任务晚写。
- Swap 报价接收明确的 `amount_raw` 字符串，拒绝旧浮点 `amount`，校验返回报价与请求一致。
- 提供 175 项定向测试、真实 Redis 发布实验、8 个来源诊断场景及 5 个离线报价演示场景。

## 先复现，再启动应用

Python 3.11、Node 24、npm 和 Redis 是完整回归的运行条件。离线报价演示只需 Python API 依赖：

```bash
git clone https://github.com/fangnster/SolonAI.git
cd SolonAI
python3.11 -m venv .venv
.venv/bin/python -m pip install -r apps/api/requirements.txt -r requirements-dev.txt
.venv/bin/python scripts/demo_swap_quote.py
```

演示使用真实 HTTP 路由与注入的报价服务，不需要私钥、模型凭证或真实报价连接。预期 `verified: true`，外部报价调用与订单提交均为 0。

完整回归：

```bash
.venv/bin/python scripts/check_wallet_report.py --out .wallet-report-results
.venv/bin/python scripts/trace_wallet_sources.py --case all --out .wallet-report-results/provenance
```

如可执行文件不在 PATH，传入 `--node /absolute/path/to/node --redis-server /absolute/path/to/redis-server`。回归自建临时 Redis，不使用现有业务实例；每次选择新输出目录。

## 文档入口

- [英文项目与评审入口](docs/en/PORTFOLIO.md)
- [安装与本地应用启动](docs/en/SETUP.md)
- [架构和实际完成范围](docs/en/ARCHITECTURE.md)
- [钱包 API 契约](docs/en/API.md)
- [Swap 原始数量契约与迁移](docs/en/QUOTE_CONTRACT.md)
- [测试、命令和验证边界](docs/en/TESTING.md)
- [五分钟钱包演示](docs/en/DEMO.md)
- [原有项目资料索引](docs/README.md)

## 后续工作与贡献

完整鉴权、AI 环境依赖统一、实时提供方 API 适配、报价有效期、USD 估值语义、Token-2022、Redis 故障恢复和浏览器生命周期仍有后续工作。当前通过的是明确范围的回归，不能据此把全部历史界面或自动交易流程视为已完成。

本 fork 含历史上游贡献与后续 AI 辅助工程实践，分别保留证据。个人 fork 的发布不等于上游合并。上游贡献请遵循其规范；本个人仓库的 CI 检查 main、develop、course/** 和 codex/**，静态 Python 检查使用 Ruff。
