"""Sample legacy Python code for testing the AST analyzer."""

# This file intentionally violates Clean Code and SOLID principles
# to serve as a test fixture for the refactoring agent.


class UserOrderManager:
    """A bloated class that violates SRP — handles users AND orders AND emails."""

    def __init__(self, db_connection, email_service, logger_instance):
        self.db = db_connection
        self.email = email_service
        self.logger = logger_instance
        self.cache = {}

    def get_user(self, user_id):
        user = self.db.query("SELECT * FROM users WHERE id = %s" % user_id)
        return user

    def create_user(self, username, email, password, role, department, manager_id, is_active, created_at, updated_at, notes):
        """A function with way too many parameters."""
        self.db.execute(
            "INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)" %
            (username, email, password, role, department, manager_id, is_active, created_at, updated_at, notes)
        )
        self.email.send_welcome(email, username)
        self.logger.info(f"User {username} created")

    def get_order(self, order_id):
        order = self.db.query("SELECT * FROM orders WHERE id = %s" % order_id)
        return order

    def process_order(self, order_id, user_id, payment_method, shipping_address, billing_address, items, discount_code, tax_rate, notes, priority, is_gift, gift_message):
        """Another function with too many parameters and too many lines."""
        order = self.get_order(order_id)
        user = self.get_user(user_id)

        if order is None:
            return None

        if user is None:
            return None

        if order["status"] == "pending":
            if payment_method == "credit_card":
                result = self.db.execute(
                    "INSERT INTO payments (order_id, method, amount) VALUES (%s, %s, %s)" %
                    (order_id, payment_method, order["total"])
                )
                if result:
                    self.db.execute("UPDATE orders SET status = 'paid' WHERE id = %s" % order_id)
                    if discount_code:
                        discount = self.db.query("SELECT * FROM discounts WHERE code = '%s'" % discount_code)
                        if discount and discount["active"]:
                            self.db.execute(
                                "UPDATE orders SET discount = %s WHERE id = %s" %
                                (discount["amount"], order_id)
                            )
                    self.email.send_confirmation(user["email"], order_id)
            elif payment_method == "paypal":
                result = self.db.execute(
                    "INSERT INTO payments (order_id, method, amount) VALUES (%s, %s, %s)" %
                    (order_id, payment_method, order["total"])
                )
                if result:
                    self.db.execute("UPDATE orders SET status = 'paid' WHERE id = %s" % order_id)
                    self.email.send_confirmation(user["email"], order_id)
            elif payment_method == "bank_transfer":
                result = self.db.execute(
                    "INSERT INTO payments (order_id, method, amount) VALUES (%s, %s, %s)" %
                    (order_id, payment_method, order["total"])
                )
                if result:
                    self.db.execute("UPDATE orders SET status = 'paid' WHERE id = %s" % order_id)
                    self.email.send_confirmation(user["email"], order_id)

            if shipping_address:
                self.db.execute(
                    "INSERT INTO shipments (order_id, address) VALUES (%s, '%s')" %
                    (order_id, shipping_address)
                )

            if is_gift and gift_message:
                self.email.send_gift_notification(user["email"], gift_message)

        elif order["status"] == "shipped":
            return {"status": "already_shipped"}

        elif order["status"] == "cancelled":
            return {"status": "cancelled"}

        return {"status": "processed"}

    def cancel_order(self, order_id, reason, notify_user, refund_payment, restock_items, create_ticket):
        """Too many params and mixed concerns."""
        self.db.execute("UPDATE orders SET status = 'cancelled' WHERE id = %s" % order_id)
        if notify_user:
            user = self.db.query("SELECT user_id FROM orders WHERE id = %s" % order_id)
            self.email.send_cancellation(user["email"], reason)
        if refund_payment:
            self.db.execute("DELETE FROM payments WHERE order_id = %s" % order_id)
        if restock_items:
            items = self.db.query("SELECT * FROM order_items WHERE order_id = %s" % order_id)
            for item in items:
                self.db.execute("UPDATE inventory SET quantity = quantity + %s WHERE product_id = %s" % (item["quantity"], item["product_id"]))
        if create_ticket:
            self.db.execute("INSERT INTO tickets (order_id, type, reason) VALUES (%s, 'cancellation', '%s')" % (order_id, reason))

    def send_daily_report(self, manager_email, date_range_start, date_range_end, include_users, include_orders, include_revenue, include_errors, format_type):
        """Yet another function with too many parameters."""
        report_data = {}
        if include_users:
            report_data["users"] = self.db.query("SELECT COUNT(*) FROM users WHERE created_at BETWEEN '%s' AND '%s'" % (date_range_start, date_range_end))
        if include_orders:
            report_data["orders"] = self.db.query("SELECT COUNT(*) FROM orders WHERE created_at BETWEEN '%s' AND '%s'" % (date_range_start, date_range_end))
        if include_revenue:
            report_data["revenue"] = self.db.query("SELECT SUM(amount) FROM payments WHERE created_at BETWEEN '%s' AND '%s'" % (date_range_start, date_range_end))
        if include_errors:
            report_data["errors"] = self.db.query("SELECT COUNT(*) FROM error_logs WHERE created_at BETWEEN '%s' AND '%s'" % (date_range_start, date_range_end))
        self.email.send_report(manager_email, report_data, format_type)

    def validate_user_input(self, username, email, password):
        if not username or len(username) < 3:
            return False
        if not email or "@" not in email:
            return False
        if not password or len(password) < 8:
            return False
        return True

    def hash_password(self, password):
        import hashlib
        return hashlib.md5(password.encode()).hexdigest()

    def check_permission(self, user_id, permission):
        user = self.get_user(user_id)
        if user and user.get("role") == "admin":
            return True
        return False


def massive_utility_function(data, config, logger, db, cache, processor, validator, formatter, serializer, exporter):
    """A standalone function with 10 parameters — clearly needs refactoring."""
    results = []
    for item in data:
        if validator.validate(item):
            processed = processor.process(item, config)
            if processed:
                formatted = formatter.format(processed)
                if formatted:
                    serialized = serializer.serialize(formatted)
                    if serialized:
                        cached = cache.set(serialized.key, serialized.value)
                        if cached:
                            db.save(serialized)
                            results.append(serialized)
                            logger.info(f"Processed item {item.id}")
                        else:
                            logger.warning(f"Cache failed for {item.id}")
                    else:
                        logger.error(f"Serialization failed for {item.id}")
                else:
                    logger.error(f"Formatting failed for {item.id}")
            else:
                logger.warning(f"Processing failed for {item.id}")
        else:
            logger.error(f"Validation failed for {item.id}")
    return results
