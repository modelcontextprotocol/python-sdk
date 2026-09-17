from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CallRequest(_message.Message):
    __slots__ = ("method", "params_json", "request_id_json", "report_progress")
    METHOD_FIELD_NUMBER: _ClassVar[int]
    PARAMS_JSON_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_JSON_FIELD_NUMBER: _ClassVar[int]
    REPORT_PROGRESS_FIELD_NUMBER: _ClassVar[int]
    method: str
    params_json: bytes
    request_id_json: bytes
    report_progress: bool
    def __init__(self, method: _Optional[str] = ..., params_json: _Optional[bytes] = ..., request_id_json: _Optional[bytes] = ..., report_progress: _Optional[bool] = ...) -> None: ...

class CallEvent(_message.Message):
    __slots__ = ("result_json", "error_json", "notification")
    RESULT_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_JSON_FIELD_NUMBER: _ClassVar[int]
    NOTIFICATION_FIELD_NUMBER: _ClassVar[int]
    result_json: bytes
    error_json: bytes
    notification: Notification
    def __init__(self, result_json: _Optional[bytes] = ..., error_json: _Optional[bytes] = ..., notification: _Optional[_Union[Notification, _Mapping]] = ...) -> None: ...

class Notification(_message.Message):
    __slots__ = ("method", "params_json")
    METHOD_FIELD_NUMBER: _ClassVar[int]
    PARAMS_JSON_FIELD_NUMBER: _ClassVar[int]
    method: str
    params_json: bytes
    def __init__(self, method: _Optional[str] = ..., params_json: _Optional[bytes] = ...) -> None: ...
