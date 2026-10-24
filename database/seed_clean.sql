-- =============================================================================
-- QueryPilot AI — Target Database Schema & Seed Data (Dataset A)
-- This script runs against querypilot_target via a separate init script
-- =============================================================================

\connect querypilot_target

-- Create the sales schema
CREATE SCHEMA IF NOT EXISTS sales;

-- Grant usage on schema
GRANT USAGE ON SCHEMA sales TO target_readonly;

-- =============================================================================
-- Tables
-- =============================================================================

CREATE TABLE IF NOT EXISTS sales.regions (
    region_id SERIAL PRIMARY KEY,
    region_name VARCHAR(50) NOT NULL UNIQUE,
    region_code VARCHAR(10) NOT NULL UNIQUE,
    manager_name VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE sales.regions IS 'Sales regions with assigned managers';
COMMENT ON COLUMN sales.regions.region_name IS 'Full name of the sales region';
COMMENT ON COLUMN sales.regions.region_code IS 'Short code for the region';

CREATE TABLE IF NOT EXISTS sales.customers (
    customer_id SERIAL PRIMARY KEY,
    company_name VARCHAR(200) NOT NULL,
    contact_name VARCHAR(100),
    email VARCHAR(200),
    phone VARCHAR(30),
    city VARCHAR(100),
    state VARCHAR(50),
    region_id INTEGER REFERENCES sales.regions(region_id),
    segment VARCHAR(50) DEFAULT 'Standard',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE sales.customers IS 'Customer accounts';
COMMENT ON COLUMN sales.customers.segment IS 'Customer segment: Enterprise, Mid-Market, Standard, or Small Business';

CREATE TABLE IF NOT EXISTS sales.product_catalog (
    product_id SERIAL PRIMARY KEY,
    product_name VARCHAR(200) NOT NULL,
    category VARCHAR(100) NOT NULL,
    subcategory VARCHAR(100),
    unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
    cost_price NUMERIC(10, 2) NOT NULL CHECK (cost_price >= 0),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE sales.product_catalog IS 'Products available for sale';
COMMENT ON COLUMN sales.product_catalog.unit_price IS 'List price per unit in USD';
COMMENT ON COLUMN sales.product_catalog.cost_price IS 'Cost of goods per unit in USD';

CREATE TABLE IF NOT EXISTS sales.sales_orders (
    order_id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES sales.customers(customer_id),
    order_date DATE NOT NULL,
    ship_date DATE,
    status VARCHAR(20) NOT NULL DEFAULT 'completed'
        CHECK (status IN ('pending', 'processing', 'shipped', 'completed', 'cancelled')),
    region_id INTEGER NOT NULL REFERENCES sales.regions(region_id),
    sales_rep VARCHAR(100),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE sales.sales_orders IS 'Sales order headers';

CREATE TABLE IF NOT EXISTS sales.sales_order_items (
    item_id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES sales.sales_orders(order_id),
    product_id INTEGER NOT NULL REFERENCES sales.product_catalog(product_id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
    discount_pct NUMERIC(5, 2) DEFAULT 0 CHECK (discount_pct >= 0 AND discount_pct <= 100)
);

COMMENT ON TABLE sales.sales_order_items IS 'Line items for each sales order';
COMMENT ON COLUMN sales.sales_order_items.unit_price IS 'Actual sale price per unit (may differ from catalog price)';
COMMENT ON COLUMN sales.sales_order_items.discount_pct IS 'Discount percentage applied to this line item';

CREATE TABLE IF NOT EXISTS sales.regional_targets (
    target_id SERIAL PRIMARY KEY,
    region_id INTEGER NOT NULL REFERENCES sales.regions(region_id),
    target_month INTEGER NOT NULL CHECK (target_month BETWEEN 1 AND 12),
    target_year INTEGER NOT NULL CHECK (target_year >= 2020),
    revenue_target NUMERIC(12, 2) NOT NULL CHECK (revenue_target >= 0),
    UNIQUE (region_id, target_month, target_year)
);

COMMENT ON TABLE sales.regional_targets IS 'Monthly revenue targets by region';

CREATE TABLE IF NOT EXISTS sales.returns (
    return_id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES sales.sales_orders(order_id),
    item_id INTEGER NOT NULL REFERENCES sales.sales_order_items(item_id),
    return_date DATE NOT NULL,
    reason VARCHAR(200),
    refund_amount NUMERIC(10, 2) CHECK (refund_amount >= 0),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE sales.returns IS 'Product returns and refunds';

-- Indexes
CREATE INDEX IF NOT EXISTS idx_orders_date ON sales.sales_orders(order_date);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON sales.sales_orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_region ON sales.sales_orders(region_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON sales.sales_order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product ON sales.sales_order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_customers_region ON sales.customers(region_id);

-- =============================================================================
-- Seed Data
-- =============================================================================

-- Regions
INSERT INTO sales.regions (region_id, region_name, region_code, manager_name) VALUES
(1, 'North',   'NORTH',   'Alice Johnson'),
(2, 'South',   'SOUTH',   'Bob Martinez'),
(3, 'East',    'EAST',    'Carol Chen'),
(4, 'West',    'WEST',    'David Kim'),
(5, 'Central', 'CENTRAL', 'Eve Thompson');
SELECT setval('sales.regions_region_id_seq', 5);

-- Customers
INSERT INTO sales.customers (customer_id, company_name, contact_name, email, city, state, region_id, segment) VALUES
( 1, 'Apex Manufacturing',       'John Smith',       'john@apex-mfg.com',        'Chicago',       'IL', 5, 'Enterprise'),
( 2, 'Bright Solutions',         'Sarah Lee',        'sarah@brightsol.com',       'New York',      'NY', 3, 'Enterprise'),
( 3, 'Cascade Industries',       'Mike Brown',       'mike@cascade-ind.com',      'Seattle',       'WA', 4, 'Mid-Market'),
( 4, 'Delta Corp',               'Lisa Wang',        'lisa@deltacorp.com',        'Boston',        'MA', 3, 'Enterprise'),
( 5, 'Echo Technologies',        'James Miller',     'james@echotech.com',        'Austin',        'TX', 2, 'Mid-Market'),
( 6, 'Frontier Systems',         'Amy Davis',        'amy@frontiersys.com',       'Denver',        'CO', 4, 'Standard'),
( 7, 'Global Dynamics',          'Robert Wilson',    'robert@globaldyn.com',      'Atlanta',       'GA', 2, 'Enterprise'),
( 8, 'Harbor Networks',          'Jennifer Taylor',  'jen@harbornet.com',         'San Francisco', 'CA', 4, 'Mid-Market'),
( 9, 'Innovate Partners',        'Chris Anderson',   'chris@innovatepart.com',    'Minneapolis',   'MN', 1, 'Standard'),
(10, 'Jade Commerce',            'Maria Garcia',     'maria@jadecommerce.com',    'Miami',         'FL', 2, 'Standard'),
(11, 'Keystone Analytics',       'Tom Jackson',      'tom@keystonean.com',        'Philadelphia',  'PA', 3, 'Mid-Market'),
(12, 'Lunar Enterprises',        'Nancy White',      'nancy@lunarent.com',        'Phoenix',       'AZ', 4, 'Small Business'),
(13, 'Metro Services',           'Kevin Harris',     'kevin@metroserv.com',       'Detroit',       'MI', 5, 'Standard'),
(14, 'Nova Solutions',           'Rachel Clark',     'rachel@novasol.com',        'Portland',      'OR', 4, 'Mid-Market'),
(15, 'Orbit Technologies',       'Daniel Lewis',     'daniel@orbittech.com',      'Houston',       'TX', 2, 'Enterprise'),
(16, 'Peak Performance',         'Laura Robinson',   'laura@peakperf.com',        'Salt Lake City','UT', 4, 'Standard'),
(17, 'Quantum Group',            'Steve Walker',     'steve@quantumgrp.com',      'Charlotte',     'NC', 2, 'Mid-Market'),
(18, 'Ridge Solutions',          'Karen Hall',       'karen@ridgesol.com',        'Columbus',      'OH', 5, 'Standard'),
(19, 'Summit Industries',        'Paul Allen',       'paul@summitind.com',        'Milwaukee',     'WI', 1, 'Mid-Market'),
(20, 'Titan Corp',               'Michelle Young',   'michelle@titancorp.com',    'Dallas',        'TX', 2, 'Enterprise'),
(21, 'Unity Software',           'Andrew King',      'andrew@unitysw.com',        'Raleigh',       'NC', 2, 'Standard'),
(22, 'Vista Technologies',       'Susan Wright',     'susan@vistatech.com',       'Indianapolis',  'IN', 5, 'Mid-Market'),
(23, 'Wavelength Solutions',     'Mark Lopez',       'mark@wavelength.com',       'San Diego',     'CA', 4, 'Standard'),
(24, 'Xenon Dynamics',           'Emily Hill',       'emily@xenondyn.com',        'Nashville',     'TN', 2, 'Small Business'),
(25, 'Yield Partners',           'Jason Scott',      'jason@yieldpart.com',       'Kansas City',   'MO', 5, 'Enterprise'),
(26, 'Zenith Manufacturing',     'Diane Green',      'diane@zenithmfg.com',       'Cleveland',     'OH', 5, 'Mid-Market'),
(27, 'Alpha Logistics',          'Brian Adams',      'brian@alphalog.com',        'Minneapolis',   'MN', 1, 'Standard'),
(28, 'Beacon Health',            'Patricia Nelson',  'patricia@beaconhlt.com',    'Boston',        'MA', 3, 'Enterprise'),
(29, 'Coral Systems',            'George Baker',     'george@coralsys.com',       'Tampa',         'FL', 2, 'Standard'),
(30, 'Dune Analytics',           'Sandra Carter',    'sandra@dunean.com',         'Omaha',         'NE', 1, 'Small Business');
SELECT setval('sales.customers_customer_id_seq', 30);

-- Products
INSERT INTO sales.product_catalog (product_id, product_name, category, subcategory, unit_price, cost_price) VALUES
( 1, 'ProDisplay 27" Monitor',       'Electronics',  'Monitors',      499.99, 280.00),
( 2, 'UltraBook Pro Laptop',         'Electronics',  'Laptops',      1299.99, 750.00),
( 3, 'PowerStation Desktop',         'Electronics',  'Desktops',      899.99, 520.00),
( 4, 'SmartDock Hub',                 'Electronics',  'Peripherals',   149.99,  65.00),
( 5, 'WirelessPro Headset',          'Electronics',  'Audio',         199.99,  85.00),
( 6, 'DataVault Enterprise',         'Software',     'Database',      599.99,  50.00),
( 7, 'SecureShield Pro',             'Software',     'Security',      399.99,  35.00),
( 8, 'CloudSync Platform',           'Software',     'Cloud',         249.99,  25.00),
( 9, 'AnalyticsPro Suite',           'Software',     'Analytics',     799.99,  70.00),
(10, 'DevTools Ultimate',            'Software',     'Development',   349.99,  30.00),
(11, 'Premium Support Plan',         'Services',     'Support',       999.99, 400.00),
(12, 'Cloud Migration Package',      'Services',     'Migration',    2499.99, 1200.00),
(13, 'Security Audit Service',       'Services',     'Consulting',   1499.99, 700.00),
(14, 'Training Workshop (5-day)',    'Services',     'Training',     1999.99, 800.00),
(15, 'Custom Integration',           'Services',     'Consulting',   3499.99, 1500.00),
(16, 'RackMount Server R200',        'Hardware',     'Servers',      4999.99, 3200.00),
(17, 'Network Switch 48-Port',       'Hardware',     'Networking',   1299.99, 750.00),
(18, 'Storage Array 10TB',           'Hardware',     'Storage',      2999.99, 1800.00),
(19, 'UPS Battery Backup',           'Hardware',     'Power',         699.99, 350.00),
(20, 'Firewall Appliance',           'Hardware',     'Security',     1899.99, 1100.00),
(21, 'Ergonomic Keyboard',           'Accessories',  'Input',          89.99,  35.00),
(22, 'Precision Mouse',              'Accessories',  'Input',          59.99,  22.00),
(23, 'USB-C Cable Pack (5)',          'Accessories',  'Cables',         29.99,   8.00),
(24, 'Laptop Stand Adjustable',      'Accessories',  'Stands',         79.99,  30.00),
(25, 'Webcam HD Pro',                'Accessories',  'Video',         129.99,  50.00);
SELECT setval('sales.product_catalog_product_id_seq', 25);

-- Orders and items (procedural generation for determinism)
SELECT setseed(0.42);

DO $$
DECLARE
    v_order_id INTEGER;
    v_customer_id INTEGER;
    v_region_id INTEGER;
    v_order_date DATE;
    v_status VARCHAR(20);
    v_product_id INTEGER;
    v_quantity INTEGER;
    v_price NUMERIC(10,2);
    v_discount NUMERIC(5,2);
    v_reps TEXT[] := ARRAY['Alice Johnson','Bob Martinez','Carol Chen','David Kim','Eve Thompson',
                           'Frank Wilson','Grace Lee','Henry Brown','Iris Davis','Jack Moore'];
    v_statuses TEXT[] := ARRAY['completed','completed','completed','completed','completed',
                               'completed','completed','shipped','processing','cancelled'];
    v_num_items INTEGER;
    v_month INTEGER;
    v_day INTEGER;
BEGIN
    FOR i IN 1..300 LOOP
        v_month := LEAST(9, 1 + floor(sqrt(random() * 81))::int);
        v_day := 1 + floor(random() * 28)::int;
        v_order_date := ('2026-01-01'::date + ((v_month - 1) * 30 + v_day - 1) * INTERVAL '1 day')::date;
        v_customer_id := 1 + floor(random() * 30)::int;
        SELECT region_id INTO v_region_id FROM sales.customers WHERE customer_id = v_customer_id;
        v_status := v_statuses[1 + floor(random() * 10)::int];
        
        INSERT INTO sales.sales_orders (customer_id, order_date, ship_date, status, region_id, sales_rep)
        VALUES (
            v_customer_id, v_order_date,
            CASE WHEN v_status IN ('completed','shipped') THEN v_order_date + (1 + floor(random() * 5))::int ELSE NULL END,
            v_status, v_region_id,
            v_reps[1 + floor(random() * 10)::int]
        ) RETURNING order_id INTO v_order_id;
        
        v_num_items := 1 + floor(random() * 5)::int;
        FOR j IN 1..v_num_items LOOP
            v_product_id := 1 + floor(random() * 25)::int;
            v_quantity := 1 + floor(random() * 10)::int;
            SELECT unit_price INTO v_price FROM sales.product_catalog WHERE product_id = v_product_id;
            IF random() < 0.3 THEN
                v_discount := round((5 + random() * 20)::numeric, 2);
            ELSE
                v_discount := 0;
            END IF;
            INSERT INTO sales.sales_order_items (order_id, product_id, quantity, unit_price, discount_pct)
            VALUES (v_order_id, v_product_id, v_quantity, v_price, v_discount);
        END LOOP;
    END LOOP;
END $$;

-- Regional targets
INSERT INTO sales.regional_targets (region_id, target_month, target_year, revenue_target) VALUES
(1,1,2026,80000),(1,2,2026,85000),(1,3,2026,90000),(1,4,2026,95000),(1,5,2026,100000),
(1,6,2026,105000),(1,7,2026,110000),(1,8,2026,115000),(1,9,2026,120000),
(2,1,2026,120000),(2,2,2026,125000),(2,3,2026,130000),(2,4,2026,135000),(2,5,2026,140000),
(2,6,2026,145000),(2,7,2026,150000),(2,8,2026,155000),(2,9,2026,160000),
(3,1,2026,100000),(3,2,2026,105000),(3,3,2026,110000),(3,4,2026,115000),(3,5,2026,120000),
(3,6,2026,125000),(3,7,2026,130000),(3,8,2026,135000),(3,9,2026,140000),
(4,1,2026,150000),(4,2,2026,155000),(4,3,2026,160000),(4,4,2026,165000),(4,5,2026,170000),
(4,6,2026,175000),(4,7,2026,180000),(4,8,2026,185000),(4,9,2026,190000),
(5,1,2026,90000),(5,2,2026,95000),(5,3,2026,100000),(5,4,2026,105000),(5,5,2026,110000),
(5,6,2026,115000),(5,7,2026,120000),(5,8,2026,125000),(5,9,2026,130000);

-- Returns
DO $$
DECLARE
    v_order RECORD;
    v_item RECORD;
    v_reasons TEXT[] := ARRAY['Defective product','Wrong item shipped','Customer changed mind',
                              'Not as described','Duplicate order','Compatibility issue'];
BEGIN
    FOR v_order IN
        SELECT o.order_id, o.order_date FROM sales.sales_orders o
        WHERE o.status = 'completed' ORDER BY o.order_id LIMIT 30
    LOOP
        SELECT * INTO v_item FROM sales.sales_order_items WHERE order_id = v_order.order_id LIMIT 1;
        IF v_item IS NOT NULL THEN
            INSERT INTO sales.returns (order_id, item_id, return_date, reason, refund_amount)
            VALUES (
                v_order.order_id, v_item.item_id,
                v_order.order_date + (3 + floor(random() * 25))::int,
                v_reasons[1 + floor(random() * 6)::int],
                round((v_item.unit_price * v_item.quantity * (1 - v_item.discount_pct / 100) * (0.5 + random() * 0.5))::numeric, 2)
            );
        END IF;
    END LOOP;
END $$;

-- Grant SELECT on all tables to read-only role
GRANT SELECT ON ALL TABLES IN SCHEMA sales TO target_readonly;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA sales TO target_readonly;

-- Set default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA sales GRANT SELECT ON TABLES TO target_readonly;

-- Analyze for query planner statistics
ANALYZE;
