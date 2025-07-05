"""
Reservation data parser for ReserveCalifornia.com.

Handles parsing of HTML content and JSON responses from the California
state park reservation system to extract campsite availability data.
"""

import re
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date
from urllib.parse import urljoin, parse_qs, urlparse

from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from ..config.parks import ParkEnum, get_park_info
from ..database.models import CampsiteAvailability, SiteTypeEnum, AvailabilityStatus

logger = logging.getLogger(__name__)


class ReservationParser:
    """
    Parser for ReserveCalifornia.com content.
    
    Handles the specific HTML structure and JavaScript data formats
    used by the California state park reservation system.
    """
    
    def __init__(self):
        """Initialize the parser."""
        self.site_type_mapping = {
            "tent": SiteTypeEnum.TENT,
            "rv": SiteTypeEnum.RV,
            "cabin": SiteTypeEnum.CABIN,
            "group": SiteTypeEnum.GROUP,
            "day use": SiteTypeEnum.DAY_USE,
            "standard": SiteTypeEnum.TENT,  # Default mapping
            "electric": SiteTypeEnum.RV,
            "primitive": SiteTypeEnum.TENT,
            "hookup": SiteTypeEnum.RV,
            "full hookup": SiteTypeEnum.RV,
            "partial hookup": SiteTypeEnum.RV
        }
        
        self.status_mapping = {
            "available": AvailabilityStatus.AVAILABLE,
            "open": AvailabilityStatus.AVAILABLE,
            "a": AvailabilityStatus.AVAILABLE,
            "booked": AvailabilityStatus.BOOKED,
            "reserved": AvailabilityStatus.BOOKED,
            "r": AvailabilityStatus.BOOKED,
            "closed": AvailabilityStatus.CLOSED,
            "c": AvailabilityStatus.CLOSED,
            "maintenance": AvailabilityStatus.MAINTENANCE,
            "m": AvailabilityStatus.MAINTENANCE,
            "unavailable": AvailabilityStatus.BOOKED,
            "na": AvailabilityStatus.BOOKED
        }
    
    def parse_html_content(
        self,
        html_content: str,
        park: ParkEnum,
        base_url: str = "https://www.reservecalifornia.com"
    ) -> List[CampsiteAvailability]:
        """
        Parse HTML content to extract campsite availability.
        
        Args:
            html_content: Raw HTML content from the page
            park: Park being parsed
            base_url: Base URL for resolving relative links
            
        Returns:
            List of CampsiteAvailability objects
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        availability_list = []
        
        try:
            # Try multiple parsing strategies for different page layouts
            
            # Strategy 1: Parse calendar grid view
            calendar_data = self._parse_calendar_view(soup, park, base_url)
            availability_list.extend(calendar_data)
            
            # Strategy 2: Parse search results list
            search_results = self._parse_search_results(soup, park, base_url)
            availability_list.extend(search_results)
            
            # Strategy 3: Parse JavaScript data objects
            js_data = self._parse_javascript_data(soup, park, base_url)
            availability_list.extend(js_data)
            
            # Strategy 4: Parse AJAX response data (if present)
            ajax_data = self._parse_ajax_data(html_content, park, base_url)
            availability_list.extend(ajax_data)
            
        except Exception as e:
            logger.error(f"Error parsing HTML content for {park}: {e}")
        
        # Remove duplicates based on unique key
        unique_availability = {}
        for avail in availability_list:
            key = f"{avail.park}_{avail.site_id}_{avail.check_in_date}"
            if key not in unique_availability:
                unique_availability[key] = avail
        
        logger.info(f"Parsed {len(unique_availability)} unique availability records for {park}")
        return list(unique_availability.values())
    
    def _parse_calendar_view(
        self,
        soup: BeautifulSoup,
        park: ParkEnum,
        base_url: str
    ) -> List[CampsiteAvailability]:
        """Parse calendar grid view of availability."""
        availability_list = []
        
        # Look for calendar tables or grids
        calendar_containers = soup.find_all(['table', 'div'], class_=re.compile(r'calendar|availability|grid', re.I))
        
        for container in calendar_containers:
            # Find date headers
            date_headers = container.find_all(['th', 'div'], string=re.compile(r'\d{1,2}/\d{1,2}|\d{4}-\d{2}-\d{2}'))
            
            # Find site rows
            site_rows = container.find_all(['tr', 'div'], class_=re.compile(r'site|campsite|row', re.I))
            
            for row in site_rows:
                site_info = self._extract_site_info_from_row(row, park)
                if not site_info:
                    continue
                
                # Find availability cells in this row
                availability_cells = row.find_all(['td', 'div'], class_=re.compile(r'avail|status|day', re.I))
                
                for i, cell in enumerate(availability_cells):
                    if i < len(date_headers):
                        date_str = date_headers[i].get_text(strip=True)
                        check_in_date = self._parse_date(date_str)
                        
                        if check_in_date:
                            status = self._extract_status_from_cell(cell)
                            price = self._extract_price_from_cell(cell)
                            
                            availability = CampsiteAvailability(
                                park=park,
                                site_id=site_info['site_id'],
                                site_name=site_info['site_name'],
                                site_type=site_info['site_type'],
                                check_in_date=check_in_date,
                                status=status,
                                price=price,
                                max_occupancy=site_info.get('max_occupancy'),
                                amenities=site_info.get('amenities', []),
                                scraped_at=datetime.utcnow(),
                                url=self._extract_booking_url(cell, base_url)
                            )
                            
                            availability_list.append(availability)
        
        return availability_list
    
    def _parse_search_results(
        self,
        soup: BeautifulSoup,
        park: ParkEnum,
        base_url: str
    ) -> List[CampsiteAvailability]:
        """Parse search results list view."""
        availability_list = []
        
        # Look for search result containers
        result_containers = soup.find_all(['div', 'li'], class_=re.compile(r'result|site|campsite|listing', re.I))
        
        for container in result_containers:
            site_info = self._extract_site_info_from_container(container, park)
            if not site_info:
                continue
            
            # Look for availability information within this container
            avail_info = self._extract_availability_from_container(container)
            
            for avail_data in avail_info:
                try:
                    availability = CampsiteAvailability(
                        park=park,
                        site_id=site_info['site_id'],
                        site_name=site_info['site_name'],
                        site_type=site_info['site_type'],
                        check_in_date=avail_data['check_in_date'],
                        status=avail_data['status'],
                        price=avail_data.get('price'),
                        max_occupancy=site_info.get('max_occupancy'),
                        amenities=site_info.get('amenities', []),
                        scraped_at=datetime.utcnow(),
                        url=avail_data.get('url')
                    )
                    
                    availability_list.append(availability)
                    
                except ValidationError as e:
                    logger.warning(f"Invalid availability data: {e}")
                    continue
        
        return availability_list
    
    def _parse_javascript_data(
        self,
        soup: BeautifulSoup,
        park: ParkEnum,
        base_url: str
    ) -> List[CampsiteAvailability]:
        """Parse JavaScript data objects embedded in the page."""
        availability_list = []
        
        # Look for script tags containing data
        script_tags = soup.find_all('script', string=re.compile(r'availability|campsite|reservation', re.I))
        
        for script in script_tags:
            script_content = script.get_text()
            
            # Try to extract JSON data from various patterns
            json_patterns = [
                r'var\s+availability\s*=\s*(\{.*?\});',
                r'window\.reservationData\s*=\s*(\{.*?\});',
                r'data:\s*(\{.*?\})',
                r'"availability":\s*(\[.*?\])',
                r'"sites":\s*(\[.*?\])'
            ]
            
            for pattern in json_patterns:
                matches = re.findall(pattern, script_content, re.DOTALL)
                
                for match in matches:
                    try:
                        data = json.loads(match)
                        parsed_data = self._parse_json_availability_data(data, park, base_url)
                        availability_list.extend(parsed_data)
                        
                    except json.JSONDecodeError:
                        continue
        
        return availability_list
    
    def _parse_ajax_data(
        self,
        content: str,
        park: ParkEnum,
        base_url: str
    ) -> List[CampsiteAvailability]:
        """Parse AJAX response data if content appears to be JSON."""
        availability_list = []
        
        # Check if content looks like JSON
        content = content.strip()
        if content.startswith('{') or content.startswith('['):
            try:
                data = json.loads(content)
                availability_list = self._parse_json_availability_data(data, park, base_url)
                
            except json.JSONDecodeError:
                logger.debug("Content is not valid JSON")
        
        return availability_list
    
    def _parse_json_availability_data(
        self,
        data: Dict[str, Any],
        park: ParkEnum,
        base_url: str
    ) -> List[CampsiteAvailability]:
        """Parse JSON data structure for availability information."""
        availability_list = []
        
        # Handle different JSON structures
        if isinstance(data, list):
            items = data
        elif 'sites' in data:
            items = data['sites']
        elif 'availability' in data:
            items = data['availability']
        elif 'results' in data:
            items = data['results']
        else:
            items = [data]
        
        for item in items:
            if not isinstance(item, dict):
                continue
            
            # Extract site information
            site_id = str(item.get('siteId', item.get('id', item.get('site_id', 'unknown'))))
            site_name = item.get('siteName', item.get('name', item.get('site_name', f'Site {site_id}'))
            
            # Extract site type
            site_type_raw = item.get('siteType', item.get('type', item.get('site_type', 'tent'))
            site_type = self._normalize_site_type(site_type_raw)
            
            # Extract availability dates
            availability_dates = item.get('dates', item.get('availability', item.get('calendar', [])))
            
            if not availability_dates and 'date' in item:
                # Single date format
                availability_dates = [item]
            
            for date_info in availability_dates:
                if not isinstance(date_info, dict):
                    continue
                
                check_in_date = self._parse_date(
                    date_info.get('date', date_info.get('checkIn', date_info.get('check_in_date')))
                )
                
                if not check_in_date:
                    continue
                
                status_raw = date_info.get('status', date_info.get('available', date_info.get('availability')))
                status = self._normalize_status(status_raw)
                
                price = self._extract_price_value(date_info.get('price', date_info.get('rate', date_info.get('cost'))))
                
                try:
                    availability = CampsiteAvailability(
                        park=park,
                        site_id=site_id,
                        site_name=site_name,
                        site_type=site_type,
                        check_in_date=check_in_date,
                        status=status,
                        price=price,
                        max_occupancy=item.get('maxOccupancy', item.get('capacity')),
                        amenities=item.get('amenities', []),
                        scraped_at=datetime.utcnow(),
                        url=item.get('bookingUrl', item.get('url'))
                    )
                    
                    availability_list.append(availability)
                    
                except ValidationError as e:
                    logger.warning(f"Invalid JSON availability data: {e}")
                    continue
        
        return availability_list
    
    def _extract_site_info_from_row(self, row: Tag, park: ParkEnum) -> Optional[Dict[str, Any]]:
        """Extract site information from a table row."""
        # Look for site ID and name
        site_cells = row.find_all(['td', 'th', 'div'], string=re.compile(r'site\s*\d+|#\d+|\d{3,}', re.I))
        
        if not site_cells:
            return None
        
        site_text = site_cells[0].get_text(strip=True)
        site_id_match = re.search(r'(\d+)', site_text)
        
        if not site_id_match:
            return None
        
        site_id = site_id_match.group(1)
        site_name = site_text
        
        # Extract site type
        type_text = row.get_text().lower()
        site_type = self._infer_site_type(type_text)
        
        return {
            'site_id': site_id,
            'site_name': site_name,
            'site_type': site_type
        }
    
    def _extract_site_info_from_container(self, container: Tag, park: ParkEnum) -> Optional[Dict[str, Any]]:
        """Extract site information from a search result container."""
        # Look for site identification
        site_id_elem = container.find(['span', 'div', 'h3'], class_=re.compile(r'site|id', re.I))
        
        if site_id_elem:
            site_text = site_id_elem.get_text(strip=True)
            site_id_match = re.search(r'(\d+)', site_text)
            
            if site_id_match:
                site_id = site_id_match.group(1)
                site_name = site_text
                
                # Extract site type
                type_text = container.get_text().lower()
                site_type = self._infer_site_type(type_text)
                
                return {
                    'site_id': site_id,
                    'site_name': site_name,
                    'site_type': site_type
                }
        
        return None
    
    def _extract_availability_from_container(self, container: Tag) -> List[Dict[str, Any]]:
        """Extract availability information from a container."""
        availability_info = []
        
        # Look for date and status information
        date_elements = container.find_all(string=re.compile(r'\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2}'))
        
        for date_elem in date_elements:
            check_in_date = self._parse_date(date_elem)
            
            if check_in_date:
                # Find associated status and price
                parent = date_elem.parent if hasattr(date_elem, 'parent') else container
                status = self._extract_status_from_element(parent)
                price = self._extract_price_from_element(parent)
                
                availability_info.append({
                    'check_in_date': check_in_date,
                    'status': status,
                    'price': price
                })
        
        return availability_info
    
    def _normalize_site_type(self, site_type_raw: Any) -> SiteTypeEnum:
        """Normalize site type to enum value."""
        if not site_type_raw:
            return SiteTypeEnum.TENT
        
        site_type_str = str(site_type_raw).lower().strip()
        
        for key, enum_value in self.site_type_mapping.items():
            if key in site_type_str:
                return enum_value
        
        return SiteTypeEnum.TENT  # Default
    
    def _normalize_status(self, status_raw: Any) -> AvailabilityStatus:
        """Normalize availability status to enum value."""
        if not status_raw:
            return AvailabilityStatus.UNKNOWN
        
        status_str = str(status_raw).lower().strip()
        
        for key, enum_value in self.status_mapping.items():
            if key == status_str or key in status_str:
                return enum_value
        
        return AvailabilityStatus.UNKNOWN
    
    def _parse_date(self, date_str: str) -> Optional[date]:
        """Parse date string into date object."""
        if not date_str:
            return None
        
        # Common date formats
        date_patterns = [
            r'(\d{4})-(\d{2})-(\d{2})',  # YYYY-MM-DD
            r'(\d{1,2})/(\d{1,2})/(\d{4})',  # M/D/YYYY or MM/DD/YYYY
            r'(\d{1,2})-(\d{1,2})-(\d{4})',  # M-D-YYYY
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, str(date_str))
            if match:
                try:
                    if len(match.group(1)) == 4:  # Year first
                        year, month, day = match.groups()
                    else:  # Month/day first
                        month, day, year = match.groups()
                    
                    return date(int(year), int(month), int(day))
                    
                except ValueError:
                    continue
        
        return None
    
    def _extract_price_value(self, price_raw: Any) -> Optional[float]:
        """Extract numeric price value."""
        if not price_raw:
            return None
        
        price_str = str(price_raw)
        price_match = re.search(r'(\d+\.?\d*)', price_str)
        
        if price_match:
            try:
                return float(price_match.group(1))
            except ValueError:
                pass
        
        return None
    
    def _infer_site_type(self, text: str) -> SiteTypeEnum:
        """Infer site type from text content."""
        text = text.lower()
        
        if any(keyword in text for keyword in ['rv', 'hookup', 'electric', 'sewer']):
            return SiteTypeEnum.RV
        elif any(keyword in text for keyword in ['cabin', 'lodge', 'yurt']):
            return SiteTypeEnum.CABIN
        elif any(keyword in text for keyword in ['group', 'large']):
            return SiteTypeEnum.GROUP
        else:
            return SiteTypeEnum.TENT
    
    def _extract_status_from_cell(self, cell: Tag) -> AvailabilityStatus:
        """Extract availability status from table cell."""
        # Check CSS classes first
        css_classes = cell.get('class', [])
        class_text = ' '.join(css_classes).lower()
        
        if any(keyword in class_text for keyword in ['available', 'open', 'free']):
            return AvailabilityStatus.AVAILABLE
        elif any(keyword in class_text for keyword in ['booked', 'reserved', 'taken']):
            return AvailabilityStatus.BOOKED
        elif any(keyword in class_text for keyword in ['closed', 'unavailable']):
            return AvailabilityStatus.CLOSED
        
        # Check text content
        cell_text = cell.get_text(strip=True).lower()
        return self._normalize_status(cell_text)
    
    def _extract_price_from_cell(self, cell: Tag) -> Optional[float]:
        """Extract price from table cell."""
        cell_text = cell.get_text()
        return self._extract_price_value(cell_text)
    
    def _extract_status_from_element(self, element: Tag) -> AvailabilityStatus:
        """Extract status from any element."""
        element_text = element.get_text().lower()
        return self._normalize_status(element_text)
    
    def _extract_price_from_element(self, element: Tag) -> Optional[float]:
        """Extract price from any element."""
        element_text = element.get_text()
        return self._extract_price_value(element_text)
    
    def _extract_booking_url(self, element: Tag, base_url: str) -> Optional[str]:
        """Extract booking URL from element."""
        # Look for links
        link = element.find('a', href=True)
        if link:
            href = link['href']
            if href.startswith('http'):
                return href
            else:
                return urljoin(base_url, href)
        
        return None