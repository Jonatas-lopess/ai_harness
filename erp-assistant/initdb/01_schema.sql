CREATE TABLE suppliers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    lead_time_days INT NOT NULL CHECK (lead_time_days > 0)
);

CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    stock INT NOT NULL,
    supplier_id INT NOT NULL REFERENCES suppliers(id),
    safety_stock INT NOT NULL DEFAULT 0 CHECK (safety_stock >= 0)
);

CREATE TABLE sales (
    id SERIAL PRIMARY KEY,
    product_id INT NOT NULL,
    quantity INT NOT NULL,
    sale_date DATE NOT NULL
);

ALTER TABLE sales
    ADD CONSTRAINT fk_product
    FOREIGN KEY (product_id)
    REFERENCES products(id);

CREATE TABLE purchase_orders (
    id SERIAL PRIMARY KEY,
    product_id INT NOT NULL REFERENCES products(id),
    quantity INT NOT NULL CHECK (quantity > 0),
    expected_date DATE NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('open', 'received', 'cancelled'))
);
