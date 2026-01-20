# Telegram Setup Guide

Enable Klabautermann as a Telegram bot for mobile access to your personal knowledge graph.

## Prerequisites

- Klabautermann installed and running locally
- Telegram account
- Telegram app (mobile or desktop)

## Step 1: Create a Telegram Bot

### 1.1 Start BotFather

1. Open Telegram and search for `@BotFather`
2. Start a conversation with `/start`

### 1.2 Create Your Bot

1. Send `/newbot` to BotFather
2. Choose a name for your bot (e.g., "My Klabautermann")
3. Choose a username ending in `bot` (e.g., `my_klabautermann_bot`)
4. **Save the API token** - you'll need this!

Example token format: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`

### 1.3 Configure Bot Settings (Optional)

Send these commands to BotFather to customize your bot:

```
/setdescription - Set bot description
/setabouttext - Set about text
/setuserpic - Set profile picture
```

## Step 2: Configure Klabautermann

### 2.1 Add Telegram Settings to .env

```bash
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your-bot-token-from-botfather
TELEGRAM_ALLOWED_USERS=your-telegram-user-id

# Optional: Webhook mode (for production)
# TELEGRAM_WEBHOOK_URL=https://your-domain.com/webhook
```

### 2.2 Find Your Telegram User ID

Your user ID is required for the whitelist. To find it:

1. Start a chat with `@userinfobot` on Telegram
2. It will reply with your user ID (numeric)
3. Add this ID to `TELEGRAM_ALLOWED_USERS`

For multiple users, separate IDs with commas:
```bash
TELEGRAM_ALLOWED_USERS=123456789,987654321
```

## Step 3: Run with Telegram

### 3.1 Start the Telegram Channel

```bash
uv run python -m klabautermann --channel telegram
```

Or run both CLI and Telegram:
```bash
uv run python -m klabautermann --channel cli --channel telegram
```

### 3.2 Test the Connection

1. Open Telegram and find your bot by username
2. Send `/start`
3. Try a message: "Hello Klabautermann"

## Security Considerations

### User Whitelist

**Important**: Only whitelisted users can interact with your bot. This prevents unauthorized access to your personal knowledge graph.

```bash
# Only allow specific users
TELEGRAM_ALLOWED_USERS=123456789
```

### Token Security

- **Never commit your bot token** to version control
- Store tokens in `.env` (which is gitignored)
- Rotate tokens if compromised via BotFather `/revoke`

### Network Security

For production deployments:
- Use HTTPS webhook instead of polling
- Consider running behind a reverse proxy
- Enable rate limiting

## Webhook Mode (Production)

For better reliability in production, use webhook mode:

### 1. Set Up Domain

You need a domain with HTTPS. Use services like:
- Cloudflare Tunnel
- ngrok (for testing)
- Your own server with Let's Encrypt

### 2. Configure Webhook

```bash
TELEGRAM_WEBHOOK_URL=https://your-domain.com/telegram/webhook
TELEGRAM_WEBHOOK_PORT=8443
```

### 3. Run in Webhook Mode

```bash
uv run python -m klabautermann --channel telegram --telegram-mode webhook
```

## Troubleshooting

### Bot Not Responding

1. **Check token**: Verify `TELEGRAM_BOT_TOKEN` is correct
2. **Check whitelist**: Ensure your user ID is in `TELEGRAM_ALLOWED_USERS`
3. **Check logs**: Run with `LOG_LEVEL=DEBUG`

### "Unauthorized" Errors

- Your user ID is not in the whitelist
- Find your correct user ID with `@userinfobot`

### Connection Timeout

- Check internet connectivity
- Telegram API might be blocked in your region
- Try using a VPN or proxy

### Webhook Issues

- Verify SSL certificate is valid
- Check port is open and accessible
- Test webhook URL manually

## Advanced Configuration

### Custom Commands

Define bot commands in BotFather:

```
/setcommands

help - Get help
status - Show system status
search - Search knowledge graph
```

### Message Formatting

Klabautermann supports Telegram markdown:

```
*bold text*
_italic text_
`code`
```

### Rate Limiting

Configure rate limits to prevent abuse:

```bash
TELEGRAM_RATE_LIMIT=30  # messages per minute
TELEGRAM_RATE_WINDOW=60  # window in seconds
```

## Next Steps

- [Configuration Guide](CONFIGURATION.md) - More settings
- [Troubleshooting](TROUBLESHOOTING.md) - Common issues
- [Architecture](../specs/architecture/CHANNELS.md) - Channel internals
