class AERAError(Exception):
    pass


class AccessDeniedError(AERAError):
    pass


class ProvisioningError(AERAError):
    pass


class PaymentError(AERAError):
    pass
