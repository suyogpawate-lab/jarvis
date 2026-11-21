# JARVIS social integrations

The social manager is loaded by the normal FastAgent startup and exposes three natural-language tools:

- `social_accounts`: reports configured credentials and account-type boundaries.
- `social_review`: collects a bounded feed sample, filters Reddit mature posts, deduplicates, ranks against a topic, and returns source links.
- `social_manage`: performs only supported actions when the user directly requests the exact action.

## Credentials

Put credentials in the private `~/jarvis/.env` file. Never commit tokens.

| Variable | Purpose |
|---|---|
| `JARVIS_GITHUB_TOKEN` | GitHub notifications and repository starring; use a token with only required repository/notification permissions |
| `JARVIS_REDDIT_ACCESS_TOKEN` | Reddit OAuth access token for reading the authenticated user's best feed |
| `JARVIS_REDDIT_USER_AGENT` | Optional descriptive Reddit API user agent |
| `JARVIS_YOUTUBE_ACCESS_TOKEN` | YouTube OAuth token; read subscriptions and uploads, plus `youtube.force-ssl` for like/unlike |
| `JARVIS_META_ACCESS_TOKEN` | Optional shared Meta token fallback |
| `JARVIS_FACEBOOK_PAGE_ACCESS_TOKEN` | Preferred Facebook Page access token; needs Page publishing/read permissions |
| `JARVIS_INSTAGRAM_ACCESS_TOKEN` | Preferred Instagram professional-account token; needs the relevant `instagram_business_*` scopes |
| `JARVIS_FACEBOOK_PAGE_ID` | Facebook Page ID; personal-profile feed access is not provided |
| `JARVIS_INSTAGRAM_USER_ID` | Instagram Business/Creator account ID |
| `JARVIS_INSTAGRAM_API_HOST` | Optional; defaults to `https://graph.instagram.com` |
| `JARVIS_META_GRAPH_VERSION` | Optional Graph API version; defaults to `v26.0` |
| `JARVIS_LINKEDIN_ACCESS_TOKEN` | LinkedIn OAuth access token |
| `JARVIS_LINKEDIN_PERSON_URN` | LinkedIn member URN for member publishing and attempted member-post reading |
| `JARVIS_LINKEDIN_VERSION` | Optional LinkedIn API version; defaults to `202610` |

This first implementation consumes OAuth tokens supplied in the environment; it does not yet provide an in-app OAuth consent/callback wizard or refresh-token lifecycle. An account is marked configured when the relevant variables exist, not when the provider has validated them. Provider app setup, OAuth consent, scopes, app review, and token renewal remain necessary.

## Supported actions

- GitHub: star/unstar a repository.
- YouTube: like/unlike a video.
- Facebook: publish text to the configured Page.\n- LinkedIn: publish text on the authenticated member profile with `w_member_social`; member-feed reading needs restricted `r_member_social` access.
- Instagram: publish a single image with caption to a configured Business/Creator account using a publicly reachable HTTPS image URL.

Reddit voting is deliberately not automated. LinkedIn member publishing uses `w_member_social`; member-feed reading requires the restricted `r_member_social` permission, which LinkedIn currently treats as closed to new access requests. Organization capabilities depend on approved Community Management access and Page roles. No personal Instagram feed API is available for ordinary consumer accounts. Facebook personal-profile feed access is not implemented.

The manager uses the existing `requests` dependency and tool registry; it adds no service, daemon, model, or heavyweight dependency. All social actions require the model to pass `confirmed=true` and the agent prompt instructs it to do so only for an explicit user request.
