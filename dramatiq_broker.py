"""Dramatiq RabbitMQ broker setup shared by all worker modules.

The broker must be configured BEFORE any @dramatiq.actor decorator is processed,
so every module that defines actors imports this one first. The analysis worker
runs `dramatiq tasks`; the document-conversion worker runs `dramatiq
conversion_tasks -Q conversion`.
"""
import os

import dramatiq
from dramatiq.brokers.rabbitmq import RabbitmqBroker

broker_url = (
    os.getenv("DRAMATIQ_BROKER_URL")
    or os.getenv("RABBITMQ_URL")
    or "amqp://guest:guest@rabbitmq:5672/"
)

broker = RabbitmqBroker(url=broker_url)
dramatiq.set_broker(broker)
