from app.core.exceptions import AERAError


class XUIError(AERAError):
    pass


class XUIAuthenticationError(XUIError):
    pass


class XUIUnavailableError(XUIError):
    pass
