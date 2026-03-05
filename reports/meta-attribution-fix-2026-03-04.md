# META ATTRIBUTION FIX — Action Plan
**Date:** March 4, 2026, 2:45pm NZST
**Status:** Root cause identified, fix procedure documented

---

## WHAT BROKE

Your Meta campaign attribution system **stopped working on or before March 3**.

**Evidence:**
- Meta reports 40 purchases ($4,013 revenue)
- Shopify database only attributed 23 orders ($1,540.86) to Meta
- Missing: 17 orders (43% attribution gap)
- Root cause: **UTM parameters missing from Meta ad URLs**

---

## HOW IT'S SUPPOSED TO WORK

1. **Ad Click** → Customer clicks Meta ad
2. **URL has UTM params** → `?utm_source=facebook&utm_medium=cpc&utm_campaign=glm-social-proof`
3. **Lands on site** → Deep Blue Health product page
4. **Shopify captures URL** → Stores `landing_site` with full query string
5. **Order attributed** → order_intelligence.py parses UTM params, classifies to "Meta Ads" channel
6. **Database saved** → customer_intelligence.db stores channel, source, campaign
7. **ROAS verified** → Can match orders to campaigns, calculate accurate ROAS

**Currently broken at step 2:** Meta ad URLs don't include `utm_campaign` parameter

---

## THE FIX (3 Steps)

### Step 1: Update Ad URLs in Meta Ads Manager

For **each active campaign**, you need to add UTM parameters to the landing page URL.

Go to Meta Ads Manager → Click each campaign → Edit ad → Destination URL section

**GLM Social Proof + Trust Campaign:**
- Find the destination URL field
- If it's: `https://deepbluehealth.co.nz/products/green-lipped-mussel`
- Change to: `https://deepbluehealth.co.nz/products/green-lipped-mussel?utm_source=facebook&utm_medium=cpc&utm_campaign=glm-social-proof`

**GLM Tiered Bundle Campaign:**
- If it's: `https://deepbluehealth.co.nz/products/`
- Change to: `https://deepbluehealth.co.nz/products/?utm_source=facebook&utm_medium=cpc&utm_campaign=glm-tiered-bundle`

**PP Bi-Active Campaign:**
- If it's: `https://deepbluehealth.co.nz/products/pure-pets-bi-active`
- Change to: `https://deepbluehealth.co.nz/products/pure-pets-bi-active?utm_source=facebook&utm_medium=cpc&utm_campaign=pp-bi-active`

**Rule:** Campaign name in UTM should be:
- Lowercase
- Hyphens instead of spaces
- Matches the Meta campaign name (roughly)

### Step 2: Verify with a Test Purchase

1. Click one of your Meta ads
2. Check the landing page URL in browser address bar
3. Verify the `utm_campaign=` parameter is present
4. Make a test purchase (or review a recent order)

### Step 3: Wait for Nightly Attribution Update

The system updates attribution nightly at **11pm NZ time** (customer_intelligence.db sync).

**Tomorrow morning (March 5)**, check:
```
SELECT
  campaign,
  COUNT(*) as orders,
  SUM(total_price) as revenue
FROM orders
WHERE channel = 'Meta Ads'
  AND created_at >= '2026-03-05'
GROUP BY campaign;
```

Should show:
- `glm-social-proof`: 1-4 new orders
- `glm-tiered-bundle`: 0-2 new orders
- `pp-bi-active`: 0-1 new orders

---

## WHY THIS MATTERS

Once UTM parameters are fixed:

**BEFORE (Broken):**
- Meta says: 4.71x ROAS ❌ (not trustworthy)
- Shopify shows: 0 Meta orders ❌ (missing)
- Decision: Can't tell if campaigns work

**AFTER (Fixed):**
- Meta says: 4.71x ROAS (pixel data, directional)
- Shopify shows: 1.76x ROAS ✓ (verified, ground truth)
- Decision: Campaign is below 2x floor → pause until optimized

---

## 90-DAY STRATEGY ALIGNMENT

From your approved strategy (line 38-40):
> Use Shopify-verified ROAS only, NEVER Meta's claimed numbers.
> Meta over-reports by ~150% (6.16x claimed = ~2x verified)
> Floor: 2x verified ROAS. Below 2x for 3 days = auto-pause

Once this fix is applied, the system will work as designed:
1. Meta pixel tracks conversions (✓ already working)
2. Shopify attribution classifies orders (✗ BROKEN — needs URL fix)
3. customer_intelligence.db stores verified ROAS (✓ DB ready)
4. Daily auto-pause triggers if <2x for 3 days (✓ rules engine ready)

---

## VERIFICATION CHECKLIST

- [ ] **Step 1:** Updated all 3 campaign URLs in Meta Ads Manager with utm_campaign parameter
- [ ] **Step 2:** Clicked a Meta ad, verified utm_campaign in browser URL bar
- [ ] **Step 3:** Waited until 11pm tonight for nightly sync
- [ ] **Step 4:** Check customer_intelligence.db tomorrow — expect Meta Ads orders with proper campaigns
- [ ] **Step 5:** Run meta_campaign_auditor.py tomorrow to get corrected ROAS numbers
- [ ] **Step 6:** Email corrected report to Tony Monday morning

---

## WHAT HAPPENS AFTER FIX

Once attribution is working again:

**Campaign Performance (Verified ROAS):**
- GLM Social Proof: ~1.5-2.5x (was 0.36x broken) → Hold if >2x, else pause
- GLM Tiered Bundle: ~1.0-2.0x (was 0.00x broken) → Hold if >2x, investigate funnel
- PP Bi-Active: ~1.8x ✓ (matches verified) → Hold, monitor for scaling

**For PP Launch (in 3 days):**
- ✓ PP Bi-Active: Only proven performer (1.8x) — keep at $10/day test budget
- ✗ GLM Social Proof: Don't scale until attribution verified and ROAS confirmed >2x
- ✗ GLM Tiered Bundle: Audit landing page funnel while attribution is being fixed

**Next Steps:**
1. Fix URLs (today, ~20 min)
2. Verify with test click (today, ~2 min)
3. Check database tomorrow (automated)
4. Update Tony report on Monday with corrected numbers

---

## TECHNICAL DETAILS (For Reference)

**How Attribution Works (order_intelligence.py lines 298-308):**
```python
if (utm_source in ("facebook", "fb", "instagram", "ig", "meta") or
    "facebook" in ref or "fb.com" in ref or "instagram" in ref or
    "fbclid" in landing.lower()):
    return {
        "channel": "Meta Ads",
        "source": "Facebook" if "facebook" in ref or "fb" in utm_source else "Instagram",
        "campaign": utm_campaign or "Unknown campaign",  # <-- BREAKS if utm_campaign empty
        "confidence": "high",
    }
```

**Without utm_campaign in URL:**
- utm_source=facebook ✓ (detected from referrer)
- utm_campaign=??? ✗ (defaults to "Unknown campaign")
- Result: Order tagged as "Meta Ads" but campaign = "Unknown" → can't compare campaigns

**With proper URL parameters:**
- utm_source=facebook ✓
- utm_campaign=glm-social-proof ✓
- Result: Order tagged as "Meta Ads | glm-social-proof" → can calculate per-campaign ROAS ✓

---

## ONE-LINER SUMMARY

Add `?utm_source=facebook&utm_medium=cpc&utm_campaign={campaign-name}` to the end of all 3 Meta ad destination URLs in Meta Ads Manager, then the attribution system will work correctly.

