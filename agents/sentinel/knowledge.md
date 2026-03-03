# Sentinel Knowledge — System Monitoring & Diagnostics

## 22-Agent System Overview
- **Agents:** 22 specialized agents running on schedules
- **Data sources:** Xero, Shopify, Klaviyo, Meta, Google Ads, Wise, etc.
- **Cron tasks:** 27+ scheduled tasks across 24 hours
- **Critical path:** Meridian, Odysseus, PREP need fresh data every morning

## Health Indicators

### Agent Staleness
- Normal: Agent state updated within last 6 hours (matches schedule)
- Stale: Agent not updated in 12+ hours (missed run or failure)
- Critical: Agent not updated in 24+ hours (definitely failed)

### Data Freshness
- Normal: Xero sync within 24h, Shopify within 2h, Klaviyo within 4h
- Stale: Data older than expected for that source
- Critical: No syncs in 24h or data clearly wrong

### Cron Task Completion
- Expected: 27 tasks scheduled, should complete on time
- Alert if: Task fails (check orchestrator logs why)
- Critical if: Morning critical tasks fail (7am Oracle, 6:30am Odysseus, etc.)

## Common Issues & Fixes
- **Xero sync failed:** Check API key, check Xero status, re-run manually
- **Shopify sync failed:** Check API scopes, check network, re-run manually
- **Agent didn't run:** Check orchestrator logs, check task schedule, check agent errors
- **Data looks wrong:** Compare across sources, check for anomalies, flag to domain expert
- **Context not fresh:** Check if agents updated before PREP needs to run

## Misalignment Detection
- If Meridian says revenue is $X but Odysseus says $Y → data quality issue
- If Asclepius says focus is high but brain protocol compliance is low → contradiction
- If Strategos is on day 30 but hasn't been updated in 2 weeks → stale
- If PREP is advising based on data older than 6 hours → context needs refresh

## Early Warning Patterns
- Agent update frequency declining → might indicate creeping failure
- Data sync latency increasing → might indicate API issue
- Cron task success rate dropping → might indicate system overload
- Misalignments appearing → might indicate data quality degradation
