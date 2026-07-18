# Embed Widget Integration Guide

Add an AI-powered chat widget to any website in minutes. The embed widget
connects to your Nexus Agent backend and provides a full conversational
interface for your users.

---

## Quick Start

Copy and paste this snippet just before the closing `</body>` tag:

```html
<script src="https://your-api.com/embed/widget.js"
  data-token="nex_abc123..."
  data-api-url="https://your-api.com">
</script>
```

That's it. A floating chat button appears in the bottom-right corner of your
site. Click it to open the chat panel.

> **Before you start**: Generate an embed token from the **Embed Generator**
> page in the management console, or via the API (see below).

---

## Generating an Embed Token

### Via the Management Console

1. Navigate to **Embed Generator** (`/embed`)
2. Configure the widget appearance and security settings
3. Click **Generate Token**
4. Copy the generated script snippet

### Via the API

```bash
curl -X POST https://your-api.com/api/v1/embeds \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Website Chat",
    "allowed_domains": ["example.com", "www.example.com"],
    "theme": "light",
    "primary_color": "#2563eb",
    "welcome_message": "Hi! How can I help you today?",
    "rate_limit": 30
  }'
```

Response:
```json
{
  "embed_id": "550e8400-e29b-41d4-a716-446655440000",
  "token": "nex_abc123def456ghi789...",
  "script_url": "https://your-api.com/embed/widget.js?token=nex_abc123...",
  "created_at": "2026-07-19T12:00:00Z"
}
```

---

## Full Configuration Reference

All widget settings are configured via `data-*` attributes on the script tag.

| Attribute | Required | Default | Description |
|-----------|----------|---------|-------------|
| `data-token` | **Yes** | — | Embed token generated from the API |
| `data-api-url` | **Yes** | — | Your Nexus Agent backend URL |
| `data-theme` | No | `light` | `light`, `dark`, or `custom` |
| `data-primary-color` | No | `#2563eb` | Primary brand color (hex) |
| `data-position` | No | `bottom-right` | `bottom-right`, `bottom-left` |
| `data-welcome-message` | No | `Hello! How can I help you today?` | Initial greeting |
| `data-max-height` | No | `600` | Max chat panel height in pixels |
| `data-max-width` | No | `380` | Max chat panel width in pixels |
| `data-custom-css` | No | — | Base64-encoded custom CSS overrides |
| `data-allowed-domains` | No | — | Comma-separated domain whitelist override |

### Advanced: Programmatic Initialization

For single-page apps or dynamic sites, initialize the widget via JavaScript:

```html
<script src="https://your-api.com/embed/widget.js"></script>
<script>
  NexusEmbed.init({
    apiUrl: "https://your-api.com",
    token: "nex_abc123...",
    theme: "dark",
    primaryColor: "#6366f1",
    position: "bottom-right",
    welcomeMessage: "Need help? Ask me anything!",
    maxHeight: 600,
    maxWidth: 380,
  });
</script>
```

---

## Security Best Practices

### 1. Unique Tokens Per Instance

Generate a **separate token** for each website or environment. This lets you
revoke access per-instance without affecting others.

```bash
# Good: one token per site
curl -X POST ... -d '{"name": "production-site"}'
curl -X POST ... -d '{"name": "staging-site"}'

# Bad: reuse the same token everywhere
```

### 2. Restrict Allowed Domains

Always set `allowed_domains` to your own origins. The middleware validates
the `Origin` header against this list and blocks requests from unknown domains.

```json
{
  "allowed_domains": ["example.com", "www.example.com", "app.example.com"]
}
```

Use `*` only during development. Never use it in production.

### 3. Set Rate Limits

Configure `rate_limit` (messages per minute) appropriate for your traffic.
Typical values:

| Traffic Level | Rate Limit |
|---------------|-----------|
| Low (personal site) | 10–30 |
| Medium (business site) | 60–120 |
| High (public SaaS) | 300+ |

### 4. Rotate Tokens

Generate new tokens periodically (e.g., every 90 days) and revoke old ones.
Old tokens continue to work until revoked.

```bash
curl -X DELETE https://your-api.com/api/v1/embeds/$EMBED_ID \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### 5. Use HTTPS

Always serve the widget over HTTPS. The token is sent as a query parameter
and is encrypted in transit.

---

## Customization Examples

### Dark Theme

```html
<script src="https://your-api.com/embed/widget.js"
  data-token="nex_..."
  data-api-url="https://your-api.com"
  data-theme="dark"
  data-primary-color="#818cf8">
</script>
```

### Bottom-Left Position with Custom Message

```html
<script
  src="https://your-api.com/embed/widget.js"
  data-token="nex_..."
  data-api-url="https://your-api.com"
  data-position="bottom-left"
  data-welcome-message="Welcome to our support! How can we help?">
</script>
```

### Brand Color + Custom CSS

```html
<script
  src="https://your-api.com/embed/widget.js"
  data-token="nex_..."
  data-api-url="https://your-api.com"
  data-primary-color="#e11d48"
  data-custom-css="Lm5leHVzLXdpZGdldCAuY2hhdC1oZWFkZXIgeyBib3JkZXItcmFkaXVzOiAyNHB4OyB9">
</script>
```

The `data-custom-css` value is base64-encoded. Generate it with:

```bash
echo -n '.nexus-widget .chat-header { border-radius: 24px; }' | base64
```

---

## Analytics

The embed widget tracks usage per token. Query analytics via the API:

```bash
curl -X GET https://your-api.com/api/v1/embeds/$EMBED_ID/analytics \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Response:
```json
{
  "message_count": 1523,
  "active_sessions": 12,
  "avg_session_duration_s": 247.5
}
```

| Metric | Description |
|--------|-------------|
| `message_count` | Total messages sent through this embed |
| `active_sessions` | Currently active WebSocket sessions |
| `avg_session_duration_s` | Average conversation length in seconds |

---

## Troubleshooting

| Symptom | Likely Cause | Solution |
|---------|-------------|----------|
| Widget doesn't appear | Invalid or revoked token | Generate a new token from the console |
| Browser console: `403` | Domain not in `allowed_domains` | Add your domain to the widget config |
| Browser console: `429` | Rate limit exceeded | Increase `rate_limit` or wait 60s |
| Widget appears but says "Server unreachable" | CORS or network issue | Check `data-api-url` is correct and accessible |
| Styling looks broken | CSS conflict with host site | Use `data-custom-css` with higher specificity |
| Chat history lost on refresh | Session not persisted | Embed widget uses per-session state |

### Common CORS Issues

If you see CORS errors in the browser console:

1. Verify the domain is in the widget's `allowed_domains` list
2. Ensure the backend's `cors_origins` setting includes your domain (or `*` for dev)
3. Check that the request includes `Origin` header matching `allowed_domains`

### Debug Mode

Add `data-debug="true"` to the script tag to enable verbose console logging:

```html
<script src="https://your-api.com/embed/widget.js"
  data-token="nex_..."
  data-api-url="https://your-api.com"
  data-debug="true">
</script>
```

---

## Platform Integration Examples

### Plain HTML

```html
<!DOCTYPE html>
<html>
<head>
  <title>My Site</title>
</head>
<body>
  <h1>Welcome</h1>
  <p>Content here...</p>

  <!-- Embed widget -->
  <script src="https://your-api.com/embed/widget.js"
    data-token="nex_..."
    data-api-url="https://your-api.com">
  </script>
</body>
</html>
```

### React / Next.js

```tsx
import { useEffect } from "react";

export default function Layout({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    // @ts-expect-error NexusEmbed is loaded from external script
    if (window.NexusEmbed) {
      window.NexusEmbed.init({
        apiUrl: process.env.NEXT_PUBLIC_API_URL!,
        token: process.env.NEXT_PUBLIC_EMBED_TOKEN!,
        theme: "light",
      });
    } else {
      // Script hasn't loaded yet — poll or use a callback
      const check = setInterval(() => {
        if (window.NexusEmbed) {
          window.NexusEmbed.init({
            apiUrl: process.env.NEXT_PUBLIC_API_URL!,
            token: process.env.NEXT_PUBLIC_EMBED_TOKEN!,
          });
          clearInterval(check);
        }
      }, 200);
    }
  }, []);

  return <>{children}</>;
}
```

### WordPress

Add to your theme's `functions.php`:

```php
add_action('wp_footer', function() {
  if (is_admin()) return;
  $token = get_option('nexus_embed_token');
  $api_url = get_option('nexus_api_url');
  if (!$token || !$api_url) return;
  ?>
  <script src="<?php echo esc_url($api_url); ?>/embed/widget.js"
    data-token="<?php echo esc_attr($token); ?>"
    data-api-url="<?php echo esc_url($api_url); ?>"
    data-theme="light">
  </script>
  <?php
});
```

Or use a plugin like **Insert Headers and Footers** to paste the script tag.

### Shopify

In your Shopify theme, edit `theme.liquid` and add before `</body>`:

```liquid
{% if request.page_type != 'customers' %}
  <script src="{{ settings.nexus_api_url }}/embed/widget.js"
    data-token="{{ settings.nexus_embed_token }}"
    data-api-url="{{ settings.nexus_api_url }}">
  </script>
{% endif %}
```

Add the settings in `config/settings_schema.json`:

```json
{
  "name": "Chat Widget",
  "settings": [
    {
      "type": "text",
      "id": "nexus_embed_token",
      "label": "Embed Token"
    },
    {
      "type": "text",
      "id": "nexus_api_url",
      "label": "API URL",
      "default": "https://your-api.com"
    }
  ]
}
```

### Webflow

1. Go to **Site Settings** → **Custom Code**
2. Paste the script tag in the **Footer Code** section
3. Click **Save Changes**

```html
<script src="https://your-api.com/embed/widget.js"
  data-token="nex_..."
  data-api-url="https://your-api.com">
</script>
```

### Wix

1. Go to **Settings** → **Advanced** → **Custom Code**
2. Click **+ Add Custom Code**
3. Paste the script tag
4. Set **Where to add the code** to `All pages`
5. Click **Apply**
