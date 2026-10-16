# Meta Permissions

Configured available permissions:

- `pages_show_list`
- `business_management`
- `instagram_basic`
- `instagram_content_publish`
- `pages_read_engagement`
- `pages_read_user_content`
- `pages_manage_posts`

## Enabled

- Instagram content publishing when credentials are present and live mode is explicitly enabled.
- Facebook Page posting with `pages_manage_posts`.
- Page/engagement reads where Graph API returns metrics.

## Degraded Gracefully

- Missing credentials return `missing_credentials`/`unavailable`.
- Missing metrics are stored as unavailable and do not crash analytics.
- Comment engagement is disabled by default through `ENABLE_COMMENT_ENGAGEMENT=false`.

## Not Assumed

The system does not assume messaging or advanced moderation permissions. If comment replies or message handling are expanded later, add explicit permission checks before enabling.

