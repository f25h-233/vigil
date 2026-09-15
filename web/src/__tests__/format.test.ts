import { describe, expect, it } from 'vitest'
import { fmtDate, fmtDateTime, relTime } from '../format'

describe('fmtDate / fmtDateTime', () => {
  it('按本地时区渲染，不是 UTC', () => {
    // 本地 2026-09-13 12:00 —— 用 UTC 解释会偏 8 小时到 9月13日 04:00 或 9月12日
    const ts = Math.floor(new Date(2026, 8, 13, 12, 0).getTime() / 1000)
    expect(fmtDate(ts)).toBe('9月13日')
    expect(fmtDateTime(ts)).toBe('9月13日 12:00')
  })
})

describe('relTime', () => {
  const now = Math.floor(Date.now() / 1000)

  it('一小时内按分钟', () => {
    expect(relTime(now - 120)).toBe('2 分钟前')
  })
  it('一天内按小时', () => {
    expect(relTime(now - 7200)).toBe('2 小时前')
  })
  it('一周内按天', () => {
    expect(relTime(now - 86400 * 3)).toBe('3 天前')
  })
  it('超过一周回落到日期', () => {
    expect(relTime(now - 86400 * 30)).toMatch(/月.*日/)
  })
  it('未来时间不编「-3 分钟前」', () => {
    // 库里存在 1970 脏数据与未来戳；负数分钟会被读成「-1 分钟前」
    expect(relTime(now + 600)).toMatch(/月.*日/)
  })
  it('刚发出不说「0 分钟前」', () => {
    expect(relTime(now - 10)).toBe('1 分钟前')
  })
})
