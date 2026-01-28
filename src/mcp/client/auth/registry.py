"""
协议注册表。

提供多协议授权实现的注册与选择逻辑。
"""

from mcp.client.auth.protocol import AuthProtocol


class AuthProtocolRegistry:
    """
    授权协议注册表。

    用于注册和获取协议实现类，并根据服务器声明的可用协议、默认协议及优先级选择协议。
    """

    _protocols: dict[str, type[AuthProtocol]] = {}

    @classmethod
    def register(cls, protocol_id: str, protocol_class: type[AuthProtocol]) -> None:
        """
        注册协议实现。

        Args:
            protocol_id: 协议标识（如 oauth2、api_key）
            protocol_class: 实现 AuthProtocol 的类（非实例）
        """
        cls._protocols[protocol_id] = protocol_class

    @classmethod
    def get_protocol_class(cls, protocol_id: str) -> type[AuthProtocol] | None:
        """
        获取协议实现类。

        Args:
            protocol_id: 协议标识

        Returns:
            协议类，未注册时返回 None
        """
        return cls._protocols.get(protocol_id)

    @classmethod
    def select_protocol(
        cls,
        available_protocols: list[str],
        default_protocol: str | None = None,
        preferences: dict[str, int] | None = None,
    ) -> str | None:
        """
        从服务器声明的可用协议中选出一个客户端支持的协议。

        选择顺序：
        1. 过滤出客户端已注册的协议
        2. 若存在默认协议且客户端支持，则优先返回默认协议
        3. 若有优先级映射，按优先级数值升序排序后取第一个
        4. 否则返回第一个支持的协议

        Args:
            available_protocols: 服务器声明的可用协议 ID 列表
            default_protocol: 服务器推荐的默认协议 ID（可选）
            preferences: 协议优先级映射，数值越小优先级越高（可选）

        Returns:
            选中的协议 ID，若无交集则返回 None
        """
        supported = [p for p in available_protocols if p in cls._protocols]
        if not supported:
            return None

        if default_protocol and default_protocol in supported:
            return default_protocol

        if preferences:
            supported.sort(key=lambda p: preferences.get(p, 999))

        return supported[0] if supported else None

    @classmethod
    def list_registered(cls) -> list[str]:
        """
        返回已注册的协议 ID 列表（便于测试或调试）。

        Returns:
            已注册的 protocol_id 列表
        """
        return list(cls._protocols.keys())
