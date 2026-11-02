'use client'

import { Card } from '@/components/ui/Card'

interface AssetCardProps {
  icon: string
  symbol: string
  name: string
  amount?: number
  amountExact?: string
  value?: number
  change24h?: number
}

export const AssetCard: React.FC<AssetCardProps> = ({
  icon,
  symbol,
  name,
  amount,
  amountExact,
  value = 0,
  change24h = 0,
}) => {
  const isPositive = change24h >= 0

  return (
    <Card hover className="cursor-pointer">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-4">
          {/* Token Icon */}
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-r from-indigo-600 to-purple-600 text-xl font-bold text-white">
            {icon}
          </div>

          {/* Token Info */}
          <div>
            <div className="flex items-center space-x-2">
              <h3 className="text-lg font-semibold text-white">{symbol}</h3>
              <span className="text-sm text-gray-400">{name}</span>
            </div>
            <p className="mt-1 text-sm text-gray-400">
              {amountExact !== undefined ? amountExact : (amount?.toLocaleString() ?? '—')} {symbol}
            </p>
          </div>
        </div>

        {/* Value & Change */}
        <div className="text-right">
          <p className="text-lg font-semibold text-white">${value.toLocaleString()}</p>
          <div
            className={`mt-1 flex items-center justify-end space-x-1 ${
              isPositive ? 'text-green-500' : 'text-red-500'
            }`}
          >
            <span className="text-sm">
              {isPositive ? '↑' : '↓'} {Math.abs(change24h).toFixed(2)}%
            </span>
          </div>
        </div>
      </div>
    </Card>
  )
}
