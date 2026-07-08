CREATE TABLE IF NOT EXISTS ods_ord_order_hour (
    id BIGINT,
    order_no STRING,
    amount DECIMAL(18, 2),
    created_at STRING
)
PARTITIONED BY (dt STRING);