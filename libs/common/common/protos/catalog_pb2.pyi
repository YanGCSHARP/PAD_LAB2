from typing import ClassVar as _ClassVar

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message

DESCRIPTOR: _descriptor.FileDescriptor

class ReserveTicketsRequest(_message.Message):
    __slots__ = ("booking_id", "category_id", "quantity")
    BOOKING_ID_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_ID_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_FIELD_NUMBER: _ClassVar[int]
    booking_id: str
    category_id: str
    quantity: int
    def __init__(self, booking_id: str | None = ..., category_id: str | None = ..., quantity: int | None = ...) -> None: ...

class ReservationRef(_message.Message):
    __slots__ = ("booking_id",)
    BOOKING_ID_FIELD_NUMBER: _ClassVar[int]
    booking_id: str
    def __init__(self, booking_id: str | None = ...) -> None: ...

class ReservationReply(_message.Message):
    __slots__ = ("booking_id", "event_id", "event_title", "category_id", "category_name", "quantity", "unit_price", "total_price", "status", "starts_at")
    BOOKING_ID_FIELD_NUMBER: _ClassVar[int]
    EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    EVENT_TITLE_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_ID_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_NAME_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_FIELD_NUMBER: _ClassVar[int]
    UNIT_PRICE_FIELD_NUMBER: _ClassVar[int]
    TOTAL_PRICE_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    STARTS_AT_FIELD_NUMBER: _ClassVar[int]
    booking_id: str
    event_id: str
    event_title: str
    category_id: str
    category_name: str
    quantity: int
    unit_price: str
    total_price: str
    status: str
    starts_at: str
    def __init__(self, booking_id: str | None = ..., event_id: str | None = ..., event_title: str | None = ..., category_id: str | None = ..., category_name: str | None = ..., quantity: int | None = ..., unit_price: str | None = ..., total_price: str | None = ..., status: str | None = ..., starts_at: str | None = ...) -> None: ...
