from contextlib import contextmanager

@contextmanager
def wls_environment(env: dict):
    yield dict(env)
