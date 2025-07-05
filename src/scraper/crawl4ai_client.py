"""
Crawl4AI RAG MCP client for JavaScript-aware web scraping.

Provides interface to Crawl4AI RAG MCP server for scraping reservecalifornia.com
with JavaScript support and content extraction capabilities.
"""

import asyncio
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date, timedelta
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import ValidationError

from ..config.settings import settings
from ..config.parks import ParkEnum, get_park_info, get_search_url
from ..database.models import CampsiteAvailability, ScrapeResult, CampsiteSearchQuery
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class MCPError(Exception):
    """Exception raised for MCP communication errors."""
    pass


class Crawl4AIClient:
    """
    Client for Crawl4AI RAG MCP server.
    
    Handles JavaScript-aware scraping of reservecalifornia.com and content extraction
    using the Crawl4AI RAG MCP server capabilities.
    """
    
    def __init__(self, mcp_server_url: Optional[str] = None):
        """
        Initialize Crawl4AI client.
        
        Args:
            mcp_server_url: URL of the Crawl4AI RAG MCP server
        """
        self.mcp_server_url = mcp_server_url or settings.crawl4ai_mcp_url
        self.rate_limiter = RateLimiter(
            requests_per_minute=settings.max_requests_per_minute,
            backoff_multiplier=settings.backoff_multiplier
        )
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),  # 60 second timeout for JavaScript-heavy pages
            limits=httpx.Limits(max_connections=5)
        )
        self.session_id: Optional[str] = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def close(self):
        """Close the HTTP client."""
        if self.client:
            await self.client.aclose()
    
    async def health_check(self) -> bool:
        """
        Check if the MCP server is available and responding.
        
        Returns:
            bool: True if server is healthy
        """
        try:
            response = await self.client.get(
                f"{self.mcp_server_url}/health",
                timeout=5.0
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
    
    async def scrape_park_availability(
        self,
        park: ParkEnum,
        date_range: Tuple[date, date],
        site_types: Optional[List[str]] = None
    ) -> List[CampsiteAvailability]:
        """
        Scrape campsite availability for a specific park and date range.
        
        Args:
            park: Park to scrape
            date_range: Tuple of (start_date, end_date)
            site_types: Optional filter for specific site types
            
        Returns:
            List of CampsiteAvailability objects
            
        Raises:
            MCPError: If scraping fails
        """
        start_date, end_date = date_range
        park_info = get_park_info(park)
        
        logger.info(f"Scraping {park_info.display_name} from {start_date} to {end_date}")
        
        # Apply rate limiting
        await self.rate_limiter.acquire()
        
        try:
            # Get search URL for the park
            search_url = get_search_url(park, start_date.isoformat(), (end_date - start_date).days + 1)
            
            # Prepare scraping request
            scrape_request = {
                "url": search_url,
                "javascript": True,
                "wait_time": 8,  # Wait for dynamic content to load
                "screenshot": False,  # Don't need screenshots for data extraction
                "extract_patterns": [
                    "campsite",
                    "availability",
                    "pricing",
                    "site_details",
                    "booking_info"
                ],
                "custom_css_selector": [
                    ".campsite-item",
                    ".availability-calendar",
                    ".site-info",
                    ".price-info"
                ],
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            # Make request to Crawl4AI RAG MCP server
            scraped_content = await self._call_mcp_tool("crawl_website", scrape_request)
            
            # Extract structured data using RAG capabilities
            availability_data = await self._extract_availability_data(
                scraped_content,
                park,
                start_date,
                end_date,
                site_types
            )
            
            self.rate_limiter.handle_success()
            logger.info(f"Successfully scraped {len(availability_data)} availability records for {park_info.display_name}")
            
            return availability_data
            
        except Exception as e:
            await self.rate_limiter.handle_error(e)
            logger.error(f"Failed to scrape {park_info.display_name}: {e}")
            raise MCPError(f"Scraping failed for {park}: {e}")
    
    async def _call_mcp_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call a tool on the Crawl4AI RAG MCP server.
        
        Args:
            tool_name: Name of the tool to call
            parameters: Parameters for the tool
            
        Returns:
            Tool response data
            
        Raises:
            MCPError: If tool call fails
        """
        payload = {
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": parameters
            }
        }
        
        try:
            response = await self.client.post(
                f"{self.mcp_server_url}/tools/call",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code != 200:
                raise MCPError(f"MCP tool call failed with status {response.status_code}: {response.text}")
            
            result = response.json()
            
            if "error" in result:
                raise MCPError(f"MCP tool error: {result['error']}")
            
            return result.get("content", {})
            
        except httpx.RequestError as e:
            raise MCPError(f"Network error calling MCP tool: {e}")
        except json.JSONDecodeError as e:
            raise MCPError(f"Invalid JSON response from MCP server: {e}")
    
    async def _extract_availability_data(
        self,
        scraped_content: Dict[str, Any],
        park: ParkEnum,
        start_date: date,
        end_date: date,
        site_types: Optional[List[str]] = None
    ) -> List[CampsiteAvailability]:
        """
        Extract structured availability data from scraped content using RAG.
        
        Args:
            scraped_content: Raw scraped content from Crawl4AI
            park: Park being scraped
            start_date: Start date of search
            end_date: End date of search
            site_types: Optional site type filter
            
        Returns:
            List of structured availability objects
        """
        # Prepare context for RAG extraction
        extraction_context = {
            "park_name": get_park_info(park).display_name,
            "search_date_range": f"{start_date.isoformat()} to {end_date.isoformat()}",
            "target_data": "campsite availability, pricing, and booking information",
            "site_types_filter": site_types or [],
            "expected_fields": [
                "site_id",
                "site_name", 
                "site_type",
                "check_in_date",
                "availability_status",
                "price",
                "max_occupancy",
                "amenities",
                "booking_url"
            ]
        }
        
        # Use RAG to extract structured data
        extraction_request = {
            "content": scraped_content.get("content", ""),
            "html": scraped_content.get("html", ""),
            "schema": {
                "type": "object",
                "properties": {
                    "campsites": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "site_id": {"type": "string"},
                                "site_name": {"type": "string"},
                                "site_type": {"type": "string"},
                                "check_in_date": {"type": "string", "format": "date"},
                                "status": {"type": "string"},
                                "price": {"type": ["number", "null"]},
                                "max_occupancy": {"type": ["integer", "null"]},
                                "amenities": {"type": "array", "items": {"type": "string"}},
                                "url": {"type": ["string", "null"]}
                            }
                        }
                    }
                }
            },
            "context": f"Extract campsite availability data for {extraction_context['park_name']} from {extraction_context['search_date_range']}. Focus on finding site IDs, names, types, availability status, pricing, and booking information.",
            "extraction_mode": "structured"
        }
        
        try:
            extracted_data = await self._call_mcp_tool("extract_structured_data", extraction_request)
            
            # Convert extracted data to CampsiteAvailability objects
            availability_list = []
            campsites_data = extracted_data.get("campsites", [])
            
            for site_data in campsites_data:
                try:
                    # Map status strings to enum values
                    status_mapping = {
                        "available": "available",
                        "open": "available",
                        "booked": "booked",
                        "reserved": "booked",
                        "closed": "closed",
                        "maintenance": "maintenance",
                        "unavailable": "booked"
                    }
                    
                    raw_status = site_data.get("status", "unknown").lower()
                    mapped_status = status_mapping.get(raw_status, "unknown")
                    
                    # Parse check-in date
                    check_in_str = site_data.get("check_in_date")
                    if check_in_str:
                        check_in_date = datetime.fromisoformat(check_in_str).date()
                    else:
                        continue  # Skip entries without dates
                    
                    # Apply site type filter if specified
                    site_type = site_data.get("site_type", "tent").lower()
                    if site_types and site_type not in [st.lower() for st in site_types]:
                        continue
                    
                    availability = CampsiteAvailability(
                        park=park,
                        site_id=site_data.get("site_id", "unknown"),
                        site_name=site_data.get("site_name", "Unknown Site"),
                        site_type=site_type,
                        check_in_date=check_in_date,
                        status=mapped_status,
                        price=site_data.get("price"),
                        max_occupancy=site_data.get("max_occupancy"),
                        amenities=site_data.get("amenities", []),
                        scraped_at=datetime.utcnow(),
                        url=site_data.get("url")
                    )
                    
                    availability_list.append(availability)
                    
                except (ValidationError, ValueError) as e:
                    logger.warning(f"Skipping invalid availability data: {e}")
                    continue
            
            return availability_list
            
        except Exception as e:
            logger.error(f"Failed to extract availability data: {e}")
            return []
    
    async def scrape_multiple_parks(
        self,
        query: CampsiteSearchQuery
    ) -> Dict[ParkEnum, List[CampsiteAvailability]]:
        """
        Scrape multiple parks according to search query.
        
        Args:
            query: Search parameters
            
        Returns:
            Dictionary mapping parks to availability lists
        """
        results = {}
        
        for park in query.parks:
            try:
                availability = await self.scrape_park_availability(
                    park,
                    (query.start_date, query.end_date),
                    [st.value for st in query.site_types] if query.site_types else None
                )
                
                # Apply additional filters
                filtered_availability = []
                for avail in availability:
                    # Price filter
                    if query.max_price and avail.price and avail.price > query.max_price:
                        continue
                    
                    # Weekend filter
                    if query.weekend_only and avail.check_in_date.weekday() < 5:
                        continue
                    
                    # Occupancy filter  
                    if query.min_occupancy and avail.max_occupancy and avail.max_occupancy < query.min_occupancy:
                        continue
                    
                    filtered_availability.append(avail)
                
                results[park] = filtered_availability
                
            except Exception as e:
                logger.error(f"Failed to scrape {park}: {e}")
                results[park] = []
        
        return results
    
    async def get_scrape_result(
        self,
        park: ParkEnum,
        start_time: datetime,
        availability_count: int,
        errors: List[str] = None,
        success: bool = True
    ) -> ScrapeResult:
        """
        Create a ScrapeResult object for tracking scraping operations.
        
        Args:
            park: Park that was scraped
            start_time: When scraping started
            availability_count: Number of availability records found
            errors: List of errors encountered
            success: Whether scraping was successful
            
        Returns:
            ScrapeResult object
        """
        end_time = datetime.utcnow()
        processing_time = (end_time - start_time).total_seconds()
        
        return ScrapeResult(
            park=park,
            scrape_timestamp=start_time,
            completed_at=end_time,
            sites_found=availability_count,
            available_sites=availability_count,  # Will be updated based on status filtering
            errors=errors or [],
            processing_time_seconds=processing_time,
            success=success
        )