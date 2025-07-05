"""
Main application entry point for Southern California Campsite Tracker.

Provides CLI interface for scraping, processing alerts, and running the dashboard.
Also serves as the web application entry point for deployment.
"""

import asyncio
import logging
import sys
from typing import List, Optional
from datetime import datetime, date, timedelta

import click
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config.settings import settings
from .config.parks import ParkEnum, get_all_parks
from .scraper.crawl4ai_client import Crawl4AIClient
from .database.supabase_client import SupabaseClient
from .database.models import CampsiteSearchQuery
from .notifications.alert_rules import AlertProcessor
from .notifications.email_alerts import EmailNotificationService
from .dashboard.calendar_view import dashboard

# Setup logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create main FastAPI app
app = FastAPI(
    title="Southern California Campsite Tracker",
    description="Monitor and track campsite availability across Southern California state parks",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the dashboard
app.mount("/", dashboard.app)


@click.group()
def cli():
    """Southern California Campsite Tracker CLI."""
    pass


@cli.command()
@click.option('--parks', multiple=True, help='Specific parks to scrape (default: all)')
@click.option('--days', default=30, help='Number of days ahead to scrape (default: 30)')
async def scrape(parks: tuple, days: int):
    """Scrape campsite availability data."""
    try:
        logger.info("Starting campsite availability scraping")
        
        # Determine parks to scrape
        if parks:
            park_list = [ParkEnum(park) for park in parks]
        else:
            park_list = get_all_parks()
        
        # Setup clients
        async with Crawl4AIClient() as scraper, SupabaseClient() as db:
            
            # Check MCP server connectivity
            crawl_healthy = await scraper.health_check()
            db_healthy = await db.health_check()
            
            if not crawl_healthy:
                logger.error("Crawl4AI MCP server not available")
                return
            
            if not db_healthy:
                logger.warning("Database connection issues - data may not be stored")
            
            # Create search query
            start_date = date.today()
            end_date = start_date + timedelta(days=days)
            
            query = CampsiteSearchQuery(
                parks=park_list,
                start_date=start_date,
                end_date=end_date
            )
            
            # Scrape each park
            total_scraped = 0
            for park in park_list:
                try:
                    logger.info(f"Scraping {park.value}")
                    
                    availability = await scraper.scrape_park_availability(
                        park, (start_date, end_date)
                    )
                    
                    if availability and db_healthy:
                        await db.store_availability_data(availability)
                        total_scraped += len(availability)
                        logger.info(f"Stored {len(availability)} records for {park.value}")
                    
                except Exception as e:
                    logger.error(f"Failed to scrape {park.value}: {e}")
                    continue
            
            logger.info(f"Scraping complete. Total records: {total_scraped}")
    
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        sys.exit(1)


@cli.command()
async def process_alerts():
    """Process alert rules and send notifications."""
    try:
        logger.info("Processing alert rules")
        
        async with SupabaseClient() as db:
            
            # Check database connectivity
            if not await db.health_check():
                logger.error("Database not available")
                return
            
            # Get recent availability data (last 2 hours)
            cutoff_time = datetime.utcnow() - timedelta(hours=2)
            
            all_availability = []
            for park in get_all_parks():
                availability = await db.get_availability_by_park(
                    park,
                    start_date=date.today(),
                    end_date=date.today() + timedelta(days=7)
                )
                
                # Filter to recent data
                recent_availability = [
                    avail for avail in availability
                    if avail.scraped_at >= cutoff_time
                ]
                
                all_availability.extend(recent_availability)
            
            if not all_availability:
                logger.info("No recent availability data found")
                return
            
            # Process alerts
            alert_processor = AlertProcessor(db)
            stats = await alert_processor.process_new_availability(all_availability)
            
            logger.info(f"Alert processing complete: {stats}")
    
    except Exception as e:
        logger.error(f"Alert processing failed: {e}")
        sys.exit(1)


@cli.command()
@click.option('--host', default='127.0.0.1', help='Host to bind to')
@click.option('--port', default=8000, help='Port to bind to')
async def dashboard(host: str, port: int):
    """Run the web dashboard."""
    try:
        logger.info(f"Starting dashboard on {host}:{port}")
        
        config = uvicorn.Config(
            "src.main:app",
            host=host,
            port=port,
            log_level=settings.log_level.lower(),
            reload=settings.debug
        )
        
        server = uvicorn.Server(config)
        await server.serve()
    
    except Exception as e:
        logger.error(f"Dashboard failed to start: {e}")
        sys.exit(1)


@cli.command()
async def worker():
    """Run as background worker for scheduled tasks."""
    try:
        logger.info("Starting background worker")
        
        while True:
            try:
                # Run scraping
                await scrape.callback(parks=(), days=30)
                
                # Wait 5 minutes then process alerts
                await asyncio.sleep(300)
                await process_alerts.callback()
                
                # Wait remainder of 30 minutes
                await asyncio.sleep(1500)  # 25 minutes
                
            except Exception as e:
                logger.error(f"Worker cycle failed: {e}")
                await asyncio.sleep(600)  # Wait 10 minutes on error
    
    except KeyboardInterrupt:
        logger.info("Worker stopped")
    except Exception as e:
        logger.error(f"Worker failed: {e}")
        sys.exit(1)


@cli.command()
async def setup():
    """Setup database and initial configuration."""
    try:
        logger.info("Setting up campsite tracker")
        
        async with SupabaseClient() as db:
            # Test database connection
            if await db.health_check():
                logger.info("✅ Database connection successful")
            else:
                logger.error("❌ Database connection failed")
                return
        
        # Test email service
        email_service = EmailNotificationService()
        if await email_service.test_email_connection():
            logger.info("✅ Email service configured")
        else:
            logger.warning("⚠️ Email service not configured")
        
        # Test Crawl4AI
        async with Crawl4AIClient() as scraper:
            if await scraper.health_check():
                logger.info("✅ Crawl4AI MCP server available")
            else:
                logger.warning("⚠️ Crawl4AI MCP server not available")
        
        logger.info("Setup complete!")
    
    except Exception as e:
        logger.error(f"Setup failed: {e}")
        sys.exit(1)


@cli.command()
@click.option('--email', required=True, help='Email address for alerts')
@click.option('--parks', multiple=True, help='Parks to monitor (default: all)')
@click.option('--weekend-only', is_flag=True, help='Only alert for weekend availability')
async def create_alert(email: str, parks: tuple, weekend_only: bool):
    """Create a new alert rule."""
    try:
        from .database.models import AlertRule, SiteTypeEnum
        
        # Determine parks
        if parks:
            park_list = [ParkEnum(park) for park in parks]
        else:
            park_list = get_all_parks()
        
        # Create alert rule
        alert_rule = AlertRule(
            user_email=email,
            parks=park_list,
            site_types=[SiteTypeEnum.TENT, SiteTypeEnum.RV],
            weekend_only=weekend_only,
            min_nights=1,
            max_price=100.0
        )
        
        async with SupabaseClient() as db:
            rule_id = await db.create_alert_rule(alert_rule)
            logger.info(f"Created alert rule {rule_id} for {email}")
    
    except Exception as e:
        logger.error(f"Failed to create alert rule: {e}")
        sys.exit(1)


# Make CLI async-compatible
def run_async_command(func):
    """Run async click command."""
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))
    return wrapper

# Wrap async commands
for command in [scrape, process_alerts, dashboard, worker, setup, create_alert]:
    command.callback = run_async_command(command.callback)


if __name__ == "__main__":
    cli()