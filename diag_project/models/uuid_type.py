from uuid import UUID as PyUUID
import uuid

from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy import TypeDecorator, CHAR
from sqlalchemy.dialects import postgresql

class GUID(TypeDecorator):
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(postgresql.UUID())
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, PyUUID):
            return str(value)
        if isinstance(value, str):
            # UUID 형식인지 확인 (선택 사항이지만 권장)
            try:
                uuid.UUID(value)
                return value
            except ValueError:
                raise ValueError(f"Invalid UUID string: '{value}'")
        raise ValueError(f"Cannot bind '{value}' of type {type(value)} as GUID.")

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, str):
            return PyUUID(value)
        raise ValueError(f"Cannot process result '{value}' of type {type(value)} as GUID.")

    def copy_value(self, value):
        return value