"""
Calendar dashboard for campsite availability visualization.

Provides a web-based calendar interface showing availability trends
and allowing users to view availability data across different parks.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timedelta
from calendar import monthrange

from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config.settings import settings
from ..config.parks import ParkEnum, get_park_info, get_all_parks
from ..database.models import CampsiteAvailability, AvailabilityStatus, SiteTypeEnum
from ..database.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


class CalendarDayData(BaseModel):
    """Data for a single calendar day."""
    date: date
    available_count: int = 0
    total_sites: int = 0
    weekend: bool = False
    sites: List[CampsiteAvailability] = []
    avg_price: Optional[float] = None
    min_price: Optional[float] = None


class CalendarMonthData(BaseModel):
    """Data for a calendar month."""
    year: int
    month: int
    month_name: str
    days: List[CalendarDayData]
    parks: List[str]
    total_available: int = 0
    weekend_available: int = 0


class DashboardAPI:
    """
    FastAPI application for the campsite availability dashboard.
    
    Provides REST endpoints and web interface for viewing availability data.
    """
    
    def __init__(self):
        """Initialize the dashboard API."""
        self.app = FastAPI(
            title="Southern California Campsite Tracker",
            description="Monitor and track campsite availability across Southern California state parks",
            version="1.0.0"
        )
        
        self.db_client = SupabaseClient()
        
        # Setup templates and static files
        self.templates = Jinja2Templates(directory="src/dashboard/templates")
        
        # Setup routes
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup FastAPI routes."""
        
        @self.app.get("/", response_class=HTMLResponse)
        async def dashboard_home(request: Request):
            """Main dashboard page."""
            return await self.render_calendar_page(request)
        
        @self.app.get("/calendar", response_class=HTMLResponse)
        async def calendar_page(
            request: Request,
            year: int = Query(default=None),
            month: int = Query(default=None),
            park: str = Query(default="all")
        ):
            """Calendar view page."""
            return await self.render_calendar_page(request, year, month, park)
        
        @self.app.get("/api/availability/{park}")
        async def get_park_availability(
            park: str,
            start_date: str = Query(...),
            end_date: str = Query(...),
            site_type: Optional[str] = Query(default=None)
        ):
            """Get availability data for a specific park."""
            try:
                park_enum = ParkEnum(park)
                start = datetime.fromisoformat(start_date).date()
                end = datetime.fromisoformat(end_date).date()
                
                site_types = [SiteTypeEnum(site_type)] if site_type else None
                
                availability = await self.get_availability_data(
                    park_enum, start, end, site_types
                )
                
                return {
                    'park': park,
                    'start_date': start_date,
                    'end_date': end_date,
                    'availability': [avail.dict() for avail in availability]
                }
                
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                logger.error(f"Error getting availability: {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
        
        @self.app.get("/api/calendar/{year}/{month}")
        async def get_calendar_data(
            year: int,
            month: int,
            parks: str = Query(default="all")
        ):
            """Get calendar data for a specific month."""
            try:
                park_list = []
                if parks != "all":
                    park_names = parks.split(",")
                    park_list = [ParkEnum(name.strip()) for name in park_names]
                else:
                    park_list = get_all_parks()
                
                calendar_data = await self.generate_calendar_data(year, month, park_list)
                return calendar_data.dict()
                
            except Exception as e:
                logger.error(f"Error generating calendar data: {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
        
        @self.app.get("/api/parks")
        async def get_parks():
            """Get list of available parks."""
            parks = []
            for park in get_all_parks():
                park_info = get_park_info(park)
                parks.append({
                    'id': park.value,
                    'name': park_info.display_name,
                    'region': park_info.region
                })
            return {'parks': parks}
        
        @self.app.get("/health")
        async def health_check():
            """Health check endpoint."""
            db_healthy = await self.db_client.health_check()
            return {
                'status': 'healthy' if db_healthy else 'degraded',
                'database': 'connected' if db_healthy else 'disconnected',
                'timestamp': datetime.utcnow().isoformat()
            }
    
    async def render_calendar_page(
        self,
        request: Request,
        year: Optional[int] = None,
        month: Optional[int] = None,
        park: str = "all"
    ) -> HTMLResponse:
        """Render the calendar page with availability data."""
        try:
            # Default to current month if not specified
            now = datetime.now()
            year = year or now.year
            month = month or now.month
            
            # Get park list
            if park == "all":
                park_list = get_all_parks()
            else:
                try:
                    park_list = [ParkEnum(park)]
                except ValueError:
                    park_list = get_all_parks()
            
            # Generate calendar data
            calendar_data = await self.generate_calendar_data(year, month, park_list)
            
            # Get park options for dropdown
            park_options = []
            for p in get_all_parks():
                park_info = get_park_info(p)
                park_options.append({
                    'value': p.value,
                    'name': park_info.display_name,
                    'selected': p.value == park or (park == "all" and len(park_list) > 1)
                })
            
            context = {
                'request': request,
                'calendar_data': calendar_data,
                'current_year': year,
                'current_month': month,
                'selected_park': park,
                'park_options': park_options,
                'month_names': [
                    'January', 'February', 'March', 'April', 'May', 'June',
                    'July', 'August', 'September', 'October', 'November', 'December'
                ]
            }
            
            return self.templates.TemplateResponse("calendar.html", context)
            
        except Exception as e:
            logger.error(f"Error rendering calendar page: {e}")
            # Return a basic error page
            context = {
                'request': request,
                'error': str(e)
            }
            return self.templates.TemplateResponse("error.html", context)
    
    async def generate_calendar_data(
        self,
        year: int,
        month: int,
        parks: List[ParkEnum]
    ) -> CalendarMonthData:
        """Generate calendar data for a specific month."""
        try:
            # Get the first and last day of the month
            first_day = date(year, month, 1)
            last_day_num = monthrange(year, month)[1]
            last_day = date(year, month, last_day_num)
            
            # Get availability data for all parks in this month
            all_availability = []
            for park in parks:
                park_availability = await self.get_availability_data(
                    park, first_day, last_day
                )
                all_availability.extend(park_availability)
            
            # Generate calendar days
            calendar_days = []
            total_available = 0
            weekend_available = 0
            
            for day in range(1, last_day_num + 1):
                current_date = date(year, month, day)
                is_weekend = current_date.weekday() >= 5  # Saturday = 5, Sunday = 6
                
                # Get availability for this day
                day_availability = [
                    avail for avail in all_availability
                    if avail.check_in_date == current_date
                    and avail.status == AvailabilityStatus.AVAILABLE
                ]
                
                # Calculate statistics
                available_count = len(day_availability)
                total_sites = len([
                    avail for avail in all_availability
                    if avail.check_in_date == current_date
                ])
                
                # Calculate price statistics
                prices = [avail.price for avail in day_availability if avail.price]
                avg_price = sum(prices) / len(prices) if prices else None
                min_price = min(prices) if prices else None
                
                day_data = CalendarDayData(
                    date=current_date,
                    available_count=available_count,
                    total_sites=total_sites,
                    weekend=is_weekend,
                    sites=day_availability,
                    avg_price=avg_price,
                    min_price=min_price
                )
                
                calendar_days.append(day_data)
                total_available += available_count
                
                if is_weekend:
                    weekend_available += available_count
            
            # Create month data
            month_names = [
                'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December'
            ]
            
            return CalendarMonthData(
                year=year,
                month=month,
                month_name=month_names[month - 1],
                days=calendar_days,
                parks=[park.value for park in parks],
                total_available=total_available,
                weekend_available=weekend_available
            )
            
        except Exception as e:
            logger.error(f"Error generating calendar data: {e}")
            raise
    
    async def get_availability_data(
        self,
        park: ParkEnum,
        start_date: date,
        end_date: date,
        site_types: Optional[List[SiteTypeEnum]] = None
    ) -> List[CampsiteAvailability]:
        """Get availability data for a park and date range."""
        try:
            # Get availability from database
            availability = await self.db_client.get_availability_by_park(
                park, start_date, end_date
            )
            
            # Filter by site types if specified
            if site_types:
                availability = [
                    avail for avail in availability
                    if avail.site_type in site_types
                ]
            
            return availability
            
        except Exception as e:
            logger.error(f"Error getting availability data for {park}: {e}")
            return []


# Create dashboard templates
CALENDAR_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Southern California Campsite Tracker</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .header { text-align: center; margin-bottom: 30px; }
        .controls { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 10px; }
        .calendar { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; margin-bottom: 20px; }
        .calendar-header { background: #2c3e50; color: white; padding: 10px; text-align: center; font-weight: bold; }
        .calendar-day { background: white; border: 1px solid #ddd; min-height: 100px; padding: 5px; position: relative; }
        .calendar-day.weekend { background: #f8f9fa; }
        .calendar-day.has-availability { background: #d4edda; border-color: #c3e6cb; }
        .calendar-day.weekend.has-availability { background: #d1ecf1; border-color: #bee5eb; }
        .day-number { font-weight: bold; margin-bottom: 5px; }
        .availability-count { font-size: 12px; color: #28a745; }
        .weekend-indicator { font-size: 10px; color: #6c757d; }
        .stats { display: flex; justify-content: space-around; text-align: center; background: #f8f9fa; padding: 15px; border-radius: 5px; }
        .stat { flex: 1; }
        .stat-number { font-size: 24px; font-weight: bold; color: #2c3e50; }
        .stat-label { font-size: 12px; color: #6c757d; }
        select, button { padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; }
        button { background: #007bff; color: white; border-color: #007bff; cursor: pointer; }
        button:hover { background: #0056b3; }
        .legend { display: flex; gap: 20px; justify-content: center; margin-top: 15px; font-size: 12px; }
        .legend-item { display: flex; align-items: center; gap: 5px; }
        .legend-color { width: 15px; height: 15px; border: 1px solid #ddd; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏕️ Southern California Campsite Tracker</h1>
            <p>Monitor availability across Joshua Tree, Carlsbad, and Oceanside</p>
        </div>
        
        <div class="controls">
            <div>
                <select id="parkSelect">
                    <option value="all">All Parks</option>
                    {% for park in park_options %}
                    <option value="{{ park.value }}" {% if park.selected %}selected{% endif %}>{{ park.name }}</option>
                    {% endfor %}
                </select>
                
                <select id="monthSelect">
                    {% for i in range(12) %}
                    <option value="{{ i + 1 }}" {% if (i + 1) == current_month %}selected{% endif %}>
                        {{ month_names[i] }}
                    </option>
                    {% endfor %}
                </select>
                
                <select id="yearSelect">
                    {% for year in range(2024, 2026) %}
                    <option value="{{ year }}" {% if year == current_year %}selected{% endif %}>{{ year }}</option>
                    {% endfor %}
                </select>
                
                <button onclick="updateCalendar()">Update</button>
            </div>
            
            <div>
                <button onclick="window.location.reload()">Refresh Data</button>
            </div>
        </div>
        
        <div class="stats">
            <div class="stat">
                <div class="stat-number">{{ calendar_data.total_available }}</div>
                <div class="stat-label">Total Available</div>
            </div>
            <div class="stat">
                <div class="stat-number">{{ calendar_data.weekend_available }}</div>
                <div class="stat-label">Weekend Available</div>
            </div>
            <div class="stat">
                <div class="stat-number">{{ calendar_data.days|length }}</div>
                <div class="stat-label">Days in Month</div>
            </div>
        </div>
        
        <div class="calendar">
            <div class="calendar-header">Sun</div>
            <div class="calendar-header">Mon</div>
            <div class="calendar-header">Tue</div>
            <div class="calendar-header">Wed</div>
            <div class="calendar-header">Thu</div>
            <div class="calendar-header">Fri</div>
            <div class="calendar-header">Sat</div>
            
            {% for day in calendar_data.days %}
            <div class="calendar-day {% if day.weekend %}weekend{% endif %} {% if day.available_count > 0 %}has-availability{% endif %}">
                <div class="day-number">{{ day.date.day }}</div>
                {% if day.available_count > 0 %}
                <div class="availability-count">{{ day.available_count }} available</div>
                {% if day.min_price %}
                <div class="availability-count">from ${{ "%.0f"|format(day.min_price) }}</div>
                {% endif %}
                {% endif %}
                {% if day.weekend %}
                <div class="weekend-indicator">Weekend</div>
                {% endif %}
            </div>
            {% endfor %}
        </div>
        
        <div class="legend">
            <div class="legend-item">
                <div class="legend-color" style="background: white;"></div>
                <span>No availability</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: #d4edda;"></div>
                <span>Weekday availability</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: #d1ecf1;"></div>
                <span>Weekend availability</span>
            </div>
        </div>
    </div>
    
    <script>
        function updateCalendar() {
            const park = document.getElementById('parkSelect').value;
            const month = document.getElementById('monthSelect').value;
            const year = document.getElementById('yearSelect').value;
            
            window.location.href = `/calendar?year=${year}&month=${month}&park=${park}`;
        }
    </script>
</body>
</html>
"""


async def create_templates_directory():
    """Create templates directory and files if they don't exist."""
    import os
    
    templates_dir = "src/dashboard/templates"
    os.makedirs(templates_dir, exist_ok=True)
    
    # Write calendar template
    with open(f"{templates_dir}/calendar.html", "w") as f:
        f.write(CALENDAR_TEMPLATE)
    
    # Create error template
    error_template = """
<!DOCTYPE html>
<html>
<head>
    <title>Error - Campsite Tracker</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; text-align: center; }
        .error { color: #e74c3c; margin: 20px 0; }
    </style>
</head>
<body>
    <h1>🚨 Error</h1>
    <div class="error">{{ error }}</div>
    <a href="/">Return to Dashboard</a>
</body>
</html>
    """
    
    with open(f"{templates_dir}/error.html", "w") as f:
        f.write(error_template)


# Initialize dashboard
dashboard = DashboardAPI()
app = dashboard.app


async def run_dashboard(host: str = "127.0.0.1", port: int = 8000):
    """Run the dashboard server."""
    import uvicorn
    
    # Create templates
    await create_templates_directory()
    
    logger.info(f"Starting dashboard server on {host}:{port}")
    
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info"
    )
    
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(run_dashboard())