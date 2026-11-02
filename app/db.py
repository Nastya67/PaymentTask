"""Database session of the current thread, reset after every request.

autobegin=False: a query outside a transaction raises instead of silently
opening one, e.g. while waiting for the provider.
expire_on_commit=False: objects stay readable after their transaction commits.
"""

import functools
from collections.abc import Callable

from sqlalchemy.orm import scoped_session, sessionmaker

db_session = scoped_session(sessionmaker(autobegin=False, expire_on_commit=False))


def transactional[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Runs func in its own transaction: commit on return, rollback on error.

    Calling it while a transaction is open raises, so transactions never nest.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        with db_session.begin():
            return func(*args, **kwargs)

    return wrapper
