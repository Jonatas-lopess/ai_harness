-- Cenários da fase 2. Datas fixas (não CURRENT_DATE): testes usam as_of = 2026-01-31, janela de 30 dias.
-- Vendas em [2026-01-01, 2026-01-31).
INSERT INTO suppliers (name, lead_time_days)
VALUES
    ('supplier-fast', 5),
    ('supplier-slow', 10);

INSERT INTO products (name, price, stock, supplier_id, safety_stock)
VALUES
    ('rupture',        10.00,  40, 2, 5),  -- 10/dia, ponto 105, sem pedido: sinaliza
    ('covered-by-po',  20.00,  40, 2, 5),  -- igual, mas pedido aberto de 100 cobre
    ('false-alarm',    30.00, 100, 1, 2),  -- 1/dia, ponto 7, estoque folgado
    ('received-po',    40.00,  40, 2, 5);  -- igual a rupture; pedido já recebido não conta

INSERT INTO sales (product_id, quantity, sale_date)
VALUES
    (1, 150, '2026-01-10'), (1, 150, '2026-01-20'),
    (2, 150, '2026-01-10'), (2, 150, '2026-01-20'),
    (3,  15, '2026-01-10'), (3,  15, '2026-01-20'),
    (4, 150, '2026-01-10'), (4, 150, '2026-01-20'),
    -- venda fora da janela: não pode entrar na demanda
    (3, 999, '2025-12-01'),
    (3, 999, '2026-01-31');

INSERT INTO purchase_orders (product_id, quantity, expected_date, status)
VALUES
    (2, 100, '2026-02-05', 'open'),
    (4, 100, '2026-01-25', 'received'),
    (1, 500, '2026-02-10', 'cancelled');
