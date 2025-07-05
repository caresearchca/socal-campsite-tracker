"""
Alert rule processing and weekend detection logic.

Handles matching campsite availability against user-defined alert rules
and determining when notifications should be sent.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import datetime, date, timedelta
from collections import defaultdict

from ..config.settings import settings
from ..config.parks import ParkEnum, get_park_info
from ..database.models import (
    CampsiteAvailability,
    AlertRule,
    NotificationRecord,
    AvailabilityStatus,
    SiteTypeEnum,
    NotificationStatus
)
from ..database.supabase_client import SupabaseClient
from .email_alerts import EmailNotificationService

logger = logging.getLogger(__name__)


class AlertProcessor:
    """
    Processes alert rules against availability data.
    
    Handles matching logic, duplicate prevention, and notification triggering.
    """
    
    def __init__(
        self,
        db_client: Optional[SupabaseClient] = None,
        email_service: Optional[EmailNotificationService] = None
    ):
        """
        Initialize alert processor.
        
        Args:
            db_client: Database client for queries
            email_service: Email service for notifications
        """
        self.db_client = db_client or SupabaseClient()
        self.email_service = email_service or EmailNotificationService()
        
        # Tracking for batch processing
        self.processed_notifications: Set[str] = set()
        self.notification_batch: List[NotificationRecord] = []
    
    async def process_new_availability(
        self,
        availability: List[CampsiteAvailability]
    ) -> Dict[str, Any]:
        """
        Process new availability data against all active alert rules.
        
        Args:
            availability: List of new availability data
            
        Returns:
            Dict with processing statistics
        """
        if not availability:
            return {'notifications_sent': 0, 'rules_processed': 0, 'errors': []}
        
        logger.info(f"Processing {len(availability)} availability records against alert rules")
        
        stats = {
            'notifications_sent': 0,
            'rules_processed': 0,
            'errors': [],
            'availability_processed': len(availability),
            'weekend_sites_found': 0,
            'rules_matched': 0
        }
        
        try:
            # Get all active alert rules
            alert_rules = await self.db_client.get_active_alert_rules()
            stats['rules_processed'] = len(alert_rules)
            
            if not alert_rules:
                logger.info("No active alert rules found")
                return stats
            
            # Filter for weekend sites if any rules care about weekends
            weekend_availability = [
                site for site in availability
                if self.is_weekend_date(site.check_in_date)
                and site.status == AvailabilityStatus.AVAILABLE
            ]
            stats['weekend_sites_found'] = len(weekend_availability)
            
            # Process each alert rule
            for rule in alert_rules:
                try:
                    matches = await self.find_matching_availability(rule, availability)
                    
                    if matches:
                        stats['rules_matched'] += 1
                        notification_sent = await self.send_alert_notification(rule, matches)
                        
                        if notification_sent:
                            stats['notifications_sent'] += 1
                        
                except Exception as e:
                    error_msg = f"Error processing rule {rule.id}: {e}"
                    logger.error(error_msg)
                    stats['errors'].append(error_msg)
            
            # Batch store notification records
            if self.notification_batch:
                await self._store_notification_batch()
            
            logger.info(f"Alert processing complete: {stats}")
            return stats
            
        except Exception as e:
            error_msg = f"Failed to process availability alerts: {e}"
            logger.error(error_msg)
            stats['errors'].append(error_msg)
            return stats
    
    async def find_matching_availability(
        self,
        alert_rule: AlertRule,
        availability: List[CampsiteAvailability]
    ) -> List[CampsiteAvailability]:
        """
        Find availability that matches an alert rule.
        
        Args:
            alert_rule: Alert rule to match against
            availability: List of availability to check
            
        Returns:
            List of matching availability
        """
        matches = []
        
        for site in availability:
            # Only process available sites
            if site.status != AvailabilityStatus.AVAILABLE:
                continue
            
            # Check if we already sent notification for this site/date
            already_notified = await self.db_client.check_notification_sent(
                site.park,
                site.site_id,
                site.check_in_date,
                settings.alert_cooldown_hours
            )
            
            if already_notified:
                continue
            
            # Check rule criteria
            if await self._matches_alert_rule(alert_rule, site, availability):
                matches.append(site)
        
        return matches
    
    async def _matches_alert_rule(
        self,
        rule: AlertRule,
        site: CampsiteAvailability,
        all_availability: List[CampsiteAvailability]
    ) -> bool:
        """
        Check if a specific site matches an alert rule.
        
        Args:
            rule: Alert rule to check
            site: Campsite availability to check
            all_availability: All availability data for consecutive nights check
            
        Returns:
            bool: True if site matches rule
        """
        # Check park filter
        if site.park not in rule.parks:
            return False
        
        # Check site type filter
        if site.site_type not in [SiteTypeEnum(st) for st in rule.site_types]:
            return False
        
        # Check weekend filter
        if rule.weekend_only and not self.is_weekend_date(site.check_in_date):
            return False
        
        # Check price filter
        if rule.max_price and site.price and site.price > rule.max_price:
            return False
        
        # Check advance notice
        days_ahead = (site.check_in_date - date.today()).days
        if days_ahead < rule.advance_notice_days:
            return False
        
        # Check consecutive nights requirement
        if rule.min_nights > 1:
            consecutive_available = self._check_consecutive_nights(
                site, all_availability, rule.min_nights
            )
            if not consecutive_available:
                return False
        
        return True
    
    def _check_consecutive_nights(
        self,
        site: CampsiteAvailability,
        all_availability: List[CampsiteAvailability],
        min_nights: int
    ) -> bool:
        """
        Check if site has consecutive nights available.
        
        Args:
            site: Starting site availability
            all_availability: All availability data
            min_nights: Minimum consecutive nights required
            
        Returns:
            bool: True if consecutive nights are available
        """
        # Find all availability for this park and site
        site_availability = [
            avail for avail in all_availability
            if (avail.park == site.park and 
                avail.site_id == site.site_id and
                avail.status == AvailabilityStatus.AVAILABLE)
        ]
        
        # Sort by date
        site_availability.sort(key=lambda x: x.check_in_date)
        
        # Find consecutive sequence starting from site.check_in_date
        consecutive_count = 0
        current_date = site.check_in_date
        
        for avail in site_availability:
            if avail.check_in_date == current_date:
                consecutive_count += 1
                current_date += timedelta(days=1)
                
                if consecutive_count >= min_nights:
                    return True
            elif avail.check_in_date > current_date:
                # Gap in availability, reset count
                break
        
        return consecutive_count >= min_nights
    
    def is_weekend_date(self, check_date: date) -> bool:
        """
        Check if a date is a weekend (Friday, Saturday, or Sunday).
        
        Args:
            check_date: Date to check
            
        Returns:
            bool: True if weekend date
        """
        # 0=Monday, 6=Sunday. Weekend includes Friday (4), Saturday (5), Sunday (6)
        return check_date.weekday() >= 4
    
    async def send_alert_notification(
        self,
        alert_rule: AlertRule,
        matching_sites: List[CampsiteAvailability]
    ) -> bool:
        """
        Send notification for matching sites.
        
        Args:
            alert_rule: Alert rule that was matched
            matching_sites: Sites that matched the rule
            
        Returns:
            bool: True if notification was sent successfully
        """
        try:
            # Group sites by park for better email organization
            sites_by_park = defaultdict(list)
            for site in matching_sites:
                sites_by_park[site.park].append(site)
            
            # Send separate emails for each park to avoid overwhelming messages
            notifications_sent = 0
            
            for park, sites in sites_by_park.items():
                # Limit sites per email to avoid spam
                max_sites_per_email = 10
                site_chunks = [
                    sites[i:i + max_sites_per_email]
                    for i in range(0, len(sites), max_sites_per_email)
                ]
                
                for chunk in site_chunks:
                    notification_record = await self.email_service.send_availability_alert(
                        alert_rule, chunk
                    )
                    
                    # Add to batch for storage
                    self.notification_batch.append(notification_record)
                    
                    if notification_record.status == NotificationStatus.SENT:
                        notifications_sent += 1
                        
                        # Track to prevent duplicates in this batch
                        for site in chunk:
                            key = f"{site.park}_{site.site_id}_{site.check_in_date}"
                            self.processed_notifications.add(key)
            
            return notifications_sent > 0
            
        except Exception as e:
            logger.error(f"Failed to send alert notification: {e}")
            return False
    
    async def _store_notification_batch(self) -> None:
        """Store batched notification records."""
        try:
            for notification in self.notification_batch:
                await self.db_client.record_notification(notification)
            
            logger.info(f"Stored {len(self.notification_batch)} notification records")
            self.notification_batch.clear()
            
        except Exception as e:
            logger.error(f"Failed to store notification batch: {e}")
    
    async def generate_daily_summary(
        self,
        target_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Generate daily summary statistics.
        
        Args:
            target_date: Date to generate summary for (defaults to yesterday)
            
        Returns:
            Dict with summary statistics
        """
        if not target_date:
            target_date = date.today() - timedelta(days=1)
        
        try:
            summary = {
                'total_available': 0,
                'weekend_available': 0,
                'notifications_sent': 0,
                'parks': []
            }
            
            # Get availability for each park
            for park in ParkEnum:
                park_availability = await self.db_client.get_availability_by_park(
                    park,
                    start_date=target_date,
                    end_date=target_date,
                    status_filter=[AvailabilityStatus.AVAILABLE]
                )
                
                weekend_count = sum(
                    1 for site in park_availability
                    if self.is_weekend_date(site.check_in_date)
                )
                
                lowest_price = None
                if park_availability:
                    prices = [site.price for site in park_availability if site.price]
                    if prices:
                        lowest_price = min(prices)
                
                park_info = get_park_info(park)
                park_summary = {
                    'name': park_info.display_name,
                    'available_count': len(park_availability),
                    'weekend_count': weekend_count,
                    'lowest_price': lowest_price
                }
                
                summary['parks'].append(park_summary)
                summary['total_available'] += len(park_availability)
                summary['weekend_available'] += weekend_count
            
            # Count notifications sent
            # This would require querying notification_records table
            # For now, we'll use a placeholder
            summary['notifications_sent'] = 0  # TODO: Implement actual count
            
            return summary
            
        except Exception as e:
            logger.error(f"Failed to generate daily summary: {e}")
            return {
                'total_available': 0,
                'weekend_available': 0,
                'notifications_sent': 0,
                'parks': [],
                'error': str(e)
            }
    
    async def cleanup_old_notifications(self, days_to_keep: int = 30) -> int:
        """
        Clean up old notification records.
        
        Args:
            days_to_keep: Number of days of records to keep
            
        Returns:
            int: Number of records cleaned up
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
        
        try:
            # This would require a delete operation via the MCP
            # For now, we'll log the intent
            logger.info(f"Would clean up notification records older than {cutoff_date}")
            return 0  # TODO: Implement actual cleanup
            
        except Exception as e:
            logger.error(f"Failed to cleanup old notifications: {e}")
            return 0
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """Get current processing statistics."""
        return {
            'processed_notifications_count': len(self.processed_notifications),
            'pending_notification_batch': len(self.notification_batch),
            'email_delivery_stats': self.email_service.get_delivery_stats()
        }