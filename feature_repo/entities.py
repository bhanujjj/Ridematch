from feast import Entity
from feast.value_type import ValueType

driver = Entity(name="driver_id", join_keys=["driver_id"], value_type=ValueType.STRING)
rider = Entity(name="rider_id", join_keys=["rider_id"], value_type=ValueType.STRING)

