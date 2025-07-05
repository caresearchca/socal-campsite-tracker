# 🏕️ Southern California Campsite Tracker

Monitor and track campsite availability across Southern California state parks including Joshua Tree, Carlsbad, and Oceanside. Get real-time alerts when weekend spots become available!

## 🚀 Features

- **JavaScript-Aware Scraping**: Uses Crawl4AI RAG MCP for scraping JavaScript-heavy reservecalifornia.com
- **Real-Time Alerts**: Email notifications when campsites match your preferences
- **Calendar Dashboard**: Visual calendar showing availability trends
- **Weekend Focus**: Special handling for highly competitive weekend slots
- **Multi-Park Monitoring**: Tracks Joshua Tree, Carlsbad, and Oceanside simultaneously
- **Automated Scheduling**: GitHub Actions run scraping every 30 minutes

## 🏗️ Architecture

- **Scraping**: Crawl4AI RAG MCP server for JavaScript rendering
- **Database**: Supabase for data storage and user management
- **Notifications**: Email alerts with HTML templates
- **Dashboard**: FastAPI web interface with calendar visualization
- **Deployment**: DigitalOcean App Platform with GitHub Actions

## 🛠️ Quick Setup

### Prerequisites

1. **MCP Servers**: You need these MCP servers configured:
   - Crawl4AI RAG MCP running on `http://localhost:8051/sse`
   - Supabase MCP with your project credentials
   - GitHub MCP (optional, for automated deployments)
   - DigitalOcean MCP (optional, for hosting)

2. **Environment Variables**: Copy from your existing `.mcp.json`:
   ```bash
   cp .env.example .env
   # Edit .env with your actual credentials
   ```

### Local Development

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Setup Database**:
   ```bash
   python -m src.main setup
   ```

3. **Run Dashboard**:
   ```bash
   python -m src.main dashboard --host 0.0.0.0 --port 8000
   ```
   
   Access at: http://localhost:8000

4. **Test Scraping**:
   ```bash
   python -m src.main scrape --parks joshua_tree --days 7
   ```

5. **Create Alert Rule**:
   ```bash
   python -m src.main create-alert --email your@email.com --weekend-only
   ```

## 🌐 Online Deployment

### Option 1: DigitalOcean App Platform (Recommended)

1. **Fork this repository** to your GitHub account

2. **Configure Secrets** in your GitHub repository:
   - Go to Settings → Secrets and Variables → Actions
   - Add these secrets:
     ```
     CRAWL4AI_MCP_URL=http://localhost:8051/sse
     SUPABASE_PROJECT_REF=gzkxecewlnfnnoutmcuu
     SUPABASE_ACCESS_TOKEN=your-supabase-token
     DIGITALOCEAN_API_TOKEN=your-do-token
     NOTIFICATION_EMAIL=your@email.com
     SMTP_USERNAME=your-smtp-user
     SMTP_PASSWORD=your-smtp-password
     SECRET_KEY=your-secret-key-32-chars-min
     ```

3. **Update App Configuration**:
   - Edit `.do/app.yaml` 
   - Replace `caresearchca/socal-campsite-tracker` with your repo

4. **Deploy**:
   - Push to `main` branch
   - GitHub Actions will automatically deploy to DigitalOcean
   - Access your app at: `https://socal-campsite-tracker.ondigitalocean.app`

### Option 2: Docker Deployment

```bash
# Build image
docker build -t campsite-tracker .

# Run with environment variables
docker run -p 8080:8080 \
  -e SUPABASE_PROJECT_REF=your-project-ref \
  -e SUPABASE_ACCESS_TOKEN=your-token \
  -e NOTIFICATION_EMAIL=your@email.com \
  campsite-tracker
```

## 📅 Automated Scraping

The system automatically:
- **Scrapes every 30 minutes** via GitHub Actions
- **Processes alerts** after each scrape
- **Sends email notifications** for matching availability
- **Stores historical data** for trend analysis

## 🎯 Usage Examples

### Monitor Specific Parks
```bash
python -m src.main scrape --parks joshua_tree --parks carlsbad --days 14
```

### Weekend-Only Alerts
```bash
python -m src.main create-alert \
  --email camper@example.com \
  --weekend-only \
  --parks joshua_tree
```

### Run Background Worker
```bash
python -m src.main worker
```

## 📊 Dashboard Features

- **Calendar View**: Monthly calendar with availability indicators
- **Park Filtering**: View specific parks or all parks
- **Weekend Highlighting**: Special indicators for weekend availability
- **Price Information**: Shows minimum prices when available
- **Statistics**: Monthly totals and weekend availability counts

## 🔧 Configuration

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `CRAWL4AI_MCP_URL` | Crawl4AI RAG MCP server URL | `http://localhost:8051/sse` |
| `SUPABASE_PROJECT_REF` | Supabase project reference | `gzkxecewlnfnnoutmcuu` |
| `SUPABASE_ACCESS_TOKEN` | Supabase access token | `sbp_...` |
| `NOTIFICATION_EMAIL` | Email for notifications | `your@email.com` |
| `SMTP_USERNAME` | SMTP username | `your@gmail.com` |
| `SMTP_PASSWORD` | SMTP password/app password | `your-app-password` |
| `SCRAPE_INTERVAL_MINUTES` | Scraping frequency | `30` |
| `ALERT_COOLDOWN_HOURS` | Hours between repeat alerts | `24` |

### Email Configuration

For Gmail:
1. Enable 2-factor authentication
2. Generate an App Password: https://myaccount.google.com/apppasswords
3. Use the app password as `SMTP_PASSWORD`

## 🚨 Important Notes

### Rate Limiting
- **Respectful Scraping**: 30-minute intervals to avoid overwhelming servers
- **Exponential Backoff**: Automatic retry with increasing delays
- **Error Handling**: Continues operation even with temporary failures

### California Parks Booking
- **6-Month Release**: Sites become available exactly 6 months in advance at 8 AM PST
- **Instant Booking**: Popular weekend spots often book within seconds
- **Friday-Sunday**: Weekend alerts include Friday for long weekends

## 🧪 Testing

```bash
# Test MCP connectivity
python -m src.main setup

# Test email alerts
python -c "
from src.notifications.email_alerts import EmailNotificationService
import asyncio
service = EmailNotificationService()
asyncio.run(service.test_email_connection())
"

# Test scraping (dry run)
python -m src.main scrape --parks joshua_tree --days 1
```

## 📝 API Endpoints

When running the dashboard:

- `GET /` - Main dashboard
- `GET /calendar` - Calendar view with filters
- `GET /api/parks` - List available parks
- `GET /api/availability/{park}` - Get park availability
- `GET /health` - Health check

## 🔍 Monitoring

### Logs
```bash
# View real-time logs (if deployed)
doctl apps logs socal-campsite-tracker --follow

# Local logs
python -m src.main dashboard --log-level DEBUG
```

### Health Checks
- Dashboard: `/health` endpoint
- Database: Automatic connectivity testing
- Email: Built-in SMTP testing
- Crawl4AI: MCP server health checks

## 🆘 Troubleshooting

### Common Issues

1. **Crawl4AI Not Available**:
   - Ensure Crawl4AI RAG MCP server is running
   - Check URL: `http://localhost:8051/sse`

2. **Database Connection Failed**:
   - Verify Supabase credentials
   - Check project ref and access token

3. **Email Not Sending**:
   - Verify SMTP credentials
   - For Gmail, use App Password not regular password

4. **No Availability Data**:
   - ReserveCalifornia.com may be blocking requests
   - Check scraping logs for errors
   - Verify site structure hasn't changed

### Debug Mode
```bash
DEBUG=true python -m src.main dashboard
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details.

## 🎉 Enjoy Camping!

Now you can monitor Southern California's most popular campsites automatically and never miss a weekend opportunity again! 🏕️

---

**Live Dashboard**: https://socal-campsite-tracker.ondigitalocean.app (after deployment)
**GitHub Pages Demo**: https://caresearchca.github.io/socal-campsite-tracker/

**Support**: Create an issue on GitHub if you need help!