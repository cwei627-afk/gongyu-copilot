"""Explicit new-run initialization in an isolated Compose verification volume."""
from datetime import datetime, timezone
from app.demo_dataset.generate import generate
from app.db import data_directory

state = generate(data_directory(), datetime.now(timezone.utc))
print('Fictional expanded source dataset initialized:', state['heat_count'], state['order_count'], state['batch_count'])
