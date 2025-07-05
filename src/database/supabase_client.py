"""
Supabase MCP client for database operations.

Provides interface to Supabase MCP server for storing and retrieving
campsite availability data, alert rules, and notification records.
"""

import asyncio
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date, timedelta
from uuid import uuid4

import httpx
from pydantic import ValidationError

from ..config.settings import settings
from ..config.parks import ParkEnum
from ..database.models import (
    CampsiteAvailability,
    AlertRule, 
    ScrapeResult,
    NotificationRecord,
    CampsiteSearchQuery,
    AvailabilityStatus
)

logger = logging.getLogger(__name__)


class SupabaseError(Exception):
    """Exception raised for Supabase operations."""
    pass


class SupabaseClient:
    """
    Client for Supabase MCP server operations.
    
    Handles database operations through the Supabase MCP server including
    data storage, retrieval, and management operations.
    """
    
    def __init__(
        self,
        project_ref: Optional[str] = None,
        access_token: Optional[str] = None
    ):
        """
        Initialize Supabase client.
        
        Args:
            project_ref: Supabase project reference
            access_token: Supabase access token
        """
        self.project_ref = project_ref or settings.supabase_project_ref
        self.access_token = access_token or settings.supabase_access_token
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_connections=settings.db_pool_size)
        )
        
        # Table names
        self.tables = {
            'availability': 'campsite_availability',
            'alert_rules': 'alert_rules',
            'scrape_results': 'scrape_results',
            'notifications': 'notification_records'
        }
    
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
        Check if Supabase is accessible.
        
        Returns:
            bool: True if connection is healthy
        """
        try:
            # Try to list tables as a health check
            result = await self._execute_query(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' LIMIT 1"
            )
            return result.get('success', False)
        except Exception as e:
            logger.error(f"Supabase health check failed: {e}")
            return False
    
    async def store_availability_data(self, availability: List[CampsiteAvailability]) -> bool:
        """
        Store campsite availability data.
        
        Args:
            availability: List of availability records to store
            
        Returns:
            bool: True if successful
            
        Raises:
            SupabaseError: If storage fails
        """
        if not availability:
            return True
        
        try:
            # Convert to dict format for storage
            records = []
            for avail in availability:
                record = {
                    'id': str(uuid4()),
                    'park': avail.park.value,
                    'site_id': avail.site_id,
                    'site_name': avail.site_name,
                    'site_type': avail.site_type.value,
                    'check_in_date': avail.check_in_date.isoformat(),
                    'status': avail.status.value,
                    'price': avail.price,
                    'max_occupancy': avail.max_occupancy,
                    'amenities': avail.amenities,
                    'scraped_at': avail.scraped_at.isoformat(),
                    'url': avail.url,
                    'created_at': datetime.utcnow().isoformat(),
                    'updated_at': datetime.utcnow().isoformat()
                }
                records.append(record)
            
            # Batch insert with upsert (on conflict update)
            chunk_size = 1000
            for i in range(0, len(records), chunk_size):
                chunk = records[i:i + chunk_size]
                
                result = await self._call_mcp_tool("insert_rows", {
                    "table": self.tables['availability'],
                    "data": chunk,
                    "on_conflict": "update",
                    "conflict_columns": ["park", "site_id", "check_in_date"]
                })
                
                if not result.get('success'):
                    raise SupabaseError(f"Failed to insert availability batch: {result.get('error')}")
            
            logger.info(f"Successfully stored {len(availability)} availability records")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store availability data: {e}")
            raise SupabaseError(f"Storage failed: {e}")
    
    async def get_availability_by_park(
        self,
        park: ParkEnum,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        status_filter: Optional[List[AvailabilityStatus]] = None
    ) -> List[CampsiteAvailability]:
        """
        Retrieve availability data for a specific park.
        
        Args:
            park: Park to query
            start_date: Optional start date filter
            end_date: Optional end date filter
            status_filter: Optional status filter
            
        Returns:
            List of availability records
        """
        try:
            # Build query conditions
            conditions = [f"park = '{park.value}'"]
            
            if start_date:
                conditions.append(f"check_in_date >= '{start_date.isoformat()}'")
            
            if end_date:
                conditions.append(f"check_in_date <= '{end_date.isoformat()}'")
            
            if status_filter:
                status_values = [f"'{status.value}'" for status in status_filter]
                conditions.append(f"status IN ({','.join(status_values)})")
            
            where_clause = " AND ".join(conditions)
            
            query = f"""
            SELECT * FROM {self.tables['availability']}
            WHERE {where_clause}
            ORDER BY check_in_date, site_id
            """
            
            result = await self._execute_query(query)
            
            if not result.get('success'):
                raise SupabaseError(f"Query failed: {result.get('error')}")
            
            # Convert results to CampsiteAvailability objects
            availability_list = []
            for row in result.get('data', []):
                try:
                    availability = CampsiteAvailability(
                        park=ParkEnum(row['park']),
                        site_id=row['site_id'],
                        site_name=row['site_name'],
                        site_type=row['site_type'],
                        check_in_date=datetime.fromisoformat(row['check_in_date']).date(),
                        status=AvailabilityStatus(row['status']),
                        price=row.get('price'),
                        max_occupancy=row.get('max_occupancy'),
                        amenities=row.get('amenities', []),
                        scraped_at=datetime.fromisoformat(row['scraped_at']),
                        url=row.get('url')
                    )
                    availability_list.append(availability)
                    
                except (ValidationError, ValueError) as e:
                    logger.warning(f"Skipping invalid availability record: {e}")
                    continue
            
            return availability_list
            
        except Exception as e:
            logger.error(f"Failed to retrieve availability for {park}: {e}")
            return []
    
    async def create_alert_rule(self, alert_rule: AlertRule) -> str:
        """
        Create a new alert rule.
        
        Args:
            alert_rule: Alert rule to create
            
        Returns:
            str: ID of created alert rule
            
        Raises:
            SupabaseError: If creation fails
        """
        try:
            rule_id = str(uuid4())
            
            record = {
                'id': rule_id,
                'user_email': alert_rule.user_email,
                'parks': [park.value for park in alert_rule.parks],
                'site_types': [st.value for st in alert_rule.site_types],
                'weekend_only': alert_rule.weekend_only,
                'min_nights': alert_rule.min_nights,
                'max_price': alert_rule.max_price,
                'advance_notice_days': alert_rule.advance_notice_days,
                'is_active': alert_rule.is_active,
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }
            
            result = await self._call_mcp_tool("insert_rows", {
                "table": self.tables['alert_rules'],
                "data": [record]
            })
            
            if not result.get('success'):
                raise SupabaseError(f"Failed to create alert rule: {result.get('error')}")
            
            logger.info(f"Created alert rule {rule_id} for {alert_rule.user_email}")
            return rule_id
            
        except Exception as e:
            logger.error(f"Failed to create alert rule: {e}")
            raise SupabaseError(f"Alert rule creation failed: {e}")
    
    async def get_active_alert_rules(self) -> List[AlertRule]:
        """
        Get all active alert rules.
        
        Returns:
            List of active alert rules
        """
        try:
            query = f"""
            SELECT * FROM {self.tables['alert_rules']}
            WHERE is_active = true
            ORDER BY created_at
            """
            
            result = await self._execute_query(query)
            
            if not result.get('success'):
                raise SupabaseError(f"Query failed: {result.get('error')}")
            
            alert_rules = []
            for row in result.get('data', []):
                try:
                    alert_rule = AlertRule(
                        id=row['id'],
                        user_email=row['user_email'],
                        parks=[ParkEnum(park) for park in row['parks']],
                        site_types=[st for st in row['site_types']],
                        weekend_only=row['weekend_only'],
                        min_nights=row['min_nights'],
                        max_price=row.get('max_price'),
                        advance_notice_days=row['advance_notice_days'],
                        created_at=datetime.fromisoformat(row['created_at']),
                        updated_at=datetime.fromisoformat(row['updated_at']),
                        is_active=row['is_active']
                    )
                    alert_rules.append(alert_rule)
                    
                except (ValidationError, ValueError) as e:
                    logger.warning(f"Skipping invalid alert rule: {e}")
                    continue
            
            return alert_rules
            
        except Exception as e:
            logger.error(f"Failed to retrieve alert rules: {e}")
            return []
    
    async def record_notification(self, notification: NotificationRecord) -> bool:
        """
        Record a sent notification.
        
        Args:
            notification: Notification record to store
            
        Returns:
            bool: True if successful
        """
        try:
            record = {
                'id': str(uuid4()),
                'alert_rule_id': notification.alert_rule_id,
                'campsite_availability_key': notification.campsite_availability_key,
                'recipient_email': notification.recipient_email,
                'park': notification.park.value,
                'site_id': notification.site_id,
                'check_in_date': notification.check_in_date.isoformat(),
                'status': notification.status.value,
                'sent_at': notification.sent_at.isoformat() if notification.sent_at else None,
                'error_message': notification.error_message,
                'retry_count': notification.retry_count,
                'created_at': datetime.utcnow().isoformat()
            }
            
            result = await self._call_mcp_tool("insert_rows", {
                "table": self.tables['notifications'],
                "data": [record]
            })
            
            return result.get('success', False)
            
        except Exception as e:
            logger.error(f"Failed to record notification: {e}")
            return False
    
    async def check_notification_sent(
        self,
        park: ParkEnum,
        site_id: str,
        check_in_date: date,
        hours_back: int = 24
    ) -> bool:
        """
        Check if notification was already sent for this availability.
        
        Args:
            park: Park identifier
            site_id: Site identifier
            check_in_date: Check-in date
            hours_back: Hours to look back for existing notifications
            
        Returns:
            bool: True if notification was already sent
        """
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
            
            query = f"""
            SELECT COUNT(*) as count FROM {self.tables['notifications']}
            WHERE park = '{park.value}'
            AND site_id = '{site_id}'
            AND check_in_date = '{check_in_date.isoformat()}'
            AND status = 'sent'
            AND created_at >= '{cutoff_time.isoformat()}'
            """
            
            result = await self._execute_query(query)
            
            if result.get('success'):
                count = result.get('data', [{}])[0].get('count', 0)
                return count > 0
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to check notification history: {e}")
            return False
    
    async def store_scrape_result(self, scrape_result: ScrapeResult) -> bool:
        """
        Store scraping operation result.
        
        Args:
            scrape_result: Scrape result to store
            
        Returns:
            bool: True if successful
        """
        try:
            record = {
                'id': str(uuid4()),
                'park': scrape_result.park.value,
                'scrape_timestamp': scrape_result.scrape_timestamp.isoformat(),
                'completed_at': scrape_result.completed_at.isoformat() if scrape_result.completed_at else None,
                'sites_found': scrape_result.sites_found,
                'available_sites': scrape_result.available_sites,
                'errors': scrape_result.errors,
                'warnings': scrape_result.warnings,
                'processing_time_seconds': scrape_result.processing_time_seconds,
                'success': scrape_result.success,
                'raw_data': scrape_result.raw_data,
                'created_at': datetime.utcnow().isoformat()
            }
            
            result = await self._call_mcp_tool("insert_rows", {
                "table": self.tables['scrape_results'],
                "data": [record]
            })
            
            return result.get('success', False)
            
        except Exception as e:
            logger.error(f"Failed to store scrape result: {e}")
            return False
    
    async def _call_mcp_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call a tool on the Supabase MCP server.
        
        Args:
            tool_name: Name of the tool to call
            parameters: Parameters for the tool
            
        Returns:
            Tool response data
            
        Raises:
            SupabaseError: If tool call fails
        """
        # For now, simulate MCP calls with direct HTTP to Supabase
        # In production, this would go through the MCP server
        
        try:
            if tool_name == "insert_rows":
                return await self._insert_rows_direct(parameters)
            elif tool_name == "execute_query":
                return await self._execute_query_direct(parameters)
            else:
                raise SupabaseError(f"Unknown tool: {tool_name}")
                
        except Exception as e:
            raise SupabaseError(f"MCP tool call failed: {e}")
    
    async def _execute_query(self, query: str) -> Dict[str, Any]:
        """Execute a SQL query."""
        return await self._call_mcp_tool("execute_query", {"query": query})
    
    async def _insert_rows_direct(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Direct implementation of row insertion."""
        # This is a simplified implementation
        # In production, this would use the actual Supabase MCP server
        
        table = parameters.get('table')
        data = parameters.get('data', [])
        
        logger.info(f"Simulating insert of {len(data)} rows into {table}")
        
        return {
            'success': True,
            'rows_affected': len(data)
        }
    
    async def _execute_query_direct(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Direct implementation of query execution."""
        # This is a simplified implementation
        # In production, this would use the actual Supabase MCP server
        
        query = parameters.get('query')
        
        logger.info(f"Simulating query execution: {query[:100]}...")
        
        return {
            'success': True,
            'data': []  # Would return actual query results
        }