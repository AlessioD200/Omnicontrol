from __future__ import annotations

import logging
from typing import Optional
import inspect

try:
    from dbus_next.aio import MessageBus
    from dbus_next.service import ServiceInterface, method
    from dbus_next import BusType
except Exception:  # pragma: no cover - optional dependency
    MessageBus = None  # type: ignore
    ServiceInterface = object  # type: ignore
    method = lambda *a, **k: (lambda f: f)  # type: ignore
    BusType = None  # type: ignore


# dbus-next has evolved: older/newer versions use different kwarg names for
# the service.method decorator. Build a tiny compatibility wrapper that maps
# common names so we can call @method_compat(in_signature='s', out_signature='s')
# and it will work regardless of the installed dbus-next API.
def _make_method_compat(orig_method):
    try:
        sig = inspect.signature(orig_method)
        params = sig.parameters

        def method_compat(**kwargs):
            # Build a mapping of parameters the underlying decorator expects.
            to_pass = {}

            # If the underlying requires a 'name' arg without a default, supply
            # an empty string (dbus-next will validate it's a string).
            name_param = params.get('name')
            if name_param is not None and name_param.default is inspect._empty:
                to_pass['name'] = ''

            # If the underlying supports explicit in_signature/out_signature
            # parameters, pass them through.
            if 'in_signature' in params or 'out_signature' in params:
                if 'in_signature' in params:
                    to_pass['in_signature'] = kwargs.get('in_signature', '')
                if 'out_signature' in params:
                    to_pass['out_signature'] = kwargs.get('out_signature', '')
                return orig_method(**to_pass)

            # Some versions accept 'signature' instead of 'in_signature'. Map it.
            if 'signature' in params:
                if 'in_signature' in kwargs:
                    to_pass['signature'] = kwargs.get('in_signature', '')
                if 'out_signature' in kwargs:
                    to_pass['out_signature'] = kwargs.get('out_signature', '')
                return orig_method(**to_pass)

            # Fallback: decorate with no args (some dbus-next versions accept no args).
            return orig_method()

        return method_compat
    except Exception:
        return orig_method


method_compat = _make_method_compat(method)

logger = logging.getLogger(__name__)


class AgentInterface(ServiceInterface):
    def __init__(self, path: str):
        super().__init__('org.bluez.Agent1')
        self._path = path

    @method_compat(in_signature='', out_signature='')
    def Release(self) -> None:
        logger.info('BlueZ agent Release called')

    @method_compat(in_signature='s', out_signature='s')
    def RequestPinCode(self, device: str) -> str:
        logger.info('RequestPinCode for %s', device)
        # Provide a default PIN code; many devices don't need it
        return '0000'

    @method_compat(in_signature='ss', out_signature='')
    def DisplayPinCode(self, device: str, pincode: str) -> None:
        logger.info('DisplayPinCode %s -> %s', device, pincode)

    @method_compat(in_signature='s', out_signature='u')
    def RequestPasskey(self, device: str) -> int:
        logger.info('RequestPasskey for %s', device)
        return 0

    @method_compat(in_signature='suu', out_signature='')
    def DisplayPasskey(self, device: str, passkey: int, entered: int) -> None:
        logger.info('DisplayPasskey %s %s entered=%s', device, passkey, entered)

    @method_compat(in_signature='su', out_signature='')
    def RequestConfirmation(self, device: str, passkey: int) -> None:
        logger.info('RequestConfirmation %s %s - auto-confirming', device, passkey)
        # Auto-confirm pairing requests
        return None

    @method_compat(in_signature='s', out_signature='')
    def RequestAuthorization(self, device: str) -> None:
        logger.info('RequestAuthorization for %s - authorized', device)
        return None

    @method_compat(in_signature='ss', out_signature='')
    def AuthorizeService(self, device: str, uuid: str) -> None:
        logger.info('AuthorizeService %s %s - authorized', device, uuid)
        return None

    @method_compat(in_signature='', out_signature='')
    def Cancel(self) -> None:
        logger.info('Agent Cancel called')


class BluezAgent:
    def __init__(self, path: str = '/com/omnicontrol/agent', capability: str = 'NoInputNoOutput'):
        self.path = path
        self.capability = capability
        self._bus = None
        self._exported = False

    async def start(self) -> None:
        if MessageBus is None:
            raise RuntimeError('dbus-next not available')
        logger.info('Starting BlueZ DBus agent at %s (capability=%s)', self.path, self.capability)
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        self._bus = bus
        agent = AgentInterface(self.path)
        bus.export(self.path, agent)
        self._exported = True

        # Register with BlueZ AgentManager1
        try:
            proxy = await bus.get_proxy_object('org.bluez', '/org/bluez', ['org.bluez.AgentManager1'])
            manager = proxy.get_interface('org.bluez.AgentManager1')
            await manager.call_register_agent(self.path, self.capability)
            try:
                await manager.call_request_default_agent(self.path)
            except Exception:
                # default-agent may not be supported on all BlueZ versions
                logger.debug('request_default_agent not supported or failed')
            logger.info('BlueZ agent registered successfully')
        except Exception as exc:  # pragma: no cover - runtime dependent
            logger.exception('Failed to register BlueZ agent: %s', exc)
            raise

    async def stop(self) -> None:
        if self._bus and self._exported:
            try:
                proxy = await self._bus.get_proxy_object('org.bluez', '/org/bluez', ['org.bluez.AgentManager1'])
                manager = proxy.get_interface('org.bluez.AgentManager1')
                await manager.call_unregister_agent(self.path)
            except Exception:
                logger.debug('Failed to unregister agent')
        self._exported = False
