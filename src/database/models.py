"""
Pydantic models for campsite availability tracking.

Data models for validation, serialization, and database operations.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, date
from enum import Enum
from pydantic import BaseModel, Field, validator
from ..config.parks import ParkEnum


class SiteTypeEnum(str, Enum):
    """Types of camping sites available."""
    TENT = "tent"
    RV = "rv"
    CABIN = "cabin"
    GROUP = "group"
    DAY_USE = "day_use"


class AvailabilityStatus(str, Enum):
    """Availability status for campsites."""
    AVAILABLE = "available"
    BOOKED = "booked"
    CLOSED = "closed"
    MAINTENANCE = "maintenance"
    UNKNOWN = "unknown"


class NotificationStatus(str, Enum):
    """Status of notification delivery."""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class CampsiteAvailability(BaseModel):
    """
    Model for campsite availability data.
    
    Represents availability information for a specific campsite on a specific date.
    """
    
    park: ParkEnum = Field(..., description="Park identifier")
    site_id: str = Field(..., description="Unique site identifier from reservation system")
    site_name: str = Field(..., description="Human-readable site name")
    site_type: SiteTypeEnum = Field(..., description="Type of campsite")
    check_in_date: date = Field(..., description="Check-in date for availability")
    status: AvailabilityStatus = Field(..., description="Availability status")
    price: Optional[float] = Field(None, ge=0, description="Nightly rate if available")
    max_occupancy: Optional[int] = Field(None, ge=1, le=50, description="Maximum occupancy")
    amenities: List[str] = Field(default_factory=list, description="Site amenities")
    scraped_at: datetime = Field(default_factory=datetime.utcnow, description="When data was collected")
    url: Optional[str] = Field(None, description="Direct booking URL if available")
    
    @validator('check_in_date')
    def validate_future_date(cls, v: date) -> date:
        """Validate that check-in date is not in the past."""
        if v < date.today():
            raise ValueError('Check-in date must be today or in the future')
        return v
    
    @validator('site_id', 'site_name')
    def validate_not_empty(cls, v: str) -> str:
        """Validate that string fields are not empty."""
        if not v or not v.strip():
            raise ValueError('Field cannot be empty')
        return v.strip()
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            date: lambda v: v.isoformat()
        }


class AlertRule(BaseModel):
    """
    Model for user alert rules.
    
    Defines criteria for when to send availability notifications.
    """
    
    id: Optional[str] = Field(None, description="Unique alert rule ID")
    user_email: str = Field(..., description="Email address for notifications")
    parks: List[ParkEnum] = Field(..., min_items=1, description="Parks to monitor")
    site_types: List[SiteTypeEnum] = Field(..., min_items=1, description="Site types of interest")
    weekend_only: bool = Field(True, description="Only alert for weekend availability")
    min_nights: int = Field(1, ge=1, le=14, description="Minimum consecutive nights")
    max_price: Optional[float] = Field(None, ge=0, description="Maximum nightly rate")
    advance_notice_days: int = Field(7, ge=1, le=180, description="Minimum days in advance")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="When rule was created")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="When rule was last updated")
    is_active: bool = Field(True, description="Whether rule is active")
    
    @validator('user_email')
    def validate_email(cls, v: str) -> str:
        """Validate email format."""
        if '@' not in v or '.' not in v.split('@')[1]:
            raise ValueError('Invalid email format')
        return v.lower().strip()
    
    @validator('parks')
    def validate_parks_not_empty(cls, v: List[ParkEnum]) -> List[ParkEnum]:
        """Validate that parks list is not empty."""
        if not v:
            raise ValueError('At least one park must be specified')
        return v
    
    @validator('site_types')
    def validate_site_types_not_empty(cls, v: List[SiteTypeEnum]) -> List[SiteTypeEnum]:
        """Validate that site types list is not empty."""
        if not v:
            raise ValueError('At least one site type must be specified')
        return v
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True


class ScrapeResult(BaseModel):
    """
    Model for scraping operation results.
    
    Tracks the outcome and metrics of scraping operations.
    """
    
    id: Optional[str] = Field(None, description="Unique scrape result ID")
    park: ParkEnum = Field(..., description="Park that was scraped")
    scrape_timestamp: datetime = Field(default_factory=datetime.utcnow, description="When scraping started")
    completed_at: Optional[datetime] = Field(None, description="When scraping completed")
    sites_found: int = Field(0, ge=0, description="Total sites found")
    available_sites: int = Field(0, ge=0, description="Sites available for booking")
    errors: List[str] = Field(default_factory=list, description="Errors encountered during scraping")
    warnings: List[str] = Field(default_factory=list, description="Warnings from scraping")
    processing_time_seconds: Optional[float] = Field(None, ge=0, description="Time taken to complete scraping")
    success: bool = Field(False, description="Whether scraping was successful")
    raw_data: Optional[Dict[str, Any]] = Field(None, description="Raw scraped data for debugging")
    
    @validator('available_sites')
    def validate_available_sites(cls, v: int, values: Dict[str, Any]) -> int:
        """Validate that available sites doesn't exceed total sites found."""
        if 'sites_found' in values and v > values['sites_found']:
            raise ValueError('Available sites cannot exceed total sites found')
        return v
    
    def add_error(self, error: str) -> None:
        """Add an error message to the result."""
        self.errors.append(error)
        self.success = False
    
    def add_warning(self, warning: str) -> None:
        """Add a warning message to the result."""
        self.warnings.append(warning)
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True


class NotificationRecord(BaseModel):
    """
    Model for tracking sent notifications.
    
    Prevents duplicate notifications and tracks delivery status.
    """
    
    id: Optional[str] = Field(None, description="Unique notification ID")
    alert_rule_id: str = Field(..., description="Alert rule that triggered this notification")
    campsite_availability_key: str = Field(..., description="Unique key for campsite availability")
    recipient_email: str = Field(..., description="Email address notification was sent to")
    park: ParkEnum = Field(..., description="Park for the availability")
    site_id: str = Field(..., description="Site ID for the availability")
    check_in_date: date = Field(..., description="Check-in date for the availability")
    status: NotificationStatus = Field(..., description="Notification delivery status")
    sent_at: Optional[datetime] = Field(None, description="When notification was sent")
    error_message: Optional[str] = Field(None, description="Error message if delivery failed")
    retry_count: int = Field(0, ge=0, description="Number of retry attempts")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="When record was created")
    
    @property
    def notification_key(self) -> str:
        """Generate unique key for preventing duplicate notifications."""
        return f"{self.park}_{self.site_id}_{self.check_in_date.isoformat()}"
    
    @validator('recipient_email')
    def validate_email(cls, v: str) -> str:
        """Validate email format."""
        if '@' not in v or '.' not in v.split('@')[1]:
            raise ValueError('Invalid email format')
        return v.lower().strip()
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True


class CampsiteSearchQuery(BaseModel):
    """
    Model for campsite search parameters.
    
    Used to parameterize scraping operations.
    """
    
    parks: List[ParkEnum] = Field(..., min_items=1, description="Parks to search")
    start_date: date = Field(..., description="Start date for availability search")
    end_date: date = Field(..., description="End date for availability search")
    site_types: Optional[List[SiteTypeEnum]] = Field(None, description="Filter by site types")
    max_price: Optional[float] = Field(None, ge=0, description="Maximum price filter")
    min_occupancy: Optional[int] = Field(None, ge=1, description="Minimum occupancy requirement")
    weekend_only: bool = Field(False, description="Only search weekend dates")
    
    @validator('end_date')
    def validate_date_range(cls, v: date, values: Dict[str, Any]) -> date:
        """Validate that end date is after start date."""
        if 'start_date' in values and v <= values['start_date']:
            raise ValueError('End date must be after start date')
        return v
    
    @validator('start_date')
    def validate_start_date(cls, v: date) -> date:
        """Validate that start date is not in the past."""
        if v < date.today():
            raise ValueError('Start date cannot be in the past')
        return v
    
    def get_date_range(self) -> List[date]:
        """Get list of dates in the search range."""
        dates = []
        current = self.start_date
        while current <= self.end_date:
            if not self.weekend_only or current.weekday() >= 5:  # 5=Saturday, 6=Sunday
                dates.append(current)
            current = date.fromordinal(current.toordinal() + 1)
        return dates
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True