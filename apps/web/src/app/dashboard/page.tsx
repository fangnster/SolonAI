'use client'

import { useState, useEffect, useRef } from 'react'
import { useWallet } from '@solana/wallet-adapter-react'
import { StatCard } from '@/components/dashboard/StatCard'
import { AssetCard } from '@/components/assets/AssetCard'
import { StrategyCard } from '@/components/strategy/StrategyCard'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { useTranslation } from '@/hooks/useTranslation'
import { mockAssets, mockPortfolioStats } from '@/data/mockAssets'
import { mockStrategies } from '@/data/mockStrategies'
import { walletAssetCards } from '@/lib/wallet-asset-view'
import { LatestWalletRequest, loadLatestWallet } from '@/lib/latest-wallet-request'
import {
  liveReportAgeLabel,
  sampleLocalTime,
  type ReportAgeView,
  type ReportAgeTracker,
} from '@/lib/report-age.ts'
import { assetsApi, WalletAssetsRead, AssetDiagnosisResponse, PnLResponse } from '@/lib/api-client'

type TabType = 'overview' | 'profit' | 'risk'

export default function DashboardPage() {
  const { t } = useTranslation()
  const { publicKey, connected } = useWallet()
  const [activeTab, setActiveTab] = useState<TabType>('overview')
  const [storedWalletAssets, setWalletAssets] = useState<WalletAssetsRead | null>(null)
  const walletAddress = connected && publicKey ? publicKey.toBase58() : null
  const walletAssets =
    storedWalletAssets?.wallet_address === walletAddress ? storedWalletAssets : null
  const walletRequests = useRef(new LatestWalletRequest())
  const [walletLoading, setWalletLoading] = useState(false)
  const [diagnosis, setDiagnosis] = useState<AssetDiagnosisResponse | null>(null)
  const [pnl, setPnl] = useState<PnLResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ageState, setAgeState] = useState<{
    tracker: ReportAgeTracker
    view: ReportAgeView
  } | null>(null)
  const liveAge = ageState?.tracker === walletAssets?.client_age_tracker ? ageState?.view : null
  const displayWalletAssets = liveAge && !liveAge.expired ? walletAssets : null

  useEffect(() => {
    if (!walletAssets) {
      setAgeState(null)
      return
    }
    const tracker = walletAssets.client_age_tracker
    const update = () => setAgeState({ tracker, view: tracker.observe(sampleLocalTime()) })
    update()
    const timer = window.setInterval(update, 1000)
    window.addEventListener('focus', update)
    window.addEventListener('pageshow', update)
    document.addEventListener('visibilitychange', update)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', update)
      window.removeEventListener('pageshow', update)
      document.removeEventListener('visibilitychange', update)
    }
  }, [walletAssets])

  // 获取钱包资产
  const fetchWalletAssets = async (forceRefresh = false) => {
    if (!walletAddress) return

    setError(null)
    await loadLatestWallet<WalletAssetsRead>(
      walletRequests.current,
      walletAddress,
      (address) => assetsApi.getWalletAssets(address, forceRefresh),
      {
        success: setWalletAssets,
        error: (err) => {
          console.error('Failed to fetch wallet assets:', err)
          setError('获取资产数据失败')
        },
        loading: setWalletLoading,
      }
    )
  }

  useEffect(() => {
    if (walletAddress) {
      fetchWalletAssets()
      if (activeTab === 'profit') {
        fetchPnL()
      } else if (activeTab === 'risk') {
        fetchDiagnosis()
      }
    } else {
      walletRequests.current.invalidate()
      setWalletLoading(false)
      setWalletAssets(null)
      setDiagnosis(null)
      setPnl(null)
    }
    const gate = walletRequests.current
    return () => gate.invalidate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [walletAddress, activeTab])

  const fetchPnL = async () => {
    if (!publicKey) return

    setIsLoading(true)
    try {
      const data = await assetsApi.getPnL(publicKey.toBase58())
      setPnl(data)
    } catch (err) {
      console.error('Failed to fetch PnL:', err)
    } finally {
      setIsLoading(false)
    }
  }

  const fetchDiagnosis = async () => {
    if (!publicKey) return

    setIsLoading(true)
    try {
      const data = await assetsApi.getDiagnosis(publicKey.toBase58())
      setDiagnosis(data)
    } catch (err) {
      console.error('Failed to fetch diagnosis:', err)
    } finally {
      setIsLoading(false)
    }
  }

  // 转换为 AssetCard 格式
  const displayAssets = displayWalletAssets
    ? walletAssetCards(displayWalletAssets)
    : connected
      ? []
      : mockAssets

  const totalValue =
    displayWalletAssets?.total_value_usd ?? (connected ? null : mockPortfolioStats.totalValue)

  const tabs = [
    { id: 'overview' as TabType, name: '资产总览' },
    { id: 'profit' as TabType, name: '盈亏分析' },
    { id: 'risk' as TabType, name: '风险诊断' },
  ]

  return (
    <div className="min-h-screen bg-gray-950 py-8">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        {/* Page Title */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-white">{t('dashboard.title')}</h1>
          <p className="mt-2 text-gray-400">
            {connected
              ? `钱包已连接: ${publicKey?.toBase58().slice(0, 8)}...`
              : '欢迎回来！这是你的资产概览'}
          </p>
        </div>

        {/* 钱包未连接提示 */}
        {!connected && (
          <Card className="mb-8 p-6">
            <div className="flex items-center gap-4">
              <span className="text-4xl">👛</span>
              <div className="flex-1">
                <h3 className="mb-2 text-lg font-semibold text-white">连接钱包查看真实资产</h3>
                <p className="text-sm text-gray-400">
                  点击右上角连接钱包按钮，即可查看您的链上资产数据
                </p>
              </div>
            </div>
          </Card>
        )}

        {/* 加载状态 */}
        {(isLoading || walletLoading) && (
          <Card className="mb-8 p-6">
            <div className="flex items-center gap-4">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-500 border-t-transparent"></div>
              <p className="text-gray-400">正在加载链上资产数据...</p>
            </div>
          </Card>
        )}

        {/* 错误提示 */}
        {error && (
          <Card className="mb-8 border border-red-500/30 bg-red-500/10 p-6">
            <div className="flex items-center gap-4">
              <span className="text-2xl">⚠️</span>
              <div className="flex-1">
                <h3 className="mb-1 font-semibold text-white">加载失败</h3>
                <p className="text-sm text-gray-300">{error}</p>
              </div>
              <Button variant="outline" size="sm" onClick={() => fetchWalletAssets(true)}>
                重试
              </Button>
            </div>
          </Card>
        )}

        {/* Stats Cards */}
        {walletAssets && (
          <p className="mb-4 text-sm text-gray-400">
            {liveAge
              ? liveReportAgeLabel(liveAge, walletAssets.report_context)
              : '正在核对报告年龄…'}
          </p>
        )}
        <div className="mb-8 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
          <StatCard
            title={t('dashboard.totalValue')}
            value={totalValue === null ? '—' : `$${totalValue.toLocaleString()}`}
            change={mockPortfolioStats.change24h}
            trend={mockPortfolioStats.change24h >= 0 ? 'up' : 'down'}
            icon="💰"
          />
          <StatCard
            title={t('dashboard.todayProfit')}
            value={`$${mockPortfolioStats.changeValue.toLocaleString()}`}
            change={mockPortfolioStats.change24h}
            trend={mockPortfolioStats.change24h >= 0 ? 'up' : 'down'}
            icon="📈"
          />
          <StatCard
            title={t('dashboard.activeStrategies')}
            value={mockStrategies.filter((s) => s.deployed).length}
            icon="⚡"
          />
          <StatCard title={t('dashboard.riskLevel')} value={t('common.low')} icon="🛡️" />
        </div>

        {/* Tabs */}
        <div className="mb-8">
          <div className="border-b border-gray-800">
            <nav className="flex space-x-8">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`border-b-2 px-1 py-4 text-sm font-medium transition-colors ${
                    activeTab === tab.id
                      ? 'border-indigo-500 text-indigo-400'
                      : 'border-transparent text-gray-400 hover:border-gray-700 hover:text-gray-300'
                  }`}
                >
                  {tab.name}
                </button>
              ))}
            </nav>
          </div>
        </div>

        {/* Tab Content */}
        {activeTab === 'overview' && (
          <div className="space-y-8">
            {/* Assets Section */}
            <div>
              <div className="mb-6 flex items-center justify-between">
                <h2 className="text-2xl font-bold text-white">{t('dashboard.assets')}</h2>
                <button
                  className="text-sm text-indigo-400 hover:text-indigo-300"
                  onClick={() => fetchWalletAssets(true)}
                  disabled={!connected || walletLoading}
                >
                  刷新报告
                </button>
              </div>
              <div className="space-y-4">
                {displayAssets.map((asset) => (
                  <AssetCard key={asset.id} {...asset} />
                ))}
              </div>

              {connected &&
                displayWalletAssets &&
                displayWalletAssets.tokens.length === 0 &&
                displayWalletAssets.sol_balance_raw === '0' && (
                  <Card className="p-6">
                    <div className="text-center">
                      <span className="text-4xl">🪙</span>
                      <h3 className="mt-4 text-lg font-semibold text-white">钱包暂无资产</h3>
                      <p className="mt-2 text-sm text-gray-400">您的钱包中还没有任何资产</p>
                    </div>
                  </Card>
                )}
            </div>

            {/* Active Strategies Section */}
            <div>
              <div className="mb-6 flex items-center justify-between">
                <h2 className="text-2xl font-bold text-white">活跃策略</h2>
                <button className="text-sm text-indigo-400 hover:text-indigo-300">
                  查看全部 →
                </button>
              </div>
              <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
                {mockStrategies
                  .filter((s) => s.deployed)
                  .map((strategy) => (
                    <StrategyCard key={strategy.id} {...strategy} />
                  ))}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'profit' && (
          <div className="space-y-8">
            {/* 盈亏概览 */}
            <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
              <Card className="p-6">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-lg font-semibold text-white">总盈亏</h3>
                  <span className="text-2xl">📊</span>
                </div>
                <p
                  className={`mb-2 text-3xl font-bold ${
                    pnl && pnl.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}
                >
                  {pnl ? `${pnl.total_pnl >= 0 ? '+' : ''}$${pnl.total_pnl.toFixed(2)}` : '+$0.00'}
                </p>
                <p className="text-sm text-gray-400">
                  年化收益率: {pnl ? `${pnl.roi_percentage.toFixed(1)}%` : 'N/A'}
                </p>
              </Card>

              <Card className="p-6">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-lg font-semibold text-white">持仓盈亏</h3>
                  <span className="text-2xl">💎</span>
                </div>
                <p
                  className={`mb-2 text-3xl font-bold ${
                    pnl && pnl.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}
                >
                  {pnl
                    ? `${pnl.unrealized_pnl >= 0 ? '+' : ''}$${pnl.unrealized_pnl.toFixed(2)}`
                    : '+$0.00'}
                </p>
                <p className="text-sm text-gray-400">浮动盈亏</p>
              </Card>

              <Card className="p-6">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-lg font-semibold text-white">已实现盈亏</h3>
                  <span className="text-2xl">🌾</span>
                </div>
                <p
                  className={`mb-2 text-3xl font-bold ${
                    pnl && pnl.realized_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}
                >
                  {pnl
                    ? `${pnl.realized_pnl >= 0 ? '+' : ''}$${pnl.realized_pnl.toFixed(2)}`
                    : '+$0.00'}
                </p>
                <p className="text-sm text-gray-400">历史交易</p>
              </Card>
            </div>

            {/* 详细盈亏分析 */}
            {pnl && pnl.breakdown && pnl.breakdown.length > 0 && (
              <Card className="p-6">
                <h2 className="mb-6 text-xl font-bold text-white">盈亏明细</h2>
                <div className="space-y-4">
                  {pnl.breakdown.map((item, index) => (
                    <div
                      key={index}
                      className="flex items-center justify-between rounded-lg bg-gray-800 p-4"
                    >
                      <div>
                        <p className="font-medium text-white">{item.asset}</p>
                        <p className="mt-1 text-sm text-gray-400">{item.type}</p>
                      </div>
                      <div className="text-right">
                        <p
                          className={`text-xl font-bold ${
                            item.pnl >= 0 ? 'text-green-400' : 'text-red-400'
                          }`}
                        >
                          {item.pnl >= 0 ? '+' : ''}${item.pnl.toFixed(2)}
                        </p>
                        <p className="text-sm text-gray-400">
                          {item.percentage >= 0 ? '+' : ''}
                          {item.percentage.toFixed(2)}%
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {!pnl && !isLoading && (
              <Card className="p-6">
                <div className="text-center text-gray-400">暂无盈亏数据</div>
              </Card>
            )}
          </div>
        )}

        {activeTab === 'risk' && (
          <div className="space-y-8">
            {/* 风险概览 */}
            <div className="grid grid-cols-1 gap-6 md:grid-cols-4">
              <Card className="p-6">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-sm font-medium text-gray-400">风险评分</h3>
                  <span className="text-2xl">🔍</span>
                </div>
                <p
                  className={`text-3xl font-bold ${
                    diagnosis?.risk_level === 'low'
                      ? 'text-green-400'
                      : diagnosis?.risk_level === 'medium'
                        ? 'text-yellow-400'
                        : 'text-red-400'
                  }`}
                >
                  {diagnosis?.risk_score || 'N/A'}
                </p>
              </Card>

              <Card className="p-6">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-sm font-medium text-gray-400">风险等级</h3>
                  <span className="text-2xl">⚠️</span>
                </div>
                <p
                  className={`text-2xl font-bold capitalize ${
                    diagnosis?.risk_level === 'low'
                      ? 'text-green-400'
                      : diagnosis?.risk_level === 'medium'
                        ? 'text-yellow-400'
                        : 'text-red-400'
                  }`}
                >
                  {diagnosis?.risk_level || 'N/A'}
                </p>
              </Card>

              <Card className="p-6">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-sm font-medium text-gray-400">风险项</h3>
                  <span className="text-2xl">⚡</span>
                </div>
                <p className="text-3xl font-bold text-yellow-400">
                  {diagnosis?.issues.length || 0}
                </p>
              </Card>

              <Card className="p-6">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-sm font-medium text-gray-400">健康度</h3>
                  <span className="text-2xl">ℹ️</span>
                </div>
                <p className="text-3xl font-bold text-blue-400">
                  {diagnosis?.health_metrics.diversification_score || 'N/A'}
                </p>
              </Card>
            </div>

            {/* 风险诊断 */}
            <Card className="p-6">
              <h2 className="mb-6 text-xl font-bold text-white">风险诊断</h2>
              <div className="space-y-4">
                {diagnosis && diagnosis.issues.length > 0 ? (
                  diagnosis.issues.map((issue, index) => (
                    <div
                      key={index}
                      className={`rounded-lg border p-4 ${
                        issue.severity === 'high' || issue.severity === 'critical'
                          ? 'border-red-500/30 bg-red-500/10'
                          : issue.severity === 'medium'
                            ? 'border-yellow-500/30 bg-yellow-500/10'
                            : 'border-green-500/30 bg-green-500/10'
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        <span className="text-2xl">
                          {issue.severity === 'high' || issue.severity === 'critical'
                            ? '⚠️'
                            : issue.severity === 'medium'
                              ? '⚡'
                              : '✅'}
                        </span>
                        <div className="flex-1">
                          <div className="mb-2 flex items-center justify-between">
                            <h3 className="font-semibold text-white">{issue.type}</h3>
                            <span
                              className={`rounded px-2 py-1 text-xs text-white ${
                                issue.severity === 'high' || issue.severity === 'critical'
                                  ? 'bg-red-500'
                                  : issue.severity === 'medium'
                                    ? 'bg-yellow-500'
                                    : 'bg-green-500'
                              }`}
                            >
                              {issue.severity}
                            </span>
                          </div>
                          <p className="mb-3 text-sm text-gray-300">{issue.description}</p>
                          <p className="text-sm text-gray-400">建议: {issue.recommendation}</p>
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-lg border border-green-500/30 bg-green-500/10 p-4">
                    <div className="flex items-start gap-3">
                      <span className="text-2xl">✅</span>
                      <div className="flex-1">
                        <h3 className="mb-2 font-semibold text-white">资产安全</h3>
                        <p className="text-sm text-gray-300">
                          {diagnosis ? '您的资产状态良好，未发现明显风险' : '暂无诊断数据'}
                        </p>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </Card>

            {/* 健康指标 */}
            {diagnosis?.health_metrics && (
              <Card className="p-6">
                <h2 className="mb-6 text-xl font-bold text-white">健康指标</h2>
                <div className="space-y-4">
                  <div className="flex items-center justify-between rounded-lg bg-gray-800 p-4">
                    <div>
                      <p className="font-medium text-white">多样化评分</p>
                      <p className="mt-1 text-sm text-gray-400">资产分散程度</p>
                    </div>
                    <div className="text-right">
                      <p className="text-xl font-bold text-white">
                        {diagnosis.health_metrics.diversification_score}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center justify-between rounded-lg bg-gray-800 p-4">
                    <div>
                      <p className="font-medium text-white">流动性评分</p>
                      <p className="mt-1 text-sm text-gray-400">资产变现能力</p>
                    </div>
                    <div className="text-right">
                      <p className="text-xl font-bold text-white">
                        {diagnosis.health_metrics.liquidity_score}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center justify-between rounded-lg bg-gray-800 p-4">
                    <div>
                      <p className="font-medium text-white">波动性评分</p>
                      <p className="mt-1 text-sm text-gray-400">价格稳定性</p>
                    </div>
                    <div className="text-right">
                      <p className="text-xl font-bold text-white">
                        {diagnosis.health_metrics.volatility_score}
                      </p>
                    </div>
                  </div>
                </div>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
