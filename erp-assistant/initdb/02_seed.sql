INSERT INTO products (name, price, stock)
VALUES
    ('item1', 10.00, 100),
    ('item2', 20.00, 50),
    ('item3', 30.00, 20);

INSERT INTO sales (product_id, quantity, sale_date)
VALUES
    (1, 5, '2023-01-01'),
    (2, 3, '2023-01-02'),
    (3, 2, '2023-01-03');
