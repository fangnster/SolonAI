import axios from 'axios'
import { validateWalletQuantities } from './exact-amount'
import type { WalletQuantityView } from './wallet-asset-view'
import { validateWalletIdentities, type TokenIdentity } from './wallet-identity'
import { readReportContext, type ReportContext } from './report-context.ts'
import { ReportAgeTracker, sampleLocalTime } from './report-age.ts'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000, // AI 回复可能较慢，设置60秒超时
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    // 可以在这里添加token
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    // 统一错误处理
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

// ===== AI 对话 API =====

export interface ChatRequest {
  message: string
  wallet_address?: string
  session_id?: string
}

export interface ChatResponse {
  reply: string
  intent: string
  intent_params: Record<string, unknown>
  session_id: string
  data?: Record<string, unknown>
}

export interface ChatSessionItem {
  id: string
  session_id: string
  title?: string
  created_at: string
}

export interface ChatMessageItem {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  intent?: string
  created_at: string
}

export const chatApi = {
  /**
   * 发送消息给 AI
   */
  sendMessage: (request: ChatRequest): Promise<ChatResponse> => {
    return apiClient.post('/api/v1/chat/message', request)
  },

  /**
   * 流式发送消息给 AI（SSE）
   * 逐字返回 AI 回复，体验更好
   */
  sendMessageStream: (
    request: ChatRequest,
    callbacks: {
      onToken: (token: string) => void
      onData?: (data: {
        intent: string
        intent_params: Record<string, unknown>
        data?: Record<string, unknown>
      }) => void
      onSession?: (sessionId: string) => void
      onRagSources?: (sources: { filename: string }[]) => void
      onAgentStatus?: (status: {
        agent: string
        status: 'running' | 'done'
        message: string
      }) => void
      onDone: () => void
      onError: (error: string) => void
    }
  ): { abort: () => void } => {
    const controller = new AbortController()

    fetch(`${API_BASE_URL}/api/v1/chat/message/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          const err = await response.json().catch(() => ({ detail: '请求失败' }))
          callbacks.onError(err.detail || '请求失败')
          return
        }

        const reader = response.body?.getReader()
        if (!reader) {
          callbacks.onError('无法读取响应流')
          return
        }

        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          let eventType = ''
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim()
            } else if (line.startsWith('data: ')) {
              const data = line.slice(6)
              try {
                const parsed = JSON.parse(data)
                if (eventType === 'token') {
                  callbacks.onToken(parsed.token)
                } else if (eventType === 'data') {
                  callbacks.onData?.(parsed)
                } else if (eventType === 'session') {
                  callbacks.onSession?.(parsed.session_id)
                } else if (eventType === 'rag_sources') {
                  callbacks.onRagSources?.(parsed.sources)
                } else if (eventType === 'agent_status') {
                  callbacks.onAgentStatus?.(parsed)
                } else if (eventType === 'done') {
                  callbacks.onDone()
                } else if (eventType === 'error') {
                  callbacks.onError(parsed.error)
                }
              } catch {
                // ignore parse errors
              }
            }
          }
        }
      })
      .catch((err) => {
        if (err.name !== 'AbortError') {
          callbacks.onError(err.message || 'AI 服务不可用')
        }
      })

    return { abort: () => controller.abort() }
  },

  /**
   * AI 服务健康检查
   */
  healthCheck: (): Promise<{ status: string }> => {
    return apiClient.get('/api/v1/chat/health')
  },

  /**
   * 获取会话列表
   */
  getSessions: (walletAddress: string, limit = 20): Promise<ChatSessionItem[]> => {
    return apiClient.get('/api/v1/chat/sessions', {
      params: { wallet_address: walletAddress, limit },
    })
  },

  /**
   * 获取会话消息
   */
  getMessages: (sessionId: string, limit = 100): Promise<ChatMessageItem[]> => {
    return apiClient.get(`/api/v1/chat/sessions/${sessionId}/messages`, {
      params: { limit },
    })
  },

  /**
   * 删除会话
   */
  deleteSession: (
    sessionId: string,
    walletAddress: string
  ): Promise<{ success: boolean; message: string }> => {
    return apiClient.delete(`/api/v1/chat/sessions/${sessionId}`, {
      params: { wallet_address: walletAddress },
    })
  },
}

// ===== 资产 API =====

export interface TokenAsset extends TokenIdentity {
  mint: string
  symbol: string
  name: string
  balance: number
  balance_raw: string
  decimals: number
  balance_exact: string
  value_usd: number
  price_usd: number
}

export interface WalletAssetsResponse extends WalletQuantityView {
  report_context: ReportContext
  wallet_address: string
  quantity_schema_version: 2
  account_identity_version: 1
  token_observed_slot: string | null
  sol_balance_raw: string
  sol_decimals: 9
  sol_balance_exact: string
  sol_balance: number
  sol_price_usd: number
  sol_value_usd: number
  tokens: TokenAsset[]
  total_value_usd: number
}

export type WalletAssetsRead = WalletAssetsResponse & { client_age_tracker: ReportAgeTracker }

export interface AssetDiagnosisResponse {
  wallet_address: string
  risk_level: 'low' | 'medium' | 'high'
  risk_score: number
  issues: Array<{
    type: string
    severity: string
    description: string
    recommendation: string
  }>
  health_metrics: {
    diversification_score: number
    liquidity_score: number
    volatility_score: number
  }
}

export interface PnLResponse {
  wallet_address: string
  total_pnl: number
  total_pnl_percentage: number
  realized_pnl: number
  unrealized_pnl: number
  roi_percentage: number
  breakdown?: Array<{
    asset: string
    type: string
    pnl: number
    percentage: number
  }>
}

export const assetsApi = {
  /**
   * 获取钱包资产
   */
  getWalletAssets: async (walletAddress: string, refresh = false): Promise<WalletAssetsRead> => {
    const sent = sampleLocalTime()
    const data = await apiClient.get<WalletAssetsResponse, WalletAssetsResponse>(
      `/api/v1/assets/${walletAddress}`,
      { params: { refresh } }
    )
    const received = sampleLocalTime()
    validateWalletQuantities(data)
    validateWalletIdentities(data, walletAddress)
    readReportContext(data.report_context)
    return {
      ...data,
      client_age_tracker: new ReportAgeTracker(data.report_context, sent, received),
    }
  },

  /**
   * 获取资产诊断
   */
  getDiagnosis: (walletAddress: string): Promise<AssetDiagnosisResponse> => {
    return apiClient.get(`/api/v1/assets/${walletAddress}/diagnosis`)
  },

  /**
   * 获取盈亏分析
   */
  getPnL: (walletAddress: string): Promise<PnLResponse> => {
    return apiClient.get(`/api/v1/assets/${walletAddress}/pnl`)
  },
}

// ===== 策略 API =====

export interface StrategyGenerateRequest {
  wallet_address: string
  amount: number
  token: string
  risk_level: 'conservative' | 'balanced' | 'aggressive'
  duration_days: number
}

export interface Strategy {
  id: string
  wallet_address: string
  goal: string
  risk_tolerance: string
  time_horizon: string
  strategy_content: string
  recommended_actions: Array<{
    action: string
    token?: string
    amount?: number
    reason: string
  }>
  expected_return?: number
  risk_level: string
  created_at: string
  status: 'pending' | 'active' | 'executed' | 'completed'
}

export interface StrategyGenerateResponse {
  strategy: Strategy
}

export const strategyApi = {
  /**
   * 生成投资策略
   */
  generateStrategy: (request: StrategyGenerateRequest): Promise<StrategyGenerateResponse> => {
    return apiClient.post('/api/v1/strategy/generate', request)
  },

  /**
   * 获取策略列表
   */
  listStrategies: (walletAddress: string): Promise<{ strategies: Strategy[] }> => {
    return apiClient.get('/api/v1/strategy/list', { params: { wallet_address: walletAddress } })
  },

  /**
   * 获取策略详情
   */
  getStrategy: (strategyId: string): Promise<{ strategy: Strategy }> => {
    return apiClient.get(`/api/v1/strategy/${strategyId}`)
  },

  /**
   * 执行策略
   */
  executeStrategy: (
    strategyId: string,
    walletAddress: string
  ): Promise<{ success: boolean; message: string; transactions?: unknown[] }> => {
    return apiClient.post(`/api/v1/strategy/${strategyId}/execute`, {
      wallet_address: walletAddress,
    })
  },
}

// ===== 风控 API =====

export interface RiskAssessment {
  wallet_address: string
  overall_risk_score: number
  risk_level: 'low' | 'medium' | 'high' | 'critical'
  risk_factors: Array<{
    factor: string
    score: number
    description: string
    impact: string
  }>
  recommendations: string[]
  last_updated: string
}

export interface Transaction {
  signature: string
  timestamp: string
  type: string
  status: 'success' | 'failed' | 'pending'
  amount?: number
  token?: string
  from?: string
  to?: string
  risk_score?: number
  risk_flags?: string[]
}

export interface RiskAlert {
  id: string
  wallet_address: string
  alert_type: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  title: string
  description: string
  created_at: string
  resolved: boolean
}

export interface Authorization {
  id: string
  wallet_address: string
  program_id: string
  program_name: string
  permissions: string[]
  granted_at: string
  last_used?: string
  risk_level: string
}

export const riskApi = {
  /**
   * 获取风险评估
   */
  assessment: (walletAddress: string): Promise<RiskAssessment> => {
    return apiClient.get('/api/v1/risk/assessment', { params: { wallet_address: walletAddress } })
  },

  /**
   * 获取交易历史
   */
  transactions: (
    walletAddress: string,
    limit?: number
  ): Promise<{ transactions: Transaction[] }> => {
    return apiClient.get('/api/v1/risk/transactions', {
      params: { wallet_address: walletAddress, limit },
    })
  },

  /**
   * 获取风险预警
   */
  alerts: (walletAddress: string): Promise<{ alerts: RiskAlert[] }> => {
    return apiClient.get('/api/v1/risk/alerts', { params: { wallet_address: walletAddress } })
  },

  /**
   * 获取授权管理
   */
  authorizations: (walletAddress: string): Promise<{ authorizations: Authorization[] }> => {
    return apiClient.get('/api/v1/risk/authorizations', {
      params: { wallet_address: walletAddress },
    })
  },

  /**
   * 撤销授权
   */
  revokeAuth: (
    authId: string,
    walletAddress: string
  ): Promise<{ success: boolean; message: string }> => {
    return apiClient.post(`/api/v1/risk/authorizations/${authId}/revoke`, {
      wallet_address: walletAddress,
    })
  },
}

// ===== 知识库 API =====

export interface KnowledgeDocument {
  id: string
  user_id: string
  filename: string
  file_type: string
  file_size: number
  chunk_count: number
  upload_time: string
  metadata?: Record<string, unknown>
}

export interface KnowledgeStats {
  total_documents: number
  total_chunks: number
  total_size_bytes: number
  document_types: Record<string, number>
}

export interface KnowledgeSearchResult {
  chunk_id: string
  document_id: string
  filename: string
  content: string
  score: number
  metadata?: Record<string, unknown>
}

export const knowledgeApi = {
  /**
   * 上传知识文档
   */
  upload: (
    file: File,
    walletAddress: string,
    metadata?: Record<string, unknown>
  ): Promise<{ document: KnowledgeDocument }> => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('wallet_address', walletAddress)
    if (metadata) {
      formData.append('metadata', JSON.stringify(metadata))
    }
    return apiClient.post('/api/v1/knowledge/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  /**
   * 获取文档列表
   */
  listDocuments: (walletAddress: string): Promise<{ documents: KnowledgeDocument[] }> => {
    return apiClient.get('/api/v1/knowledge/documents', {
      params: { wallet_address: walletAddress },
    })
  },

  /**
   * 删除文档
   */
  deleteDocument: (
    documentId: string,
    walletAddress: string
  ): Promise<{ success: boolean; message: string }> => {
    return apiClient.delete(`/api/v1/knowledge/documents/${documentId}`, {
      params: { wallet_address: walletAddress },
    })
  },

  /**
   * 搜索知识库
   */
  search: (
    query: string,
    walletAddress: string,
    topK?: number
  ): Promise<{ results: KnowledgeSearchResult[] }> => {
    return apiClient.post('/api/v1/knowledge/search', {
      query,
      wallet_address: walletAddress,
      top_k: topK,
    })
  },

  /**
   * 获取知识库统计
   */
  stats: (walletAddress: string): Promise<KnowledgeStats> => {
    return apiClient.get('/api/v1/knowledge/stats', { params: { wallet_address: walletAddress } })
  },
}
