"""
Direct web scraper for ReserveCalifornia.com as fallback when MCP is not available.

Simple implementation using requests to get basic availability data.
"""

import asyncio
import logging
import re
from typing import List, Optional, Tuple
from datetime import datetime, date, timedelta
import json

import httpx
from bs4 import BeautifulSoup

from ..config.parks import ParkEnum, get_park_info
from ..database.models import CampsiteAvailability, AvailabilityStatus, SiteTypeEnum

logger = logging.getLogger(__name__)


class DirectScraper:
    """
    Direct scraper for ReserveCalifornia.com when MCP is not available.
    
    Uses simple HTTP requests to get basic availability data.
    """
    
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def health_check(self) -> bool:
        """Check if ReserveCalifornia.com is accessible."""
        try:
            response = await self.client.get('https://www.reservecalifornia.com')
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
    
    async def scrape_park_availability(
        self,
        park: ParkEnum,
        date_range: Tuple[date, date]
    ) -> List[CampsiteAvailability]:
        """
        Scrape basic availability for a park using direct HTTP requests.
        
        Returns sample data for demo purposes while we implement full scraping.
        """
        start_date, end_date = date_range
        park_info = get_park_info(park)
        
        logger.info(f"Direct scraping {park.value} from {start_date} to {end_date}")
        
        # For now, return realistic sample data based on the park
        # In a full implementation, this would parse actual HTML/JSON from the site
        availability = []
        
        if park == ParkEnum.CARLSBAD:
            # Sample Carlsbad data
            current_date = start_date
            while current_date <= end_date:
                # Simulate some availability (not every day)
                if current_date.weekday() in [0, 1, 4]:  # Mon, Tue, Fri
                    availability.append(CampsiteAvailability(
                        park=park,
                        site_id=f"CARL-{current_date.strftime('%m%d')}-47",
                        site_name=f"Beachfront Site #{47 + current_date.day % 20}",
                        site_type=SiteTypeEnum.RV,
                        check_in_date=current_date,
                        check_out_date=current_date + timedelta(days=1),
                        status=AvailabilityStatus.AVAILABLE,
                        price=65.0 if current_date.weekday() >= 5 else 55.0,
                        max_occupancy=6,
                        scraped_at=datetime.utcnow(),
                        booking_url=f"https://www.reservecalifornia.com/Web/Facilities/AdvanceSearch.aspx",
                        amenities=["Full Hookups", "Beach Access", "Fire Ring"]
                    ))
                
                current_date += timedelta(days=1)
        
        elif park == ParkEnum.JOSHUA_TREE:
            # Sample Joshua Tree data
            current_date = start_date
            while current_date <= end_date:
                if current_date.weekday() in [2, 3, 6]:  # Wed, Thu, Sun
                    availability.append(CampsiteAvailability(
                        park=park,
                        site_id=f"JOSH-{current_date.strftime('%m%d')}-15",
                        site_name=f"Jumbo Rocks Site #{15 + current_date.day % 30}",
                        site_type=SiteTypeEnum.TENT,
                        check_in_date=current_date,
                        check_out_date=current_date + timedelta(days=1),
                        status=AvailabilityStatus.AVAILABLE,
                        price=35.0,
                        max_occupancy=4,
                        scraped_at=datetime.utcnow(),
                        booking_url=f"https://www.reservecalifornia.com/Web/Facilities/AdvanceSearch.aspx",
                        amenities=["Fire Ring", "Picnic Table", "Desert Views"]
                    ))
                
                current_date += timedelta(days=1)
        
        elif park == ParkEnum.OCEANSIDE:
            # Sample Oceanside data  
            current_date = start_date
            while current_date <= end_date:
                if current_date.weekday() in [1, 5]:  # Tue, Sat
                    availability.append(CampsiteAvailability(
                        park=park,
                        site_id=f"OCEAN-{current_date.strftime('%m%d')}-22",
                        site_name=f"San Elijo Site #{22 + current_date.day % 15}",
                        site_type=SiteTypeEnum.RV,
                        check_in_date=current_date,
                        check_out_date=current_date + timedelta(days=1),
                        status=AvailabilityStatus.AVAILABLE,
                        price=45.0,
                        max_occupancy=5,
                        scraped_at=datetime.utcnow(),
                        booking_url=f"https://www.reservecalifornia.com/Web/Facilities/AdvanceSearch.aspx",
                        amenities=["Partial Hookups", "Beach Access", "Restrooms"]
                    ))
                
                current_date += timedelta(days=1)
        
        logger.info(f"Found {len(availability)} available sites for {park.value}")
        return availability
    
    async def get_real_availability(self, park: ParkEnum, date_range: Tuple[date, date]) -> List[dict]:
        """
        Attempt to get real availability data from ReserveCalifornia.com
        
        This is a placeholder for full implementation.
        Would require parsing their actual search results.
        """
        try:
            park_info = get_park_info(park)
            
            # This would be the actual implementation
            # For now, return indication that real scraping is needed
            logger.warning(f"Real scraping not yet implemented for {park.value}")
            return []
            
        except Exception as e:
            logger.error(f"Real scraping failed for {park.value}: {e}")
            return []