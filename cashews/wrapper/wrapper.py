from functools import lru_cache, partial
from typing import Dict, Tuple

from cashews import validation
from cashews._typing import Middleware
from cashews.backends.interface import Backend
from cashews.commands import Command
from cashews.exceptions import NotConfiguredError

from .auto_init import create_auto_init
from .backend_settings import settings_url_parse
from .disable_control import _is_disable_middleware


class Wrapper:
    default_prefix = ""

    def __init__(self, name: str = ""):
        self._backends: Dict[str, Tuple[Backend, Tuple[Middleware, ...]]] = {}  # {key: (backend, middleware)}
        self._default_middlewares: Tuple[Middleware, ...] = (
            _is_disable_middleware,
            create_auto_init(),
            validation._invalidate_middleware,
        )
        self.name = name
        super().__init__()

    @lru_cache(maxsize=1000)
    def _get_backend_and_config(self, key: str) -> Tuple[Backend, Tuple[Middleware, ...]]:
        for prefix in sorted(self._backends.keys(), reverse=True):
            if key.startswith(prefix):
                return self._backends[prefix]
        if self.default_prefix not in self._backends:
            raise NotConfiguredError("run `cache.setup(...)` before using cache")
        return self._backends[self.default_prefix]

    def _get_backend(self, key: str) -> Backend:
        backend, _ = self._get_backend_and_config(key)
        return backend

    def _with_middlewares(self, cmd: Command, key: str):
        backend, middlewares = self._get_backend_and_config(key)
        return self._with_middlewares_for_backend(cmd, backend, middlewares)

    def _with_middlewares_for_backend(self, cmd: Command, backend, middlewares):
        call = getattr(backend, cmd.value)
        for middleware in middlewares:
            call = partial(middleware, call, cmd, backend)
        return call

    def setup(self, settings_url: str, middlewares: Tuple = (), prefix: str = default_prefix, **kwargs) -> Backend:
        backend_class, params = settings_url_parse(settings_url)
        params.update(kwargs)

        if "disable" in params:
            disable = params.pop("disable")
        else:
            disable = not params.pop("enable", True)

        backend = backend_class(**params)
        if disable:
            backend.disable()
        self._add_backend(backend, middlewares, prefix)
        return backend

    def _add_backend(self, backend: Backend, middlewares=(), prefix: str = default_prefix):
        self._backends[prefix] = (
            backend,
            self._default_middlewares + middlewares,
        )

    async def init(self, *args, **kwargs):
        if args or kwargs:
            self.setup(*args, **kwargs)
        for backend, _ in self._backends.values():
            await backend.init()

    @property
    def is_init(self) -> bool:
        for backend, _ in self._backends.values():
            if not backend.is_init:
                return False
        return True

    async def close(self):
        for backend, _ in self._backends.values():
            await backend.close()