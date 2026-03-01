---
name: dbh-email-marketing
description: |
  Deep Blue Health email marketing skill for Klaviyo. Use for:
  - Writing email copy (campaigns, flows, promotions)
  - Creating Klaviyo campaigns/templates via API
  - Building automated flows (welcome, abandoned cart, post-purchase, winback)
  - Analysing email performance and optimising
  - Flash sales, product launches, educational content
  Triggers: email, Klaviyo, campaign, newsletter, flow, abandoned cart, welcome series, winback, EDM, subject line, email marketing, promotional email, Deep Blue Health
---

# Deep Blue Health Email Marketing

## Quick Start

1. **Identify email type**: Flow (automated) or Campaign (one-off)?
2. **Check brand voice**: See [references/brand-voice.md](references/brand-voice.md)
3. **Reference products**: See [references/products.md](references/products.md) for USPs
4. **Use appropriate template**: See flows or campaigns reference

## Email Types

### Automated Flows
Triggered by customer behaviour. See [references/flows.md](references/flows.md)
- Welcome Series
- Abandoned Cart
- Browse Abandonment
- Post-Purchase
- Winback
- Review Request
- Replenishment

### Campaigns
One-off sends. See [references/campaigns.md](references/campaigns.md)
- Flash Sales / Promotions
- Product Launches
- Educational Content
- Seasonal
- VIP/Loyalty

## Core Principles

```
DO:
- Lead with benefit, not feature
- Use "you" more than "we"
- Keep paragraphs to 1-3 sentences
- One primary CTA per email
- Include specific NZ ingredient origins (Marlborough Sounds, Wanaka Alps, Nelson)
- Reference customer's purchase history when relevant
- Sign off warmly and personally

DON'T:
- Use salesy language ("BUY NOW!!!")
- Make unsubstantiated health claims
- Use emojis excessively (max 1-2 per email)
- Write walls of text
- Forget mobile-first design
- Use generic stock phrases
```

## Klaviyo Integration

### Creating Campaigns via API

```python
# Create campaign
klaviyo_create_campaign(input={
    "type": "campaign",
    "attributes": {
        "name": "Campaign Name",
        "channel": "email",
        "audiences": {
            "included": ["LIST_ID"],
            "excluded": []
        }
    }
})

# Create template, then assign to campaign message
template_id = klaviyo_create_email_template(
    name="Template Name",
    html="<html>...</html>"
)
klaviyo_assign_template_to_campaign_message(
    campaignMessageId="MESSAGE_ID",
    emailTemplateId=template_id
)
```

See [references/klaviyo-api.md](references/klaviyo-api.md) for full API patterns.

### Performance Analysis

Use `klaviyo_get_campaign_report` and `klaviyo_get_flow_report` for metrics.

Key benchmarks for supplements industry:
- Open rate: 25-35% (good), 35%+ (excellent)
- Click rate: 2-4% (good), 4%+ (excellent)
- Revenue per recipient: Track trend over time

See [references/analytics.md](references/analytics.md) for analysis framework.

## HTML Email Structure

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0; padding:0; background-color:#f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
            <td align="center" style="padding:20px;">
                <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;">
                    <!-- Header -->
                    <tr>
                        <td align="center" style="padding:20px; background:#003366;">
                            <img src="LOGO_URL" alt="Deep Blue Health" width="150">
                        </td>
                    </tr>
                    <!-- Content -->
                    <tr>
                        <td style="padding:30px; font-family:Arial,sans-serif; font-size:16px; line-height:1.6; color:#333333;">
                            {{ content }}
                        </td>
                    </tr>
                    <!-- CTA -->
                    <tr>
                        <td align="center" style="padding:20px;">
                            <a href="{{ cta_url }}" style="background:#4CAF50; color:#ffffff; padding:15px 30px; text-decoration:none; border-radius:5px; font-weight:bold;">
                                {{ cta_text }}
                            </a>
                        </td>
                    </tr>
                    <!-- Footer -->
                    <tr>
                        <td style="padding:20px; background:#f5f5f5; font-size:12px; color:#666666; text-align:center;">
                            Deep Blue Health | 36C Apollo Drive, Mairangi Bay, Auckland<br>
                            <a href="{{ unsubscribe }}">Unsubscribe</a>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
```

## Reference Files

| File | Use When |
|------|----------|
| [brand-voice.md](references/brand-voice.md) | Writing any email copy |
| [products.md](references/products.md) | Featuring specific products |
| [flows.md](references/flows.md) | Building automated sequences |
| [campaigns.md](references/campaigns.md) | Creating one-off campaigns |
| [subject-lines.md](references/subject-lines.md) | Crafting subject lines |
| [klaviyo-api.md](references/klaviyo-api.md) | Using Klaviyo API |
| [analytics.md](references/analytics.md) | Analysing performance |
