"""
Southern California parks configuration.

Defines park information, URLs, and metadata for monitoring.
"""

from typing import Dict, List, Optional
from enum import Enum
from pydantic import BaseModel


class ParkEnum(str, Enum):
    """Supported Southern California parks."""
    JOSHUA_TREE = "joshua_tree"
    CARLSBAD = "carlsbad"
    OCEANSIDE = "oceanside"


class ParkInfo(BaseModel):
    """Information about a specific park."""
    
    name: str
    display_name: str
    base_url: str
    search_url: str
    park_id: Optional[str] = None
    region: str = "Southern California"
    popular_sites: List[str] = []
    peak_season_months: List[int] = []
    advance_booking_days: int = 180
    notes: Optional[str] = None


# Park configurations for Southern California
PARK_CONFIGS: Dict[ParkEnum, ParkInfo] = {
    ParkEnum.JOSHUA_TREE: ParkInfo(
        name="joshua_tree",
        display_name="Joshua Tree National Park Area",
        base_url="https://www.reservecalifornia.com",
        search_url="https://www.reservecalifornia.com/Web/Search/Joshua+Tree",
        park_id="JOSH",
        popular_sites=[
            "Jumbo Rocks Campground",
            "Belle Campground", 
            "Hidden Valley Campground",
            "Ryan Campground"
        ],
        peak_season_months=[10, 11, 12, 1, 2, 3, 4],  # Oct-Apr
        advance_booking_days=180,
        notes="Desert camping, very popular in cooler months. Sites book quickly."
    ),
    
    ParkEnum.CARLSBAD: ParkInfo(
        name="carlsbad",
        display_name="Carlsbad State Beach",
        base_url="https://www.reservecalifornia.com",
        search_url="https://www.reservecalifornia.com/Web/Search/Carlsbad",
        park_id="CARS",
        popular_sites=[
            "Carlsbad State Beach Campground",
            "South Carlsbad State Beach"
        ],
        peak_season_months=[6, 7, 8, 9],  # Summer months
        advance_booking_days=180,
        notes="Coastal camping with ocean views. Extremely popular in summer."
    ),
    
    ParkEnum.OCEANSIDE: ParkInfo(
        name="oceanside",
        display_name="Oceanside Area State Parks",
        base_url="https://www.reservecalifornia.com",
        search_url="https://www.reservecalifornia.com/Web/Search/Oceanside",
        park_id="OCEAN",
        popular_sites=[
            "San Elijo State Beach",
            "Cardiff State Beach",
            "Leucadia State Beach"
        ],
        peak_season_months=[5, 6, 7, 8, 9, 10],  # Late spring through fall
        advance_booking_days=180,
        notes="Multiple beach camping options. Very competitive reservations."
    )
}


def get_park_info(park: ParkEnum) -> ParkInfo:
    """
    Get park information for a specific park.
    
    Args:
        park: The park enum value
        
    Returns:
        ParkInfo: Park configuration and metadata
        
    Raises:
        KeyError: If park is not configured
    """
    if park not in PARK_CONFIGS:
        raise KeyError(f"Park {park} not found in configuration")
    
    return PARK_CONFIGS[park]


def get_all_parks() -> List[ParkEnum]:
    """
    Get list of all configured parks.
    
    Returns:
        List[ParkEnum]: All available parks
    """
    return list(PARK_CONFIGS.keys())


def get_peak_season_parks(month: int) -> List[ParkEnum]:
    """
    Get parks that are in peak season for the given month.
    
    Args:
        month: Month number (1-12)
        
    Returns:
        List[ParkEnum]: Parks in peak season
    """
    if not 1 <= month <= 12:
        raise ValueError("Month must be between 1 and 12")
    
    peak_parks = []
    for park, info in PARK_CONFIGS.items():
        if month in info.peak_season_months:
            peak_parks.append(park)
    
    return peak_parks


def get_search_url(park: ParkEnum, check_in_date: str = "", nights: int = 1) -> str:
    """
    Get the search URL for a specific park with optional parameters.
    
    Args:
        park: The park to search
        check_in_date: Check-in date in YYYY-MM-DD format
        nights: Number of nights
        
    Returns:
        str: Complete search URL
    """
    park_info = get_park_info(park)
    url = park_info.search_url
    
    if check_in_date:
        url += f"?checkin={check_in_date}&nights={nights}"
    
    return url