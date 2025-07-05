"""
Email notification system for campsite availability alerts.

Handles sending email notifications when matching campsite availability
is found according to user-defined alert rules.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.utils import formatdate

import aiosmtplib
from jinja2 import Environment, BaseLoader, Template

from ..config.settings import settings
from ..config.parks import get_park_info
from ..database.models import CampsiteAvailability, AlertRule, NotificationRecord, NotificationStatus

logger = logging.getLogger(__name__)


class EmailTemplateLoader(BaseLoader):
    """Custom Jinja2 template loader for email templates."""
    
    def __init__(self):
        self.templates = {
            'availability_alert': self._get_availability_alert_template(),
            'daily_summary': self._get_daily_summary_template(),
            'error_notification': self._get_error_notification_template()
        }
    
    def get_source(self, environment, template):
        if template not in self.templates:
            raise FileNotFoundError(f"Template {template} not found")
        
        source = self.templates[template]
        return source, None, lambda: True
    
    def _get_availability_alert_template(self) -> str:
        """Email template for availability alerts."""
        return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>🏕️ Campsite Available!</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
        .container { max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .header { background: #2d5a27; color: white; padding: 20px; text-align: center; }
        .content { padding: 20px; }
        .site-card { border: 1px solid #ddd; border-radius: 6px; padding: 15px; margin: 10px 0; background: #f9f9f9; }
        .site-name { font-size: 18px; font-weight: bold; color: #2d5a27; margin-bottom: 8px; }
        .site-details { margin: 5px 0; }
        .price { font-size: 16px; font-weight: bold; color: #e67e22; }
        .book-button { display: inline-block; background: #27ae60; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; margin: 10px 0; }
        .footer { background: #f8f8f8; padding: 15px; text-align: center; font-size: 12px; color: #666; }
        .urgent { border-left: 4px solid #e74c3c; padding-left: 10px; background: #fdf2f2; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏕️ Campsite Available!</h1>
            <p>{{ park_display_name }}</p>
        </div>
        
        <div class="content">
            {% if is_weekend %}
            <div class="urgent">
                <strong>⚡ Weekend Availability!</strong> These sites are available for weekend camping.
            </div>
            {% endif %}
            
            <p>Great news! We found {{ site_count }} available campsite{{ 's' if site_count != 1 else '' }} that match{{ '' if site_count != 1 else 'es' }} your alert preferences:</p>
            
            {% for site in sites %}
            <div class="site-card">
                <div class="site-name">{{ site.site_name }}</div>
                <div class="site-details">
                    <strong>Site ID:</strong> {{ site.site_id }}<br>
                    <strong>Type:</strong> {{ site.site_type|title }}<br>
                    <strong>Check-in:</strong> {{ site.check_in_date.strftime('%A, %B %d, %Y') }}<br>
                    {% if site.max_occupancy %}
                    <strong>Max Occupancy:</strong> {{ site.max_occupancy }} people<br>
                    {% endif %}
                    {% if site.amenities %}
                    <strong>Amenities:</strong> {{ site.amenities|join(', ') }}<br>
                    {% endif %}
                </div>
                {% if site.price %}
                <div class="price">${{ "%.2f"|format(site.price) }} per night</div>
                {% endif %}
                {% if site.url %}
                <a href="{{ site.url }}" class="book-button">Book Now</a>
                {% endif %}
            </div>
            {% endfor %}
            
            <p><strong>⏰ Act Fast!</strong> Popular California state park campsites book very quickly, especially weekend spots. We recommend booking immediately if you're interested.</p>
            
            <p><strong>Booking Tips:</strong></p>
            <ul>
                <li>Have your payment information ready</li>
                <li>Consider booking multiple nights if available</li>
                <li>Check cancellation policies before booking</li>
                <li>Popular parks like Joshua Tree fill up within minutes</li>
            </ul>
        </div>
        
        <div class="footer">
            <p>This alert was generated by the Southern California Campsite Tracker</p>
            <p>Sent at {{ sent_time.strftime('%Y-%m-%d %H:%M:%S %Z') }}</p>
            <p><small>You're receiving this because you have an active alert rule. To manage your alerts, contact the administrator.</small></p>
        </div>
    </div>
</body>
</html>
        """.strip()
    
    def _get_daily_summary_template(self) -> str:
        """Daily summary email template."""
        return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>🏕️ Daily Campsite Summary</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
        .container { max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .header { background: #34495e; color: white; padding: 20px; text-align: center; }
        .content { padding: 20px; }
        .summary-section { margin: 20px 0; }
        .park-summary { border: 1px solid #ddd; border-radius: 6px; padding: 15px; margin: 10px 0; }
        .stats { display: flex; justify-content: space-around; text-align: center; margin: 15px 0; }
        .stat { flex: 1; }
        .stat-number { font-size: 24px; font-weight: bold; color: #2c3e50; }
        .stat-label { font-size: 12px; color: #7f8c8d; }
        .footer { background: #f8f8f8; padding: 15px; text-align: center; font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏕️ Daily Campsite Summary</h1>
            <p>{{ summary_date.strftime('%A, %B %d, %Y') }}</p>
        </div>
        
        <div class="content">
            <div class="summary-section">
                <h2>Today's Highlights</h2>
                <div class="stats">
                    <div class="stat">
                        <div class="stat-number">{{ total_available }}</div>
                        <div class="stat-label">Available Sites</div>
                    </div>
                    <div class="stat">
                        <div class="stat-number">{{ weekend_available }}</div>
                        <div class="stat-label">Weekend Available</div>
                    </div>
                    <div class="stat">
                        <div class="stat-number">{{ notifications_sent }}</div>
                        <div class="stat-label">Alerts Sent</div>
                    </div>
                </div>
            </div>
            
            <div class="summary-section">
                <h2>Park Availability</h2>
                {% for park_data in parks %}
                <div class="park-summary">
                    <h3>{{ park_data.name }}</h3>
                    <p><strong>Available Sites:</strong> {{ park_data.available_count }}</p>
                    <p><strong>Weekend Sites:</strong> {{ park_data.weekend_count }}</p>
                    {% if park_data.lowest_price %}
                    <p><strong>Lowest Price:</strong> ${{ "%.2f"|format(park_data.lowest_price) }}</p>
                    {% endif %}
                </div>
                {% endfor %}
            </div>
        </div>
        
        <div class="footer">
            <p>Southern California Campsite Tracker - Daily Summary</p>
            <p>Generated at {{ sent_time.strftime('%Y-%m-%d %H:%M:%S %Z') }}</p>
        </div>
    </div>
</body>
</html>
        """.strip()
    
    def _get_error_notification_template(self) -> str:
        """Error notification email template."""
        return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>🚨 Campsite Tracker Error</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
        .container { max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .header { background: #e74c3c; color: white; padding: 20px; text-align: center; }
        .content { padding: 20px; }
        .error-details { background: #fdf2f2; border-left: 4px solid #e74c3c; padding: 15px; margin: 15px 0; }
        .footer { background: #f8f8f8; padding: 15px; text-align: center; font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚨 System Error Detected</h1>
        </div>
        
        <div class="content">
            <p>An error occurred in the Southern California Campsite Tracker:</p>
            
            <div class="error-details">
                <h3>Error Details</h3>
                <p><strong>Component:</strong> {{ component }}</p>
                <p><strong>Error Type:</strong> {{ error_type }}</p>
                <p><strong>Time:</strong> {{ error_time.strftime('%Y-%m-%d %H:%M:%S %Z') }}</p>
                <p><strong>Message:</strong> {{ error_message }}</p>
            </div>
            
            {% if traceback %}
            <div class="error-details">
                <h3>Technical Details</h3>
                <pre style="white-space: pre-wrap; font-size: 12px;">{{ traceback }}</pre>
            </div>
            {% endif %}
            
            <p>The system will continue attempting to operate normally. If errors persist, manual intervention may be required.</p>
        </div>
        
        <div class="footer">
            <p>Southern California Campsite Tracker - Error Notification</p>
        </div>
    </div>
</body>
</html>
        """.strip()


class EmailNotificationService:
    """
    Service for sending email notifications.
    
    Handles SMTP connections, email templating, and delivery tracking.
    """
    
    def __init__(self):
        """Initialize email service."""
        self.smtp_server = settings.smtp_server
        self.smtp_port = settings.smtp_port
        self.smtp_username = settings.smtp_username
        self.smtp_password = settings.smtp_password
        
        # Initialize Jinja2 environment
        self.template_env = Environment(loader=EmailTemplateLoader())
        
        # Email delivery tracking
        self.delivery_stats = {
            'sent': 0,
            'failed': 0,
            'retries': 0
        }
    
    async def send_availability_alert(
        self,
        alert_rule: AlertRule,
        sites: List[CampsiteAvailability]
    ) -> NotificationRecord:
        """
        Send availability alert email.
        
        Args:
            alert_rule: Alert rule that triggered this notification
            sites: List of available campsites
            
        Returns:
            NotificationRecord: Record of the notification attempt
        """
        if not sites:
            logger.warning("No sites provided for availability alert")
            return self._create_notification_record(
                alert_rule, sites[0] if sites else None, NotificationStatus.SKIPPED, 
                "No sites to notify about"
            )
        
        try:
            # Determine if this is weekend availability
            is_weekend = any(site.check_in_date.weekday() >= 5 for site in sites)
            
            # Get park information
            park_info = get_park_info(sites[0].park)
            
            # Prepare template context
            context = {
                'sites': sites,
                'site_count': len(sites),
                'park_display_name': park_info.display_name,
                'is_weekend': is_weekend,
                'sent_time': datetime.utcnow(),
                'alert_rule': alert_rule
            }
            
            # Render email template
            template = self.template_env.get_template('availability_alert')
            html_content = template.render(**context)
            
            # Create email message
            subject = f"🏕️ {park_info.display_name} - {len(sites)} Campsite{'s' if len(sites) != 1 else ''} Available!"
            if is_weekend:
                subject = f"⚡ WEEKEND! " + subject
            
            # Send email
            success = await self._send_email(
                to_email=alert_rule.user_email,
                subject=subject,
                html_content=html_content
            )
            
            # Create notification record
            status = NotificationStatus.SENT if success else NotificationStatus.FAILED
            return self._create_notification_record(alert_rule, sites[0], status)
            
        except Exception as e:
            logger.error(f"Failed to send availability alert: {e}")
            return self._create_notification_record(
                alert_rule, sites[0] if sites else None, NotificationStatus.FAILED, str(e)
            )
    
    async def send_daily_summary(
        self,
        recipient_email: str,
        summary_data: Dict[str, Any]
    ) -> bool:
        """
        Send daily summary email.
        
        Args:
            recipient_email: Email address to send to
            summary_data: Summary statistics and data
            
        Returns:
            bool: True if successful
        """
        try:
            # Prepare template context
            context = {
                'summary_date': datetime.utcnow().date(),
                'sent_time': datetime.utcnow(),
                **summary_data
            }
            
            # Render email template
            template = self.template_env.get_template('daily_summary')
            html_content = template.render(**context)
            
            # Send email
            subject = f"🏕️ Daily Campsite Summary - {context['summary_date'].strftime('%B %d, %Y')}"
            
            return await self._send_email(
                to_email=recipient_email,
                subject=subject,
                html_content=html_content
            )
            
        except Exception as e:
            logger.error(f"Failed to send daily summary: {e}")
            return False
    
    async def send_error_notification(
        self,
        recipient_email: str,
        component: str,
        error_type: str,
        error_message: str,
        traceback: Optional[str] = None
    ) -> bool:
        """
        Send error notification email.
        
        Args:
            recipient_email: Email address to send to
            component: Component where error occurred
            error_type: Type of error
            error_message: Error message
            traceback: Optional error traceback
            
        Returns:
            bool: True if successful
        """
        try:
            # Prepare template context
            context = {
                'component': component,
                'error_type': error_type,
                'error_message': error_message,
                'error_time': datetime.utcnow(),
                'traceback': traceback
            }
            
            # Render email template
            template = self.template_env.get_template('error_notification')
            html_content = template.render(**context)
            
            # Send email
            subject = f"🚨 Campsite Tracker Error - {component}"
            
            return await self._send_email(
                to_email=recipient_email,
                subject=subject,
                html_content=html_content
            )
            
        except Exception as e:
            logger.error(f"Failed to send error notification: {e}")
            return False
    
    async def test_email_connection(self) -> bool:
        """
        Test SMTP connection.
        
        Returns:
            bool: True if connection successful
        """
        try:
            smtp = aiosmtplib.SMTP(hostname=self.smtp_server, port=self.smtp_port)
            await smtp.connect()
            await smtp.starttls()
            await smtp.login(self.smtp_username, self.smtp_password)
            await smtp.quit()
            
            logger.info("Email connection test successful")
            return True
            
        except Exception as e:
            logger.error(f"Email connection test failed: {e}")
            return False
    
    async def _send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None
    ) -> bool:
        """
        Send email via SMTP.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML email content
            text_content: Optional plain text content
            
        Returns:
            bool: True if successful
        """
        try:
            # Create message
            message = MIMEMultipart('alternative')
            message['From'] = self.smtp_username
            message['To'] = to_email
            message['Subject'] = subject
            message['Date'] = formatdate(localtime=True)
            
            # Add text content (fallback)
            if not text_content:
                # Simple HTML to text conversion
                import re
                text_content = re.sub('<[^<]+?>', '', html_content)
                text_content = re.sub(r'\s+', ' ', text_content).strip()
            
            text_part = MIMEText(text_content, 'plain', 'utf-8')
            html_part = MIMEText(html_content, 'html', 'utf-8')
            
            message.attach(text_part)
            message.attach(html_part)
            
            # Send email
            smtp = aiosmtplib.SMTP(hostname=self.smtp_server, port=self.smtp_port)
            await smtp.connect()
            await smtp.starttls()
            await smtp.login(self.smtp_username, self.smtp_password)
            
            await smtp.send_message(message)
            await smtp.quit()
            
            self.delivery_stats['sent'] += 1
            logger.info(f"Email sent successfully to {to_email}")
            return True
            
        except Exception as e:
            self.delivery_stats['failed'] += 1
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False
    
    def _create_notification_record(
        self,
        alert_rule: AlertRule,
        site: Optional[CampsiteAvailability],
        status: NotificationStatus,
        error_message: Optional[str] = None
    ) -> NotificationRecord:
        """Create a notification record for tracking."""
        if not site:
            # Create a dummy record for failed notifications
            return NotificationRecord(
                alert_rule_id=alert_rule.id or "unknown",
                campsite_availability_key="unknown",
                recipient_email=alert_rule.user_email,
                park=list(alert_rule.parks)[0] if alert_rule.parks else "unknown",
                site_id="unknown",
                check_in_date=datetime.utcnow().date(),
                status=status,
                sent_at=datetime.utcnow() if status == NotificationStatus.SENT else None,
                error_message=error_message
            )
        
        return NotificationRecord(
            alert_rule_id=alert_rule.id or "unknown",
            campsite_availability_key=f"{site.park}_{site.site_id}_{site.check_in_date}",
            recipient_email=alert_rule.user_email,
            park=site.park,
            site_id=site.site_id,
            check_in_date=site.check_in_date,
            status=status,
            sent_at=datetime.utcnow() if status == NotificationStatus.SENT else None,
            error_message=error_message
        )
    
    def get_delivery_stats(self) -> Dict[str, int]:
        """Get email delivery statistics."""
        return self.delivery_stats.copy()