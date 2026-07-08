CREATE TABLE IF NOT EXISTS dwd_ord_order_detail (
    id BIGINT,
    order_no STRING,
    user_id BIGINT,
    amount DECIMAL(18, 2),
    paid_at STRING
)
PARTITIONED BY (dt STRING);