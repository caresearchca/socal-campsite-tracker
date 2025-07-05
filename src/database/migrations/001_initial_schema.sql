-- Initial schema for Southern California Campsite Availability Tracker
-- Migration 001: Create core tables for availability tracking

-- Create enum types
CREATE TYPE park_enum AS ENUM ('joshua_tree', 'carlsbad', 'oceanside');
CREATE TYPE site_type_enum AS ENUM ('tent', 'rv', 'cabin', 'group', 'day_use');
CREATE TYPE availability_status_enum AS ENUM ('available', 'booked', 'closed', 'maintenance', 'unknown');
CREATE TYPE notification_status_enum AS ENUM ('pending', 'sent', 'failed', 'skipped');

-- Campsite availability table
CREATE TABLE campsite_availability (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    park park_enum NOT NULL,
    site_id VARCHAR(50) NOT NULL,
    site_name VARCHAR(200) NOT NULL,
    site_type site_type_enum NOT NULL,
    check_in_date DATE NOT NULL,
    status availability_status_enum NOT NULL,
    price DECIMAL(8,2),
    max_occupancy INTEGER,
    amenities TEXT[] DEFAULT '{}',
    scraped_at TIMESTAMP WITH TIME ZONE NOT NULL,
    url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Unique constraint to prevent duplicates
    UNIQUE(park, site_id, check_in_date)
);

-- Alert rules table  
CREATE TABLE alert_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email VARCHAR(255) NOT NULL,
    parks park_enum[] NOT NULL,
    site_types site_type_enum[] NOT NULL,
    weekend_only BOOLEAN DEFAULT true,
    min_nights INTEGER DEFAULT 1 CHECK (min_nights >= 1 AND min_nights <= 14),
    max_price DECIMAL(8,2) CHECK (max_price >= 0),
    advance_notice_days INTEGER DEFAULT 7 CHECK (advance_notice_days >= 1 AND advance_notice_days <= 180),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Scrape results table for monitoring scraping operations
CREATE TABLE scrape_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    park park_enum NOT NULL,
    scrape_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,
    sites_found INTEGER DEFAULT 0 CHECK (sites_found >= 0),
    available_sites INTEGER DEFAULT 0 CHECK (available_sites >= 0),
    errors TEXT[] DEFAULT '{}',
    warnings TEXT[] DEFAULT '{}',
    processing_time_seconds DECIMAL(10,3) CHECK (processing_time_seconds >= 0),
    success BOOLEAN DEFAULT false,
    raw_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Notification records table for tracking sent notifications
CREATE TABLE notification_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_rule_id UUID NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
    campsite_availability_key VARCHAR(200) NOT NULL,
    recipient_email VARCHAR(255) NOT NULL,
    park park_enum NOT NULL,
    site_id VARCHAR(50) NOT NULL,
    check_in_date DATE NOT NULL,
    status notification_status_enum NOT NULL,
    sent_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0 CHECK (retry_count >= 0),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for optimal query performance

-- Availability table indexes
CREATE INDEX idx_availability_park_date ON campsite_availability(park, check_in_date);
CREATE INDEX idx_availability_status ON campsite_availability(status);
CREATE INDEX idx_availability_scraped_at ON campsite_availability(scraped_at);
CREATE INDEX idx_availability_price ON campsite_availability(price) WHERE price IS NOT NULL;

-- Alert rules indexes  
CREATE INDEX idx_alert_rules_email ON alert_rules(user_email);
CREATE INDEX idx_alert_rules_active ON alert_rules(is_active) WHERE is_active = true;
CREATE INDEX idx_alert_rules_parks ON alert_rules USING GIN(parks);

-- Scrape results indexes
CREATE INDEX idx_scrape_results_park_timestamp ON scrape_results(park, scrape_timestamp);
CREATE INDEX idx_scrape_results_success ON scrape_results(success, park);
CREATE INDEX idx_scrape_results_timestamp ON scrape_results(scrape_timestamp);

-- Notification records indexes
CREATE INDEX idx_notifications_alert_rule ON notification_records(alert_rule_id);
CREATE INDEX idx_notifications_park_site_date ON notification_records(park, site_id, check_in_date);
CREATE INDEX idx_notifications_status ON notification_records(status);
CREATE INDEX idx_notifications_created_at ON notification_records(created_at);

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply updated_at triggers
CREATE TRIGGER update_availability_updated_at 
    BEFORE UPDATE ON campsite_availability 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_alert_rules_updated_at 
    BEFORE UPDATE ON alert_rules 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Create a view for available weekend sites
CREATE VIEW available_weekend_sites AS
SELECT 
    ca.*,
    EXTRACT(DOW FROM ca.check_in_date) as day_of_week
FROM campsite_availability ca
WHERE 
    ca.status = 'available'
    AND EXTRACT(DOW FROM ca.check_in_date) IN (0, 6) -- Sunday = 0, Saturday = 6
    AND ca.check_in_date >= CURRENT_DATE
ORDER BY ca.park, ca.check_in_date, ca.site_id;

-- Create a view for scraping performance metrics
CREATE VIEW scraping_metrics AS
SELECT 
    park,
    DATE(scrape_timestamp) as scrape_date,
    COUNT(*) as total_scrapes,
    COUNT(*) FILTER (WHERE success = true) as successful_scrapes,
    AVG(processing_time_seconds) as avg_processing_time,
    AVG(sites_found) as avg_sites_found,
    AVG(available_sites) as avg_available_sites
FROM scrape_results 
GROUP BY park, DATE(scrape_timestamp)
ORDER BY scrape_date DESC, park;

-- Grant appropriate permissions (adjust as needed for your setup)
-- These would be configured based on your specific user roles

-- Add comments for documentation
COMMENT ON TABLE campsite_availability IS 'Stores scraped campsite availability data from California state parks';
COMMENT ON TABLE alert_rules IS 'User-defined rules for availability notifications';
COMMENT ON TABLE scrape_results IS 'Tracking and monitoring of scraping operations';
COMMENT ON TABLE notification_records IS 'Log of all sent notifications to prevent duplicates';

COMMENT ON COLUMN campsite_availability.park IS 'Southern California park identifier';
COMMENT ON COLUMN campsite_availability.site_id IS 'Unique site identifier from reservation system';
COMMENT ON COLUMN campsite_availability.check_in_date IS 'Date availability is for';
COMMENT ON COLUMN campsite_availability.scraped_at IS 'When this data was collected';

COMMENT ON COLUMN alert_rules.weekend_only IS 'Only send alerts for Friday/Saturday/Sunday availability';
COMMENT ON COLUMN alert_rules.advance_notice_days IS 'Minimum days in advance for notifications';

-- Insert initial data if needed
INSERT INTO alert_rules (user_email, parks, site_types, weekend_only, min_nights, max_price) 
VALUES 
    ('admin@example.com', ARRAY['joshua_tree', 'carlsbad'], ARRAY['tent', 'rv'], true, 2, 50.00)
ON CONFLICT DO NOTHING;