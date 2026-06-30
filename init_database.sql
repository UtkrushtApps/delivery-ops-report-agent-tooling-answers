CREATE TABLE IF NOT EXISTS customers (
    customer_id   TEXT PRIMARY KEY,
    full_name     TEXT NOT NULL,
    plan_tier     TEXT NOT NULL,
    account_status TEXT NOT NULL,
    support_tier  TEXT NOT NULL,
    region        TEXT NOT NULL,
    risk_flag     BOOLEAN NOT NULL DEFAULT FALSE,
    total_orders  INTEGER NOT NULL DEFAULT 0,
    last_delivery_at TIMESTAMP,
    signup_date   DATE NOT NULL,
    internal_notes TEXT
);

INSERT INTO customers (customer_id, full_name, plan_tier, account_status, support_tier, region, risk_flag, total_orders, last_delivery_at, signup_date, internal_notes) VALUES
('CUST-1001', 'Asha Menon', 'premium', 'active', 'gold', 'south', FALSE, 142, '2024-05-30 18:22:00', '2022-01-14', 'VIP - do not share notes externally'),
('CUST-1002', 'Diego Ramos', 'standard', 'active', 'silver', 'west', FALSE, 37, '2024-05-28 12:05:00', '2023-07-02', 'Frequent address changes'),
('CUST-1003', 'Mei Lin', 'premium', 'active', 'gold', 'north', TRUE, 88, '2024-05-31 09:41:00', '2021-11-20', 'Chargeback dispute open'),
('CUST-1004', 'Omar Farouk', 'standard', 'inactive', 'bronze', 'east', FALSE, 5, '2023-12-11 20:15:00', '2023-10-01', 'Churned - retention attempted'),
('CUST-1005', 'Lena Novak', 'basic', 'active', 'bronze', 'central', FALSE, 21, '2024-05-15 14:00:00', '2024-02-09', NULL),
('CUST-1006', 'Tomas Vega', 'premium', 'suspended', 'gold', 'west', TRUE, 64, '2024-04-02 11:30:00', '2022-08-19', 'Payment hold - billing review'),
('CUST-1007', 'Priya Shah', 'standard', 'active', 'silver', 'south', FALSE, 49, '2024-05-29 17:48:00', '2023-03-25', NULL);

