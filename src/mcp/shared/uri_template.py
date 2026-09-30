import sys

import mcp_client.shared.uri_template as _implementation
from mcp_client.shared.uri_template import (
    _OPERATOR_SPECS as _OPERATOR_SPECS,
)
from mcp_client.shared.uri_template import (
    _OPERATORS as _OPERATORS,
)
from mcp_client.shared.uri_template import (
    _PCT_TRIPLET_RE as _PCT_TRIPLET_RE,
)
from mcp_client.shared.uri_template import (
    _RESERVED as _RESERVED,
)
from mcp_client.shared.uri_template import (
    _STOP_CHARS as _STOP_CHARS,
)
from mcp_client.shared.uri_template import (
    _VARNAME_RE as _VARNAME_RE,
)
from mcp_client.shared.uri_template import (
    DEFAULT_MAX_TEMPLATE_LENGTH as DEFAULT_MAX_TEMPLATE_LENGTH,
)
from mcp_client.shared.uri_template import (
    DEFAULT_MAX_URI_LENGTH as DEFAULT_MAX_URI_LENGTH,
)
from mcp_client.shared.uri_template import (
    DEFAULT_MAX_VARIABLES as DEFAULT_MAX_VARIABLES,
)
from mcp_client.shared.uri_template import (
    InvalidUriTemplate as InvalidUriTemplate,
)
from mcp_client.shared.uri_template import (
    Operator as Operator,
)
from mcp_client.shared.uri_template import (
    UriTemplate as UriTemplate,
)
from mcp_client.shared.uri_template import (
    Variable as Variable,
)
from mcp_client.shared.uri_template import (
    _Atom as _Atom,
)
from mcp_client.shared.uri_template import (
    _Cap as _Cap,
)
from mcp_client.shared.uri_template import (
    _check_duplicate_variables as _check_duplicate_variables,
)
from mcp_client.shared.uri_template import (
    _check_single_query_expression as _check_single_query_expression,
)
from mcp_client.shared.uri_template import (
    _encode as _encode,
)
from mcp_client.shared.uri_template import (
    _expand_expression as _expand_expression,
)
from mcp_client.shared.uri_template import (
    _Expression as _Expression,
)
from mcp_client.shared.uri_template import (
    _extract_greedy as _extract_greedy,
)
from mcp_client.shared.uri_template import (
    _flatten as _flatten,
)
from mcp_client.shared.uri_template import (
    _is_greedy as _is_greedy,
)
from mcp_client.shared.uri_template import (
    _is_str_sequence as _is_str_sequence,
)
from mcp_client.shared.uri_template import (
    _Lit as _Lit,
)
from mcp_client.shared.uri_template import (
    _OperatorSpec as _OperatorSpec,
)
from mcp_client.shared.uri_template import (
    _parse as _parse,
)
from mcp_client.shared.uri_template import (
    _parse_expression as _parse_expression,
)
from mcp_client.shared.uri_template import (
    _parse_query as _parse_query,
)
from mcp_client.shared.uri_template import (
    _Part as _Part,
)
from mcp_client.shared.uri_template import (
    _partition_greedy as _partition_greedy,
)
from mcp_client.shared.uri_template import (
    _scan_prefix as _scan_prefix,
)
from mcp_client.shared.uri_template import (
    _scan_suffix as _scan_suffix,
)
from mcp_client.shared.uri_template import (
    _split_query_tail as _split_query_tail,
)

sys.modules[__name__] = _implementation
