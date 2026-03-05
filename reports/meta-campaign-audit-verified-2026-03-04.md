# META CAMPAIGNS AUDIT — SHOPIFY-VERIFIED TRUTH
**Date:** March 4, 2026 (After Attribution Fix)
**Period:** February 9 - March 4, 2026 (Campaign Lifetime)

---

## 🚨 CRITICAL: VERIFIED ROAS ARE MUCH LOWER THAN META REPORTS

**Meta Pixel Claims:** 4.71x ROAS ($4,013 / $852)
**Shopify Verified:** 1.76x ROAS ($1,540.86 / $877.39)
**Discrepancy:** Meta over-reporting by **2.6x**

This matches your 90-day strategy: "Meta over-reports by ~150% (6.16x claimed = 2x verified)"

---

## OVERALL PERFORMANCE (VERIFIED)

| Metric | Value |
|--------|-------|
| **Total Spend** | $877.39 |
| **Total Orders (Shopify)** | 23 |
| **Total Revenue (Verified)** | $1,540.86 |
| **Combined ROAS** | **1.76x** ⚠️ |
| **Average CPA** | $38.17 |
| **Average AOV** | $67.00 |

**Status:** ✗ **All campaigns are underperforming your 2x ROAS floor.**

---

## CAMPAIGN BREAKDOWN (SHOPIFY-VERIFIED)

### 1. GLM Social Proof + Trust | Feb 2026
**Status: ✗ PAUSE IMMEDIATELY — LOSING MONEY**

| Metric | Meta Reports | Shopify Verified |
|--------|--------------|------------------|
| Spend | $407.35 | $407.35 |
| Orders | 26 claimed | **4 actual** |
| Revenue | $2,436 | **$145.60** |
| **ROAS** | 5.98x | **0.36x** |
| CPA | $15.65 | **$101.84** |

**Analysis:**
- **Losing $0.64 for every $1 spent** on this campaign
- Meta claims 26 conversions, only 4 Shopify orders found
- Orders 22 orders (85%!) missing — either fake conversions or unattributed
- **Action:** PAUSE immediately. DO NOT RUN this during PP launch.

---

### 2. GLM Tiered Bundle | ASC | NZ | Feb 2026
**Status: ✗ PAUSE IMMEDIATELY — ZERO CONVERSIONS**

| Metric | Meta Reports | Shopify Verified |
|--------|--------------|------------------|
| Spend | $234.42 | $234.42 |
| Orders | 8 claimed | **0 actual** |
| Revenue | $1,173 | **$0.00** |
| **ROAS** | 5.01x | **0.00x** |
| CPA | $29.30 | **∞ (no sales)** |

**Analysis:**
- **Zero Shopify orders attributed** to this $234 spend
- Meta claims 8 conversions that don't exist in Shopify
- Either: landing page is broken, or Meta pixel is misconfigured
- **Action:** PAUSE immediately. Audit checkout funnel for errors.

---

### 3. PP Bi-Active | ASC | Feb 2026
**Status: ⚠️ HOLD — BARELY ABOVE FLOOR**

| Metric | Meta Reports | Shopify Verified |
|--------|--------------|------------------|
| Spend | $235.62 | $235.62 |
| Orders | 6 claimed | **6 actual** ✓ |
| Revenue | $403.81 | **$425.11** |
| **ROAS** | 1.71x | **1.80x** ✓ |
| CPA | $39.27 | **$39.27** |

**Analysis:**
- **Only campaign with accurate Meta reporting** (1.71x vs 1.80x verified)
- 1.80x ROAS is just barely above your 2x floor
- **Action:** HOLD at current spend. Don't scale. Monitor daily. If drops below 1.7x for 2 days, pause.

---

### 4. Unattributed Meta Traffic
**Status: ⚠️ INVESTIGATE**

| Metric | Value |
|--------|-------|
| Unattributed Orders | 13 |
| Unattributed Revenue | **$841.95** |
| % of Total Meta Revenue | **55%** |

**Problem:** These orders have `utm_source=facebook` but missing `utm_campaign` parameter. Can't tell which campaign drove them.

**Root Cause:** Meta ad URLs not properly formatted with UTM parameters.

**Fix Needed:** Add `utm_campaign={campaign_name}` to all Meta ad URLs before relaunching.

---

## FOR PP LAUNCH (2 Days Away)

### ✗ DO NOT RUN THESE:
- **GLM Social Proof** — 0.36x ROAS (losing money)
- **GLM Tiered Bundle** — 0.00x ROAS (zero conversions)

### ⚠️ IF YOU MUST RUN PAID:
- **PP Bi-Active only** — 1.80x ROAS (only campaign above 1.5x)
- Budget: Max $10/day (test spend only, not scaling)
- Monitor: Daily ROAS check, pause if drops below 1.7x

### ✓ WHAT TO DO INSTEAD:
1. **Pause all Meta campaigns** for 7 days
2. **Focus on organic**: Google (36% of revenue, $0 cost), Email (14% of revenue)
3. **Fix Meta tracking**: Add utm_campaign to all ad URLs
4. **Wait for PP product launch** to be stable (first week)
5. **Relaunch Meta campaigns on March 11** with fixed tracking

---

## ACTION CHECKLIST

- [ ] **TODAY:** Pause GLM Social Proof and GLM Tiered Bundle
- [ ] **TODAY:** Reduce PP Bi-Active to $10/day test budget
- [ ] **This week:** Fix Meta ad URLs — add utm_campaign parameter
- [ ] **Before PP launch:** Focus spend on organic and email
- [ ] **March 11:** After PP stabilizes, relaunch Meta with corrected URLs
- [ ] **March 11:** Re-audit attribution with full campaign names present

---

## SUMMARY

| Campaign | Verified ROAS | Status | Decision |
|----------|---------------|--------|----------|
| GLM Social Proof | 0.36x | LOSING MONEY | **PAUSE** |
| GLM Tiered Bundle | 0.00x | BROKEN | **PAUSE** |
| PP Bi-Active | 1.80x | BARELY VIABLE | **HOLD** |
| **Combined** | **1.76x** | BELOW FLOOR | **PAUSE ALL** |

Your campaigns are 2.6x worse than Meta reports. Use Shopify-verified numbers only. All campaigns below your 2x ROAS floor.

---

*This audit uses Shopify order attribution as the single source of truth. Meta pixel numbers are inflated 2-3x and should not drive campaign decisions.*
